from dataclasses import asdict
from datetime import datetime
from zoneinfo import ZoneInfo

from app.ai.report import build_report
from app.config import CLOSED_NOTE, DISCLAIMER, EXIT_STOP_PCT, MIN_AMOUNT, STALE_SEC
from app.data import stock_sdk_bridge as sdk
from app.data import tdx
from app.data.boards import BoardBook
from app.data.parse import is_limit, vwap_from_turnover
from app.data.provider import Provider
from app.engine.decide import decide
from app.engine.exit import ExitInputs, classify_exit
from app.engine.levels import compute_reference, entry_from_quote, index_range_pos, near_low, upper_shadow
from app.engine.market import classify_market
from app.engine.pick import PickInputs, pick
from app.engine.pool import candidate_of, cap_groups, is_bj, is_st, screen_one, universe_ok
from app.engine.sector import classify_sector
from app.engine.sector_history import build_histories, close_returns, proxy_board_pcts
from app.engine.session import session_info
from app.engine.stock_read import stock_read
from app.engine.types import MarketInputs, SectorInputs
from app.engine.wave2 import scan_wave2, scan_wave2_started
from app.store.db import Database
from app.store.journal import backfill, log_buy, recent_signals, summarize
from app import config
from app.config_etf import ETF_ACTIVE_LIMIT, etf_by_code
from app.data import etf as etf_data
from app.engine.etf import build_etf_rows

SH = ZoneInfo("Asia/Shanghai")


class Hub:
    def __init__(self, db: Database | None = None):
        self.db = db or Database(config.DB_PATH)
        self.provider = Provider(self.db)
        self.market_inputs = MarketInputs(ready=False)
        self.pool = {
            "pullback": [],
            "breakout": [],
            "hold": [],
            "leader": [],
            "watch": [],
            "candidate": [],
            "weak_candidate": [],
            "wave2": [],
            "wave2_started": [],
        }
        self.etf_pool = {
            "broad": [],
            "value": [],
            "active": [],
            "all": [],
            "env_note": "",
            "weak_env": False,
            "whitelist_size": 0,
            "quoted": 0,
        }
        self.etf_quotes: dict[str, dict] = {}
        self.etf_error = ""
        self.etf_spot_at = 0.0
        self.etf_bars_ready = 0
        self._etf_bar_queue: list[str] = []
        self.factor_target = 0
        self.factor_ready = 0
        self._last_spot = 0.0
        self.sector_histories: dict[str, list] = {}
        self._sector_token = None
        self.boards = BoardBook(self.db)
        self.universe_codes: list[str] = []

    async def close(self) -> None:
        await self.provider.close()

    async def refresh_indices(self) -> None:
        await self.provider.refresh_indices()
        self.market_inputs = self._market_inputs()

    async def refresh_spot(self) -> None:
        await self.provider.refresh_spot()
        self.market_inputs = self._market_inputs()
        self._last_spot = self.provider.spot_at
        self._save_sector_snapshot()
        self.rebuild_pool()
        backfill(self.db)
        try:
            await self.refresh_etf()
        except Exception:
            self.etf_error = "ETF 池刷新失败"

    async def fill_factors(self) -> int:
        count = await self.provider.fill_factor_batch()
        await self.provider.open()
        boarded = 0
        if self.provider.client and self.universe_codes and self.provider.price_date:
            boarded = await self.boards.fill_some(self.provider.client, self.universe_codes, self.provider.price_date)
        etf_filled = 0
        try:
            etf_filled = await self.fill_etf_bars()
        except Exception:
            etf_filled = 0
        if count or boarded:
            self.rebuild_pool()
            backfill(self.db)
        if etf_filled:
            self.rebuild_etf_pool()
        return count or boarded or etf_filled

    def _market_inputs(self) -> MarketInputs:
        quotes = self.provider.index_quotes
        bars = self.provider.index_bars
        sh = quotes.get("000001") or {}
        cy = quotes.get("399006") or {}
        sz = quotes.get("399001") or {}
        sh_bars = bars.get("000001") or []
        cy_bars = bars.get("399006") or []
        sz_bars = bars.get("399001") or []
        price_date = self.provider.price_date
        sh_ref_bars = _before(sh_bars, price_date)
        cy_ref_bars = _before(cy_bars, price_date)
        sh_ref = compute_reference(sh_ref_bars) if len(sh_ref_bars) >= 21 else None
        cy_ref = compute_reference(cy_ref_bars) if len(cy_ref_bars) >= 21 else None
        info = session_info()
        avg_amount, avg_volume, today_volume = _bar_baselines(sh_bars, sz_bars, price_date)
        total = (sh.get("amount") or 0) + (sz.get("amount") or 0)
        basis = "amount"
        if avg_amount and total:
            ratio = total / avg_amount
            if info["open"] and info["progress"] > 0:
                ratio = total / (avg_amount * max(info["progress"], 0.05))
        elif avg_volume and today_volume:
            basis = "volume"
            ratio = today_volume / avg_volume
            if info["open"] and info["progress"] > 0:
                ratio = today_volume / (avg_volume * max(info["progress"], 0.05))
            total = total or today_volume
        else:
            ratio = 1.0
        up, down, zt, dt = self.provider.breadth()
        emotion_source = "通达信/快照"
        northbound_note = "宏观资金（北向）缺失，不假装有数"
        emo = sdk.market_emotion()
        if emo.get("ok"):
            emotion_source = "通达信+stock-sdk"
            if emo.get("zt_pool_count") is not None and (zt or 0) == 0:
                zt = int(emo["zt_pool_count"] or 0)
                emotion_source = "stock-sdk涨停池"
            if emo.get("dt_pool_count") is not None and (dt or 0) == 0:
                dt = int(emo["dt_pool_count"] or 0)
            north = emo.get("northbound")
            if north is not None:
                northbound_note = f"北向抽样已接入（stock-sdk）：{_north_brief(north)}"
            else:
                northbound_note = "北向接口无返回，门上标注宏观资金缺失"
        sh_price = sh.get("price") or 0
        cy_price = cy.get("price") or 0
        ready = bool(sh_ref and cy_ref and sh_price and cy_price)
        return MarketInputs(
            ready=ready,
            sh_above_ma20=bool(sh_ref and sh_price >= sh_ref["ma20"]),
            cy_above_ma20=bool(cy_ref and cy_price >= cy_ref["ma20"]),
            sh_ma20_up=bool(sh_ref and sh_ref["ma20_up"]),
            cy_ma20_up=bool(cy_ref and cy_ref["ma20_up"]),
            sh_pct=sh.get("pct") or 0,
            cy_pct=cy.get("pct") or 0,
            amount_ratio=ratio,
            amount_reliable=bool(info["amount_reliable"] and (avg_amount or avg_volume)),
            sh_range_pos=index_range_pos(sh_price, sh_ref_bars),
            sh_upper_shadow=upper_shadow(sh.get("open") or 0, sh.get("high") or 0, sh.get("low") or 0, sh_price),
            sh_near_low=near_low(sh_price, sh.get("high") or 0, sh.get("low") or 0),
            up_count=up,
            down_count=down,
            zt_count=zt,
            dt_count=dt,
            sh_price=sh_price,
            cy_price=cy_price,
            sz_price=sz.get("price") or 0,
            sz_pct=sz.get("pct") or 0,
            total_amount=total,
            avg_amount_5=avg_amount or avg_volume or 0,
            amount_basis=basis,
            sh_ma20=(sh_ref or {}).get("ma20") or 0,
            cy_ma20=(cy_ref or {}).get("ma20") or 0,
            northbound_note=northbound_note,
            emotion_source=emotion_source,
        )

    def rebuild_pool(self) -> None:
        fresh = self.provider.db.factor_codes_as_of(self.provider.price_date) if self.provider.price_date else set()
        ranked = self.provider.ranked_quotes()
        universe = []
        for row in ranked:
            if len(universe) >= config.POOL_FACTOR_UNIVERSE:
                break
            if universe_ok(row["code"], row["name"], row.get("amount") or 0, row.get("circ_mv") or 0, row.get("suspended")):
                universe.append(row["code"])
        self.universe_codes = list(universe)
        self.factor_target = len(universe)
        self.factor_ready = len([code for code in universe if code in fresh])
        self._refresh_sector_history()
        tdx.prefetch_board_flows(self._flow_codes(universe))
        fresh_codes = [code for code in universe if code in fresh]
        tdx.prefetch_stock_flows(fresh_codes)
        rows = []
        trade_date = self.provider.price_date
        info = session_info()
        index_ret_5d = _return_over(self.provider.index_bars.get("000001") or [], None, 5, trade_date)
        for code in universe:
            if code not in fresh:
                continue
            quote = self.provider.quotes.get(code)
            factor = self.db.get_factor(code)
            if not quote or not factor:
                continue
            sector = self._sector_inputs(quote)
            vol_ratio = _volume_ratio(quote, factor, info)
            vwap = vwap_from_turnover(quote.get("price") or 0, quote.get("volume") or 0, quote.get("amount") or 0) if info.get("open") else None
            entry = entry_from_quote(
                factor,
                quote.get("price") or 0,
                quote.get("pct") or 0,
                vol_ratio,
                vwap,
                quote.get("amount") or 0,
                bool(quote.get("suspended")),
            )
            picked = _pick_inputs(self.db, quote, entry, sector, trade_date, index_ret_5d)
            _enrich_entry(entry, self.db, quote, sector, picked)
            item = screen_one(
                self.market_inputs,
                sector,
                entry,
                code=code,
                name=quote.get("name") or "",
                industry=sector.name or quote.get("industry") or "",
                amount=quote.get("amount") or 0,
                circ_mv=quote.get("circ_mv") or 0,
                volume_ratio=vol_ratio,
            )
            extra = candidate_of(
                self.market_inputs,
                sector,
                entry,
                picked,
                code=code,
                name=quote.get("name") or "",
                industry=sector.name or quote.get("industry") or "",
                amount=quote.get("amount") or 0,
                circ_mv=quote.get("circ_mv") or 0,
                volume_ratio=vol_ratio,
            )
            if extra:
                rows.append(extra)
            wave = scan_wave2(
                self.db.load_bars(code),
                code=code,
                name=quote.get("name") or "",
                price=entry.price,
                day_pct=entry.day_pct,
                volume_ratio=vol_ratio,
            )
            if wave.hit:
                rows.append(
                    {
                        "code": code,
                        "name": quote.get("name") or "",
                        "industry": sector.name or quote.get("industry") or "",
                        "price": entry.price,
                        "pct": entry.day_pct,
                        "bucket": "wave2",
                        "setup": "wave2",
                        "verdict": "观望",
                        "reason": wave.reason,
                        "watch_text": f"一波高点约 {wave.high:.2f}，回调中等二波",
                        "sector_rank": sector.rank,
                        "dist_ma10": entry.price / entry.ma10 - 1 if entry.ma10 else 0,
                        "volume_ratio": vol_ratio,
                        "scores": {},
                        "amount": quote.get("amount") or 0,
                        "limit_days": wave.limit_days,
                        "pullback_days": wave.pullback_days,
                    }
                )
            started = scan_wave2_started(
                self.db.load_bars(code),
                code=code,
                name=quote.get("name") or "",
                price=entry.price,
                day_pct=entry.day_pct,
                volume_ratio=vol_ratio,
            )
            if started.hit:
                rows.append(
                    {
                        "code": code,
                        "name": quote.get("name") or "",
                        "industry": sector.name or quote.get("industry") or "",
                        "price": entry.price,
                        "pct": entry.day_pct,
                        "bucket": "wave2_started",
                        "setup": "wave2_started",
                        "verdict": "观望",
                        "reason": started.reason,
                        "watch_text": "二波已启动迹象，仍须过三道门才可买",
                        "sector_rank": sector.rank,
                        "dist_ma10": entry.price / entry.ma10 - 1 if entry.ma10 else 0,
                        "volume_ratio": vol_ratio,
                        "scores": {},
                        "amount": quote.get("amount") or 0,
                        "limit_days": started.limit_days,
                        "pullback_days": started.pullback_days,
                    }
                )
            if not item:
                continue
            rows.append(item)
            if item["verdict"] == "可买" and trade_date:
                decision = decide(self.market_inputs, sector, entry)
                log_buy(
                    self.db,
                    decision,
                    code=code,
                    name=item["name"],
                    price=item["price"],
                    trade_date=trade_date,
                    sector_name=sector.name,
                    sector_rank=sector.rank,
                    source="pool",
                )
        grouped = cap_groups(rows)
        now = session_info()
        for group in grouped.values():
            for item in group:
                item["as_of"] = self.provider.spot_at
        self.pool = grouped

    def _save_sector_snapshot(self) -> None:
        trade_date = self.provider.price_date
        industries = self.provider.industries
        if not trade_date or not industries:
            return
        total = len(industries)
        rows = []
        inflows = []
        for index, row in enumerate(industries, start=1):
            inflow = row.get("inflow")
            for item in row.get("inflows") or []:
                if item.get("date") == trade_date and inflow is None:
                    inflow = item.get("inflow")
                elif item.get("date") and item.get("date") != trade_date:
                    inflows.append({"trade_date": item["date"], "name": row["name"], "inflow": item.get("inflow")})
            rows.append(
                {
                    "name": row["name"],
                    "rank": index,
                    "total": total,
                    "pct": row.get("pct") or 0,
                    "amount": row.get("amount") or 0,
                    "inflow": inflow,
                }
            )
        self.db.save_sector_snapshot(trade_date, rows)
        self.db.save_sector_inflows(inflows)

    def _refresh_sector_history(self) -> None:
        token = (self.factor_ready, self.provider.price_date, self.provider.spot_at)
        if token == self._sector_token:
            return
        members: dict[str, list[str]] = {}
        for code, name in self.provider._industry_map.items():
            if name:
                members.setdefault(name, []).append(code)
        if not members:
            for row in self.provider.quotes.values():
                name = row.get("industry") or ""
                if name:
                    members.setdefault(name, []).append(row["code"])
        series = self.db.load_close_series({"000001", "399001", "399006"})
        index_bars = self.provider.index_bars.get("000001") or []
        index_pct = close_returns([(bar.trade_date, bar.close) for bar in index_bars])
        names = [row["name"] for row in self.provider.industries] or list(members)
        self.sector_histories = build_histories(
            names,
            proxy_board_pcts(members, series),
            self.db.load_official_sectors(),
            index_pct,
        )
        self._sector_token = token

    def _flow_codes(self, codes: list[str]) -> list[str]:
        found = []
        for code in codes:
            cached = self.db.get_stock_boards(code)
            data = (cached or {}).get("data") or {}
            industry = data.get("industry") or {}
            if industry.get("code"):
                found.append(str(industry["code"]))
            for row in data.get("boards") or []:
                if row.get("core_hint") and row.get("code"):
                    found.append(str(row["code"]))
        return found

    def _sector_inputs(self, quote: dict) -> SectorInputs:
        code = quote.get("code") or ""
        built = self.boards.build(code, _stock_returns(self.db, code), _index_pcts(self.provider.index_bars.get("000001") or []))
        if built is not None:
            return built
        return SectorInputs(ready=False, name="", index_pct=self.market_inputs.sh_pct)

    async def judge(self, query: str, *, log: bool = True) -> dict:
        found = self.provider.resolve(query)
        if found.get("error") == "empty":
            return {"error": "empty", "message": "先输入股票代码或名称"}
        if found.get("error") == "ambiguous":
            return {"error": "ambiguous", "message": "名称对上了多只股票", "candidates": found["candidates"]}
        if found.get("error") == "missing":
            return {"error": "missing", "message": "没有找到这只股票，用 6 位代码再试一次"}
        code = found["code"]
        if is_bj(code):
            return {"error": "unsupported", "message": "暂不覆盖北交所"}
        quote = self.provider.live_quote(code)
        info = session_info()
        age = _age(self.provider.spot_at)
        if quote and info["open"] and age is not None and age > STALE_SEC:
            quote = await self.provider.refresh_one(code) or quote
        if not quote or not quote.get("price"):
            quote = await self.provider.refresh_one(code)
        if not quote or not quote.get("price"):
            return {"error": "missing", "message": "行情里还没有这只股票"}
        factor = await self.provider.ensure_bars(code)
        warnings = []
        if is_st(quote.get("name") or ""):
            warnings.append("这是 ST，池子里已排除，波动规则和普通股票不一样")
        if (quote.get("amount") or 0) < MIN_AMOUNT:
            warnings.append("成交额不到 2 亿，滑点会比较大")
        vol_ratio = _volume_ratio(quote, factor, info)
        # 收盘后不再用分时均价否决，那是盘中追价才用的。
        vwap = vwap_from_turnover(quote.get("price") or 0, quote.get("volume") or 0, quote.get("amount") or 0) if info.get("open") else None
        entry = entry_from_quote(
            factor,
            quote.get("price") or 0,
            quote.get("pct") or 0,
            vol_ratio,
            vwap,
            quote.get("amount") or 0,
            bool(quote.get("suspended")),
        )
        await self.provider.open()
        trade_date = self.provider.price_date or info["as_of_date"]
        if self.provider.client:
            await self.boards.ensure(self.provider.client, code, trade_date)
        sector = self._sector_inputs(quote)
        index_ret_5d = _return_over(self.provider.index_bars.get("000001") or [], None, 5, trade_date)
        picked = _pick_inputs(self.db, quote, entry, sector, trade_date, index_ret_5d)
        _enrich_entry(entry, self.db, quote, sector, picked)
        decision = decide(self.market_inputs, sector, entry, warnings)
        picked_view = pick(picked)
        bars = self.db.load_bars(code)
        wave = scan_wave2(
            bars,
            code=code,
            name=quote.get("name") or "",
            price=entry.price,
            day_pct=entry.day_pct,
            volume_ratio=vol_ratio,
        )
        if log:
            log_buy(
                self.db,
                decision,
                code=code,
                name=quote.get("name") or code,
                price=quote.get("price") or 0,
                trade_date=trade_date,
                sector_name=sector.name,
                sector_rank=sector.rank,
                source="decide",
            )
        payload = _decision_payload(decision, quote, sector, info)
        payload["factor_ready"] = factor is not None
        payload["pick_text"] = picked_view.reason
        payload["candidate"] = picked_view.selected
        payload["weak_candidate"] = picked_view.weak
        payload["stock_read"] = stock_read(entry, bars, volume_ratio=vol_ratio, flow_3d=entry.stock_flow_3d)
        payload["wave2"] = wave.hit
        payload["wave2_text"] = wave.reason if wave.hit else ""
        started = scan_wave2_started(
            bars,
            code=code,
            name=quote.get("name") or "",
            price=entry.price,
            day_pct=entry.day_pct,
            volume_ratio=vol_ratio,
        )
        payload["wave2_started"] = started.hit
        payload["wave2_started_text"] = started.reason if started.hit else ""
        if wave.hit:
            payload["warnings"] = list(payload.get("warnings") or []) + ["模式命中：龙头二波·回调等二波"]
        if started.hit:
            payload["warnings"] = list(payload.get("warnings") or []) + ["模式命中：龙头二波·已启动（不等于可买）"]
        payload["report"] = build_report(
            quote=quote,
            market=self.market_inputs,
            sector=sector,
            entry=entry,
            decision_verdict=decision.verdict,
            stock_read_text=payload.get("stock_read") or "",
            pick_text=picked_view.reason,
            wave2_text=payload.get("wave2_started_text") or payload.get("wave2_text") or "",
        )
        payload["changes_verdict"] = False
        return payload

    async def report(self, query: str) -> dict:
        base = await self.judge(query, log=False)
        if base.get("error"):
            return {**base, "changes_verdict": False}
        return {
            "code": base.get("code"),
            "name": base.get("name"),
            "verdict": base.get("verdict"),
            "changes_verdict": False,
            "report": base.get("report") or {},
            "disclaimer": DISCLAIMER,
        }

    def market_payload(self) -> dict:
        view = classify_market(self.market_inputs)
        info = session_info()
        age = _age(self.provider.index_at)
        return {
            "regime": view.regime,
            "env_tier": view.env_tier,
            "position_cap": view.position_cap,
            "reason": view.reason,
            "amount_label": view.amount_label,
            "amount_basis": self.market_inputs.amount_basis,
            "amount_ratio": view.amount_ratio,
            "total_amount": view.total_amount,
            "avg_amount_5": view.avg_amount_5,
            "sh": {"price": view.sh_price, "pct": view.sh_pct, "ma20": view.sh_ma20},
            "cy": {"price": view.cy_price, "pct": view.cy_pct, "ma20": view.cy_ma20},
            "sz": {"price": view.sz_price, "pct": view.sz_pct},
            "up_count": view.up_count,
            "down_count": view.down_count,
            "zt_count": view.zt_count,
            "dt_count": view.dt_count,
            "northbound_note": view.northbound_note or self.market_inputs.northbound_note,
            "emotion_source": self.market_inputs.emotion_source,
            "session": info,
            "index_at": self.provider.index_at,
            "spot_at": self.provider.spot_at,
            "index_age_sec": age,
            "spot_age_sec": _age(self.provider.spot_at),
            "stale": age is None or age > STALE_SEC,
            "index_source": self.provider.index_source,
            "quote_source": self.provider.quote_source,
            "price_date": self.provider.price_date,
            "error": self.provider.last_error,
            "closed_note": "" if info["open"] else CLOSED_NOTE if info["state"] == "closed" else info["label"],
            "disclaimer": DISCLAIMER,
        }

    def pool_payload(self) -> dict:
        info = session_info()
        health = self.data_health()
        mview = classify_market(self.market_inputs) if self.market_inputs else None
        return {
            "pullback": self.pool.get("pullback") or [],
            "breakout": self.pool.get("breakout") or [],
            "hold": self.pool.get("hold") or [],
            "leader": self.pool.get("leader") or [],
            "watch": self.pool.get("watch") or [],
            "candidate": self.pool.get("candidate") or [],
            "weak_candidate": self.pool.get("weak_candidate") or [],
            "wave2": self.pool.get("wave2") or [],
            "wave2_started": self.pool.get("wave2_started") or [],
            "factor_ready": self.factor_ready,
            "factor_target": self.factor_target,
            "factor_pending": max(0, len(self.provider._factor_queue)),
            "boards_ready": health["boards_ready"],
            "boards_target": health["boards_target"],
            "health": health,
            "health_note": health.get("note") or "",
            "spot_at": self.provider.spot_at,
            "spot_age_sec": _age(self.provider.spot_at),
            "stale": _age(self.provider.spot_at) is None or _age(self.provider.spot_at) > STALE_SEC,
            "session": info,
            "regime": mview.regime if mview else None,
            "env_tier": mview.env_tier if mview else None,
            "disclaimer": DISCLAIMER,
        }

    async def refresh_etf(self) -> None:
        """拉白名单 ETF 现货并重建池；失败不抛到个股链路。"""
        await self.provider.open()
        if not self.provider.client:
            self.etf_error = "HTTP 客户端未就绪"
            return
        meta = etf_by_code()
        try:
            quotes = await etf_data.fetch_etf_spot(self.provider.client, list(meta))
        except Exception as exc:
            self.etf_error = f"ETF 现货失败：{exc}"
            return
        self.etf_quotes = quotes
        self.etf_spot_at = datetime.now(tz=SH).timestamp()
        self.etf_error = "" if quotes else "ETF 现货为空"
        # 日 K 队列：缺 bars 的优先
        missing = [c for c in meta if len(self.db.load_bars(c)) < 25]
        self._etf_bar_queue = missing + [c for c in meta if c not in missing]
        self.rebuild_etf_pool()

    async def fill_etf_bars(self) -> int:
        if not self._etf_bar_queue:
            meta = etf_by_code()
            self._etf_bar_queue = list(meta)
        await self.provider.open()
        if not self.provider.client:
            return 0
        batch = self._etf_bar_queue[:8]
        self._etf_bar_queue = self._etf_bar_queue[8:]
        filled = await etf_data.fill_etf_bars(self.provider.client, self.db, batch, limit=8)
        if filled:
            self.rebuild_etf_pool()
        return filled

    def rebuild_etf_pool(self) -> None:
        meta = etf_by_code()
        bars_by_code = {code: self.db.load_bars(code) for code in meta}
        self.etf_bars_ready = sum(1 for code, bars in bars_by_code.items() if len(bars) >= 25)
        mview = classify_market(self.market_inputs) if self.market_inputs else None
        built = build_etf_rows(
            meta,
            self.etf_quotes,
            bars_by_code,
            env_tier=(mview.env_tier if mview else "") or "",
            regime=(mview.regime if mview else "") or "",
            active_limit=ETF_ACTIVE_LIMIT,
        )
        self.etf_pool = built

    def etf_payload(self) -> dict:
        info = session_info()
        mview = classify_market(self.market_inputs) if self.market_inputs else None
        pool = self.etf_pool or {}
        return {
            "broad": pool.get("broad") or [],
            "value": pool.get("value") or [],
            "active": pool.get("active") or [],
            "all": pool.get("all") or [],
            "env_note": pool.get("env_note") or "",
            "weak_env": bool(pool.get("weak_env")),
            "whitelist_size": pool.get("whitelist_size") or len(etf_by_code()),
            "quoted": pool.get("quoted") or len(self.etf_quotes),
            "bars_ready": self.etf_bars_ready,
            "bars_target": len(etf_by_code()),
            "spot_at": self.etf_spot_at,
            "error": self.etf_error,
            "regime": mview.regime if mview else None,
            "env_tier": mview.env_tier if mview else None,
            "session": info,
            "disclaimer": DISCLAIMER,
            "note": "ETF 结论为本页分档（性价比关注/观望/偏贵），不套用个股三道门可买。宽基救市敏感为经验标签。",
        }

    def data_health(self) -> dict:
        trade_date = self.provider.price_date or ""
        boards_ready = self.boards.aligned_count(self.universe_codes, trade_date)
        boards_target = len(self.universe_codes)
        stale_boards = 0
        flow_ok = 0
        flow_n = 0
        for code in self.universe_codes[:80]:
            cached = self.db.get_stock_boards(code)
            data = (cached or {}).get("data") or {}
            industry = data.get("industry") or {}
            board_code = str(industry.get("code") or "")
            if board_code:
                closes = self.boards.closes.get(board_code) or {}
                if trade_date and (not closes or max(closes) < trade_date):
                    stale_boards += 1
            flows = tdx.stock_inflows(code)
            flow_n += 1
            if flows:
                flow_ok += 1
        notes = []
        if self.provider.quote_source != "通达信":
            notes.append(f"成交额名单来源是 {self.provider.quote_source or '未知'}，不是通达信。")
        if boards_target and boards_ready < boards_target:
            notes.append(f"同花顺板块已对齐 {boards_ready}/{boards_target}。")
        if stale_boards:
            notes.append(f"有 {stale_boards} 个主板块日K落后于交易日。")
        if flow_n and flow_ok < flow_n * 0.5:
            notes.append(f"抽查个股资金流有数 {flow_ok}/{flow_n}，偏少。")
        sdk_stats = sdk.bridge_stats()
        if sdk_stats.get("fail") and not sdk_stats.get("ok"):
            notes.append("stock-sdk 备源暂不可用，不假装有数。")
        elif sdk_stats.get("ok"):
            notes.append(f"stock-sdk 备源可用（成功 {sdk_stats['ok']} 次）。")
        if self.market_inputs.emotion_source:
            notes.append(f"情绪来源：{self.market_inputs.emotion_source}。")
        if self.market_inputs.northbound_note:
            notes.append(self.market_inputs.northbound_note)
        return {
            "quote_source": self.provider.quote_source,
            "index_source": self.provider.index_source,
            "boards_ready": boards_ready,
            "boards_target": boards_target,
            "stale_board_closes": stale_boards,
            "flow_ok": flow_ok,
            "flow_checked": flow_n,
            "sdk": sdk_stats,
            "emotion_source": self.market_inputs.emotion_source,
            "northbound_note": self.market_inputs.northbound_note,
            "note": " ".join(notes),
        }

    def stats_payload(self) -> dict:
        return summarize(self.db.signal_rows())

    def signals_payload(self) -> dict:
        return {"rows": recent_signals(self.db), "disclaimer": DISCLAIMER}

    def add_position(
        self,
        *,
        code: str,
        name: str = "",
        entry_price: float | None = None,
        entry_date: str = "",
        stop_pct: float | None = None,
        note: str = "",
    ) -> dict:
        code = (code or "").strip()
        if not code or is_bj(code):
            return {"error": "bad_code", "message": "需要有效的沪深股票代码"}
        quote = self.provider.quotes.get(code) or self.provider.live_quote(code) or {}
        price = entry_price if entry_price and entry_price > 0 else (quote.get("price") or 0)
        if not price:
            return {"error": "no_price", "message": "没有买入价或现价，记不进去"}
        info = session_info()
        day = entry_date or self.provider.price_date or info.get("as_of_date") or datetime.now(SH).date().isoformat()
        stop = float(stop_pct) if stop_pct and stop_pct > 0 else EXIT_STOP_PCT
        name = name or quote.get("name") or code
        row = self.db.upsert_open_position(
            {
                "code": code,
                "name": name,
                "entry_price": float(price),
                "entry_date": day,
                "stop_pct": stop,
                "note": note or "",
                "created_at": datetime.now(SH).isoformat(timespec="seconds"),
            }
        )
        return {"ok": True, "position": row, "disclaimer": DISCLAIMER}

    def close_position(self, code: str) -> dict:
        code = (code or "").strip()
        if not code:
            return {"error": "bad_code", "message": "缺少代码"}
        ok = self.db.close_position(code, datetime.now(SH).isoformat(timespec="seconds"))
        if not ok:
            return {"error": "missing", "message": "没有这只开仓持仓"}
        return {"ok": True, "code": code, "disclaimer": DISCLAIMER}

    def positions_payload(self) -> dict:
        mview = classify_market(self.market_inputs)
        info = session_info()
        price_date = self.provider.price_date or info.get("as_of_date") or ""
        rows = []
        alerts = []
        for pos in self.db.open_positions():
            item = self._position_row(pos, mview, price_date)
            rows.append(item)
            if item.get("urgency") == "high":
                alerts.append(item)
        rows.sort(key=lambda r: ({"high": 0, "mid": 1, "low": 2}.get(r.get("urgency") or "low", 9), r.get("code") or ""))
        return {
            "rows": rows,
            "alerts": alerts,
            "alert_count": len(alerts),
            "open_count": len(rows),
            "disclaimer": DISCLAIMER,
        }

    def _position_row(self, pos: dict, mview, price_date: str) -> dict:
        code = pos["code"]
        quote = self.provider.quotes.get(code) or self.provider.live_quote(code) or {}
        factor = self.db.get_factor(code)
        price = quote.get("price") or 0
        info = session_info()
        vol_ratio = _volume_ratio(quote, factor, info) if factor else None
        sector = self._sector_inputs(quote) if quote else SectorInputs(ready=False)
        sview = classify_sector(sector)
        hold_days = _hold_trading_days(self.db.load_bars(code), pos.get("entry_date") or "", price_date)
        exit_view = classify_exit(
            ExitInputs(
                entry_price=pos.get("entry_price") or 0,
                price=price or 0,
                stop_pct=pos.get("stop_pct") or EXIT_STOP_PCT,
                hold_days=hold_days,
                ma10=(factor or {}).get("ma10") or 0,
                ma20=(factor or {}).get("ma20") or 0,
                ma20_up=bool((factor or {}).get("ma20_up")),
                volume_ratio=vol_ratio,
                high_20=(factor or {}).get("high_20") or 0,
                market_block_new=bool(mview.block_new),
                env_tier=mview.env_tier,
                sector_persist=sview.persist or "",
                sector_weak=bool(sview.weak),
            )
        )
        return {
            "id": pos.get("id"),
            "code": code,
            "name": pos.get("name") or quote.get("name") or code,
            "entry_price": pos.get("entry_price"),
            "entry_date": pos.get("entry_date"),
            "stop_pct": pos.get("stop_pct"),
            "note": pos.get("note") or "",
            "price": price,
            "pct": quote.get("pct"),
            "hold_days": hold_days,
            "pnl_pct": exit_view.pnl_pct,
            "exit_status": exit_view.status,
            "exit_reason": exit_view.reason,
            "exit_tag": exit_view.tag,
            "urgency": exit_view.urgency,
            "industry": sector.name or quote.get("industry") or "",
        }


def _hold_trading_days(bars, entry_date: str, price_date: str) -> int:
    if not entry_date:
        return 0
    dates = [bar.trade_date for bar in bars if bar.trade_date >= entry_date]
    if price_date:
        dates = [day for day in dates if day <= price_date]
    if not dates:
        return 0
    return max(0, len(dates) - 1)


def _enrich_entry(entry, db, quote: dict, sector: SectorInputs, picked: PickInputs) -> None:
    entry.ret_5d_pct = picked.ret_5d_pct
    entry.index_ret_5d_pct = picked.index_ret_5d_pct
    entry.stock_flow_3d = sum(picked.flow_3d) if picked.flow_3d else None
    if entry.stock_flow_3d is None:
        alt = sdk.flow_3d_sum(quote.get("code") or "")
        if alt is not None:
            entry.stock_flow_3d = alt
            if not picked.flow_3d:
                picked.flow_3d = [alt / 3, alt / 3, alt / 3]
    entry.limit_up = picked.limit_up
    entry.board_core = _board_core(db, quote.get("code") or "", sector)
    entry.volume_ratio = picked.volume_ratio if picked.volume_ratio is not None else entry.volume_ratio
    entry.turnover = picked.turnover


def _board_core(db, code: str, sector: SectorInputs) -> bool:
    if sector.amount_pct is not None and sector.amount_pct <= config.LEADER_AMOUNT_PCT:
        return True
    cached = db.get_stock_boards(code)
    data = (cached or {}).get("data") or {}
    industry = data.get("industry") or {}
    if industry.get("core_hint"):
        return True
    for row in data.get("boards") or []:
        if row.get("core_hint"):
            return True
    board_code = str(industry.get("code") or "")
    if board_code:
        hint = sdk.concept_core(board_code, code)
        if hint.get("ok") and (hint.get("is_core") or hint.get("core")):
            return True
    return False


def _pick_inputs(db, quote: dict, entry, sector: SectorInputs, price_date: str, index_ret_5d: float | None) -> PickInputs:
    bars = db.load_bars(quote.get("code") or "")
    inflows = tdx.stock_inflows(quote.get("code") or "") or {}
    dates3 = _recent_dates(bars, price_date, 3)
    dates5 = _recent_dates(bars, price_date, 5)
    flow3 = [inflows.get(day) for day in dates3]
    flow5 = [inflows.get(day) for day in dates5]
    flow_3d = flow3 if len(flow3) == 3 and all(item is not None for item in flow3) else None
    if flow_3d is None:
        alt = sdk.flow_3d_sum(quote.get("code") or "")
        if alt is not None:
            flow_3d = [alt / 3, alt / 3, alt / 3]
    flow_5d = sum(flow5) if len(flow5) == 5 and all(item is not None for item in flow5) else None
    ret_5d = _return_over(bars, entry.price, 5, price_date)
    sector_view = classify_sector(sector)
    turnover = quote.get("turnover") or quote.get("turnover_rate")
    try:
        turnover = float(turnover) if turnover is not None else None
    except (TypeError, ValueError):
        turnover = None
    return PickInputs(
        price=entry.price,
        day_pct=entry.day_pct,
        ma5=entry.ma5,
        ma10=entry.ma10,
        ma20=entry.ma20,
        ma20_up=entry.ma20_up,
        high_20=entry.high_20,
        low_20=entry.low_20,
        ret_10d_pct=entry.ret_10d_pct,
        ret_5d_pct=0.0 if ret_5d is None else ret_5d,
        index_ret_5d_pct=0.0 if index_ret_5d is None else index_ret_5d,
        limit_up=is_limit(quote.get("code") or "", quote.get("name") or "", quote.get("pct"), 1),
        sector_ready=bool(sector_view.ready),
        sector_persist=sector_view.persist,
        flow_3d=flow_3d,
        price_up_3d=_price_up_3d(bars, dates3, entry.day_pct, price_date),
        flow_5d=flow_5d,
        amount_5d=_amount_over(bars, price_date, 5, quote.get("amount") or 0),
        sector_rank=sector.rank,
        sector_total=sector.total,
        volume_ratio=entry.volume_ratio,
        turnover=turnover,
    )


def _series_until(bars, price_date: str):
    return [bar for bar in bars if not price_date or bar.trade_date <= price_date]


def _return_over(bars, price: float | None, sessions: int, price_date: str) -> float | None:
    series = _series_until(bars, price_date)
    if len(series) < sessions + 1:
        return None
    end = price if price else series[-1].close
    base = series[-(sessions + 1)].close
    if not base or not end:
        return None
    return (end / base - 1) * 100


def _recent_dates(bars, price_date: str, count: int) -> list[str]:
    series = _series_until(bars, price_date)
    if len(series) < count:
        return []
    return [bar.trade_date for bar in series[-count:]]


def _price_up_3d(bars, dates: list[str], day_pct: float, price_date: str) -> bool:
    if len(dates) < 3:
        return False
    prev = None
    prev_of = {}
    closes = {}
    for bar in _series_until(bars, price_date):
        closes[bar.trade_date] = bar.close
        if prev:
            prev_of[bar.trade_date] = prev
        prev = bar.close
    total = 0.0
    for day in dates:
        if day == price_date:
            total += day_pct
        elif prev_of.get(day):
            total += (closes[day] / prev_of[day] - 1) * 100
        else:
            return False
    return total > 0


def _amount_over(bars, price_date: str, count: int, today_amount: float) -> float:
    series = _series_until(bars, price_date)
    window = series[-count:]
    if len(window) < count:
        return 0.0
    total = sum(bar.amount or 0 for bar in window)
    if price_date and window[-1].trade_date == price_date and not window[-1].amount:
        total += today_amount
    return total


def _index_pcts(bars) -> dict[str, float]:
    return close_returns([(bar.trade_date, bar.close) for bar in bars])


def _stock_returns(db, code: str) -> dict[str, float]:
    return close_returns([(bar.trade_date, bar.close) for bar in db.load_bars(code)])


def _before(bars, price_date):
    if price_date and bars and bars[-1].trade_date == price_date:
        return bars[:-1]
    return list(bars)


def _bar_baselines(sh_bars, sz_bars, price_date: str) -> tuple[float | None, float | None, float | None]:
    """返回近 5 日平均成交额、平均成交量，以及评估日当天的成交量。成交额为 0 时调用方改用量能。"""

    def table(bars, field: str) -> dict[str, float]:
        return {b.trade_date: getattr(b, field) or 0 for b in bars}

    sh_amt, sz_amt = table(sh_bars, "amount"), table(sz_bars, "amount")
    sh_vol, sz_vol = table(sh_bars, "volume"), table(sz_bars, "volume")
    dates = [d for d in sorted(set(sh_amt) & set(sz_amt)) if d != price_date]
    last = dates[-5:]
    avg_amount = None
    if len(last) >= 5 and sum(sh_amt[d] + sz_amt[d] for d in last) > 0:
        avg_amount = sum(sh_amt[d] + sz_amt[d] for d in last) / 5
    avg_volume = None
    if len(last) >= 5 and sum(sh_vol.get(d, 0) + sz_vol.get(d, 0) for d in last) > 0:
        avg_volume = sum(sh_vol.get(d, 0) + sz_vol.get(d, 0) for d in last) / 5
    today_volume = None
    if price_date in sh_vol and price_date in sz_vol:
        today_volume = sh_vol[price_date] + sz_vol[price_date]
    return avg_amount, avg_volume, today_volume


def _volume_ratio(quote: dict, factor: dict | None, info: dict) -> float | None:
    given = quote.get("volume_ratio")
    if given:
        return given
    avg = (factor or {}).get("avg_volume_5") or 0
    vol = quote.get("volume") or 0
    if not avg or not vol:
        return None
    if vol < avg / 50:
        vol *= 100
    elif avg < vol / 50:
        vol = vol / 100
    progress = info["progress"] if info.get("open") else 1
    return vol / (avg * max(progress or 1, 0.05))


def _age(ts: float) -> float | None:
    if not ts:
        return None
    import time

    return max(0.0, time.time() - ts)


def _decision_payload(decision, quote: dict, sector: SectorInputs, info: dict) -> dict:
    return {
        "code": quote.get("code"),
        "name": quote.get("name"),
        "price": quote.get("price"),
        "pct": quote.get("pct"),
        "industry": sector.name or quote.get("industry") or "",
        "verdict": decision.verdict,
        "setup": decision.setup,
        "reason_line": decision.reason_line,
        "gates": [asdict(g) for g in decision.gates],
        "vetoes": decision.vetoes,
        "watch_text": decision.watch_text,
        "watch_price": decision.watch_price,
        "warnings": decision.warnings,
        "scores": decision.scores,
        "logic_track": decision.logic_track,
        "env_tier": decision.env_tier,
        "position_advice": decision.position_advice,
        "theme_quality": decision.theme_quality,
        "sector_stage": decision.sector_stage,
        "session": info,
        "closed_note": "" if info["open"] else CLOSED_NOTE if info["state"] == "closed" else info["label"],
        "disclaimer": DISCLAIMER,
        "limit_up": is_limit(quote.get("code") or "", quote.get("name") or "", quote.get("pct"), 1),
    }


def _north_brief(north) -> str:
    if isinstance(north, (int, float)):
        return f"{north:+.2f}"
    if isinstance(north, dict):
        for key in ("net", "netInflow", "value", "today", "summary"):
            if north.get(key) is not None:
                return str(north[key])[:80]
        return "有数据"
    return str(north)[:80]

