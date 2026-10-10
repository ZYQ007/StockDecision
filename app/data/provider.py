"""行情缓存。指数现价优先通达信，全市场与板块走东财，日 K 优先东财前复权。"""

import asyncio
import time

import httpx

from app.config import FACTOR_BATCH, POOL_FACTOR_UNIVERSE, TOP_CONCEPTS
from app.data import eastmoney, sina, tdx
from app.data.parse import fnum, index_market, is_limit, market_of
from app.engine.levels import compute_reference
from app.engine.pool import universe_ok
from app.store.db import Database


def _bars_before(bars, price_date: str | None):
    if price_date and bars and bars[-1].trade_date == price_date:
        return bars[:-1]
    return list(bars)


class Provider:
    def __init__(self, db: Database):
        self.db = db
        self.client: httpx.AsyncClient | None = None
        self.quotes: dict[str, dict] = {}
        self.industries: list[dict] = []
        self.concepts: list[dict] = []
        self.index_quotes: dict[str, dict] = {}
        self.index_bars: dict[str, list] = {}
        self.spot_at = 0.0
        self.index_at = 0.0
        self.quote_source = ""
        self.index_source = ""
        self.amount_leaders: list[str] = []
        self.last_error = ""
        self.price_date = ""
        self._factor_queue: list[str] = []
        self._fail_until: dict[str, float] = {}
        self._em_down_until = 0.0
        self._industry_map: dict[str, str] = {}
        self._industry_map_at = 0.0
        self._flow_date = ""

    async def open(self) -> None:
        if self.client is None:
            self.client = httpx.AsyncClient(timeout=httpx.Timeout(12.0), follow_redirects=True)

    async def close(self) -> None:
        if self.client is not None:
            await self.client.aclose()
            self.client = None

    async def refresh_indices(self) -> None:
        await self.open()
        tdx_quotes = await asyncio.to_thread(tdx.fetch_index_quotes)
        em_quotes = None
        if time.time() >= self._em_down_until:
            em_quotes = await eastmoney.fetch_index_quotes(self.client)
        quotes, source = _merge_index_quotes(tdx_quotes, em_quotes)
        if not quotes or "000001" not in quotes or "399006" not in quotes:
            self._em_down_until = time.time() + 600
            quotes = await sina.fetch_index_quotes(self.client)
            source = "sina" if quotes else source
        if not quotes or "000001" not in quotes:
            self.last_error = "指数行情暂时拉不到"
            return
        self.index_quotes = quotes
        self.index_source = source
        self.index_at = time.time()
        self.last_error = ""
        from app.engine.session import session_info

        info = session_info()
        last = self.index_bars.get("000001") or []
        last_date = last[-1].trade_date if last else ""
        if not last or (info["open"] and last_date != info["as_of_date"]):
            await self._load_index_bars()

    async def _load_index_bars(self) -> None:
        for code in ("000001", "399001", "399006"):
            bars = await asyncio.to_thread(tdx.fetch_bars, code, index_market(code), True)
            if len(bars) < 30 and time.time() >= self._em_down_until:
                bars = await eastmoney.fetch_kline(self.client, code, qfq=False, index=True)
            if len(bars) < 30:
                self._em_down_until = time.time() + 600
                bars = await sina.fetch_kline(self.client, code, index=True)
            if len(bars) < 30:
                bars = await asyncio.to_thread(_ak_index_bars, code)
            if bars:
                self.index_bars[code] = bars
                self.db.replace_bars(code, bars)
        if self.index_bars.get("000001"):
            self.price_date = self.index_bars["000001"][-1].trade_date

    async def refresh_spot(self) -> None:
        await self.open()
        rows: list = []
        industries: list = []
        concepts: list = []
        source = ""
        if time.time() >= self._em_down_until:
            try:
                rows = await eastmoney.fetch_spot(self.client)
                industries = await eastmoney.fetch_boards(self.client, "industry")
                concepts = await eastmoney.fetch_boards(self.client, "concept")
                source = "eastmoney"
            except Exception as exc:
                self.last_error = f"东财快照失败：{exc}"
                rows, industries, concepts, source = [], [], [], ""
        if len(rows) >= 1000 and source == "eastmoney" and industries and self._flow_date != (self.price_date or "pending"):
            await eastmoney.attach_board_flows(self.client, industries)
            self._flow_date = self.price_date or "pending"
        if len(rows) < 1000:
            self._em_down_until = time.time() + 600
            try:
                rows = await sina.fetch_spot(self.client)
                industries = await sina.fetch_industries(self.client)
                source = "sina"
                if time.time() - self._industry_map_at > 600 or not self._industry_map:
                    self._industry_map = await sina.fetch_industry_map(self.client, industries)
                    self._industry_map_at = time.time()
                for row in rows:
                    row["industry"] = self._industry_map.get(row["code"], "")
            except Exception as exc:
                self.last_error = f"新浪快照失败：{exc}"
        if len(rows) < 1000:
            ak_rows = await asyncio.to_thread(_ak_spot)
            if len(ak_rows) > len(rows):
                rows = ak_rows
                source = "akshare"
        if not rows:
            self.last_error = self.last_error or "全市场快照暂时拉不到"
            return
        self.quotes = {row["code"]: row for row in rows if row.get("code")}
        await self._overlay_amount_leaders()
        if industries:
            self.industries = industries
        if concepts:
            self.concepts = concepts
        self.quote_source = "通达信" if self.amount_leaders else source
        self.spot_at = time.time()
        self.last_error = ""
        self._rebuild_factor_queue()

    async def _overlay_amount_leaders(self) -> None:
        leaders = await asyncio.to_thread(tdx.fetch_amount_leaders, 1200)
        self.amount_leaders = []
        if len(leaders) < 400:
            return
        for row in leaders:
            current = dict(self.quotes.get(row["code"]) or {})
            if not row.get("name"):
                row["name"] = current.get("name") or ""
            if not row.get("circ_mv"):
                row["circ_mv"] = current.get("circ_mv") or 0
                row["total_mv"] = current.get("total_mv") or 0
            if not row.get("industry"):
                row["industry"] = current.get("industry") or ""
            row["concepts"] = current.get("concepts") or []
            current.update(row)
            self.quotes[row["code"]] = current
            self.amount_leaders.append(row["code"])

    def ranked_quotes(self) -> list[dict]:
        if self.amount_leaders:
            rows = [self.quotes[code] for code in self.amount_leaders if code in self.quotes]
            if rows:
                return rows
        return sorted(self.quotes.values(), key=lambda r: r.get("amount") or 0, reverse=True)

    def _rebuild_factor_queue(self) -> None:
        ranked = self.ranked_quotes()
        wanted = []
        for row in ranked:
            if len(wanted) >= POOL_FACTOR_UNIVERSE:
                break
            if universe_ok(row["code"], row["name"], row.get("amount") or 0, row.get("circ_mv") or 0, row.get("suspended")):
                wanted.append(row["code"])
        fresh = self.db.factor_codes_as_of(self.price_date) if self.price_date else set()
        self._factor_queue = [code for code in wanted if code not in fresh]

    async def fill_factor_batch(self) -> int:
        if not self._factor_queue:
            return 0
        now = time.time()
        batch = []
        while self._factor_queue and len(batch) < FACTOR_BATCH:
            code = self._factor_queue.pop(0)
            if self._fail_until.get(code, 0) > now:
                continue
            batch.append(code)
        if not batch:
            return 0
        await self.open()
        await asyncio.gather(*(self._store_bars(code) for code in batch))
        return len(batch)

    async def ensure_bars(self, code: str) -> dict | None:
        factor = self.db.get_factor(code)
        if factor and self.price_date and factor.get("as_of") == self.price_date:
            return factor
        await self.open()
        await self._store_bars(code)
        return self.db.get_factor(code)

    async def _store_bars(self, code: str) -> None:
        try:
            bars = await asyncio.to_thread(tdx.fetch_bars, code, market_of(code), False)
            if len(bars) < 30 and time.time() >= self._em_down_until:
                bars = await eastmoney.fetch_kline(self.client, code, qfq=True)
            if len(bars) < 30:
                self._em_down_until = time.time() + 600
                bars = await sina.fetch_kline(self.client, code, index=False)
            if len(bars) < 30:
                bars = await asyncio.to_thread(_ak_stock_bars, code)
            if len(bars) < 30:
                self._fail_until[code] = time.time() + 600
                return
            self.db.replace_bars(code, bars)
            ref = compute_reference(_bars_before(bars, self.price_date))
            if ref:
                self.db.save_factor(code, self.price_date or ref["ref_date"], ref)
        except Exception:
            self._fail_until[code] = time.time() + 600

    def live_quote(self, code: str) -> dict | None:
        return self.quotes.get(code)

    async def refresh_one(self, code: str) -> dict | None:
        """缓存不够新时补一只的现价。"""
        fresh = await asyncio.to_thread(tdx.fetch_quote, code, market_of(code))
        base = dict(self.quotes.get(code) or {"code": code, "name": "", "concepts": [], "industry": ""})
        if not fresh:
            return self.quotes.get(code)
        base.update(fresh)
        base["suspended"] = (base.get("price") or 0) <= 0 or (base.get("amount") or 0) <= 0
        base["volume_ratio"] = base.get("volume_ratio")
        self.quotes[code] = base
        return base

    def breadth(self) -> tuple[int, int, int, int]:
        up = down = zt = dt = 0
        for row in self.quotes.values():
            if row.get("suspended"):
                continue
            pct = row.get("pct") or 0
            if pct > 0:
                up += 1
            elif pct < 0:
                down += 1
            if is_limit(row["code"], row.get("name") or "", pct, 1):
                zt += 1
            elif is_limit(row["code"], row.get("name") or "", pct, -1):
                dt += 1
        return up, down, zt, dt

    def industry_of(self, name: str) -> dict | None:
        if not name or not self.industries:
            return None
        for i, row in enumerate(self.industries, start=1):
            if row["name"] == name:
                return {**row, "rank": i, "total": len(self.industries)}
        return None

    def matched_concepts(self, concepts: list[str]) -> list[str]:
        top = {row["name"] for row in self.concepts[:TOP_CONCEPTS]}
        return [name for name in concepts if name in top]

    def resolve(self, query: str) -> dict:
        text = query.strip()
        if not text:
            return {"error": "empty"}
        if text.isdigit():
            code = text.zfill(6) if len(text) <= 6 else text
            if len(code) != 6:
                return {"error": "missing"}
            return {"code": code, "known": code in self.quotes}
        exact = [row for row in self.quotes.values() if row["name"] == text]
        if len(exact) == 1:
            return {"code": exact[0]["code"], "known": True}
        if len(exact) > 1:
            return {"error": "ambiguous", "candidates": [_brief(r) for r in exact[:8]]}
        fuzzy = [row for row in self.quotes.values() if text in row["name"]]
        if len(fuzzy) == 1:
            return {"code": fuzzy[0]["code"], "known": True}
        if len(fuzzy) > 1:
            fuzzy.sort(key=lambda r: len(r["name"]))
            return {"error": "ambiguous", "candidates": [_brief(r) for r in fuzzy[:8]]}
        return {"error": "missing"}


def _brief(row: dict) -> dict:
    return {"code": row["code"], "name": row["name"]}


def _merge_index_quotes(tdx_quotes: dict | None, em_quotes: dict | None) -> tuple[dict, str]:
    """现价优先用通达信，成交额若和东财差一个数量级以上则改用东财。"""
    if tdx_quotes and em_quotes:
        merged = {}
        for code, row in tdx_quotes.items():
            item = dict(row)
            other = em_quotes.get(code) or {}
            other_price = other.get("price") or 0
            if other_price and item.get("price") and item["price"] / other_price > 50:
                item["price"] = item["price"] / 100
                item["high"] = (item.get("high") or 0) / 100
                item["low"] = (item.get("low") or 0) / 100
                item["open"] = (item.get("open") or 0) / 100
                item["prev_close"] = (item.get("prev_close") or 0) / 100
                item["pct"] = _pct(item["price"], item["prev_close"])
            other_amount = other.get("amount") or 0
            own_amount = item.get("amount") or 0
            if other_amount and (own_amount <= 0 or own_amount / other_amount > 5 or other_amount / max(own_amount, 1) > 5):
                item["amount"] = other_amount
            merged[code] = item
        for code, other in em_quotes.items():
            merged.setdefault(code, other)
        return merged, "通达信"
    if tdx_quotes:
        return tdx_quotes, "通达信"
    if em_quotes:
        return em_quotes, "eastmoney"
    return {}, ""


def _pct(price: float, prev: float) -> float:
    if not prev:
        return 0.0
    return (price / prev - 1) * 100


def _ak_spot() -> list[dict]:
    try:
        import akshare as ak
    except Exception:
        return []
    try:
        frame = ak.stock_zh_a_spot_em()
    except Exception:
        return []
    rows = []
    for _, item in frame.iterrows():
        code = str(item.get("代码") or "").zfill(6)
        price = fnum(item.get("最新价"))
        amount = fnum(item.get("成交额"), 0) or 0
        rows.append(
            {
                "code": code,
                "name": str(item.get("名称") or ""),
                "price": price,
                "pct": fnum(item.get("涨跌幅"), 0) or 0,
                "high": fnum(item.get("最高")),
                "low": fnum(item.get("最低")),
                "open": fnum(item.get("今开")),
                "prev_close": fnum(item.get("昨收")),
                "volume": fnum(item.get("成交量"), 0) or 0,
                "amount": amount,
                "volume_ratio": fnum(item.get("量比")),
                "total_mv": fnum(item.get("总市值"), 0) or 0,
                "circ_mv": fnum(item.get("流通市值"), 0) or 0,
                "industry": "",
                "concepts": [],
                "suspended": price is None or price <= 0 or amount <= 0,
            }
        )
    return rows


def _ak_index_quotes() -> dict[str, dict]:
    try:
        import akshare as ak

        frame = ak.stock_zh_index_spot_em()
    except Exception:
        return {}
    wanted = {"000001", "399001", "399006"}
    out = {}
    for _, item in frame.iterrows():
        code = str(item.get("代码") or "")
        if code not in wanted:
            continue
        out[code] = {
            "code": code,
            "name": str(item.get("名称") or code),
            "price": fnum(item.get("最新价"), 0) or 0,
            "pct": fnum(item.get("涨跌幅"), 0) or 0,
            "amount": fnum(item.get("成交额"), 0) or 0,
            "high": fnum(item.get("最高"), 0) or 0,
            "low": fnum(item.get("最低"), 0) or 0,
            "open": fnum(item.get("今开"), 0) or 0,
            "prev_close": fnum(item.get("昨收"), 0) or 0,
        }
    return out


def _ak_index_bars(code: str):
    try:
        import akshare as ak

        symbol = {"000001": "sh000001", "399001": "sz399001", "399006": "sz399006"}.get(code, code)
        frame = ak.stock_zh_index_daily(symbol=symbol)
    except Exception:
        return []
    return _frame_bars(frame)


def _ak_stock_bars(code: str):
    try:
        import akshare as ak

        frame = ak.stock_zh_a_hist(symbol=code, period="daily", adjust="qfq")
    except Exception:
        return []
    return _frame_bars(frame, date_col="日期", open_col="开盘", close_col="收盘", high_col="最高", low_col="最低", vol_col="成交量", amt_col="成交额")


def _frame_bars(frame, date_col="date", open_col="open", close_col="close", high_col="high", low_col="low", vol_col="volume", amt_col="amount"):
    from app.engine.levels import Bar

    if frame is None or len(frame) == 0:
        return []
    cols = set(frame.columns)
    # akshare index daily uses date/open/close...
    if "date" not in cols and "日期" in cols:
        date_col, open_col, close_col, high_col, low_col = "日期", "开盘", "收盘", "最高", "最低"
        vol_col, amt_col = "成交量", "成交额"
    bars = []
    tail = frame.tail(120)
    for _, item in tail.iterrows():
        raw_date = str(item.get(date_col) or "")[:10]
        bars.append(
            Bar(
                trade_date=raw_date,
                open=fnum(item.get(open_col), 0) or 0,
                high=fnum(item.get(high_col), 0) or 0,
                low=fnum(item.get(low_col), 0) or 0,
                close=fnum(item.get(close_col), 0) or 0,
                volume=fnum(item.get(vol_col), 0) or 0,
                amount=fnum(item.get(amt_col), 0) or 0,
            )
        )
    bars.sort(key=lambda b: b.trade_date)
    return bars
