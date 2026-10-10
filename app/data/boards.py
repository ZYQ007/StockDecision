"""缓存同花顺板块归属，并选出和个股最相关的主板块。"""

import asyncio

import httpx

from app.config import SECTOR_LOOKBACK

BOARD_VERSION = 2
from app.data import ths, tdx
from app.engine.relate import Candidate, choose_board, is_core
from app.engine.types import SectorDay, SectorInputs
from app.store.db import Database


class BoardBook:
    def __init__(self, db: Database):
        self.db = db
        self.closes = db.load_board_closes()
        self.catalog: dict[str, dict] = {}
        self._catalog_at = 0.0
        self._queue: list[str] = []
        self._queued: set[str] = set()
        self._failed: set[str] = set()
        self._catalog_queue: list[str] = []
        self._as_of = ""

    def aligned_count(self, codes: list[str], trade_date: str) -> int:
        if not trade_date:
            return 0
        return sum(1 for code in codes if _fresh(self.db.get_stock_boards(code), trade_date))

    def remember(self, codes: list[str], trade_date: str) -> None:
        for code in codes:
            if code in self._queued or code in self._failed:
                continue
            cached = self.db.get_stock_boards(code)
            if _fresh(cached, trade_date):
                continue
            self._queue.append(code)
            self._queued.add(code)

    async def ensure(self, client: httpx.AsyncClient, code: str, trade_date: str) -> bool:
        self._as_of = trade_date
        cached = self.db.get_stock_boards(code)
        if _fresh(cached, trade_date):
            await self._ensure_closes(client, cached["data"], trade_date)
            return True
        await self._ensure_catalog(client)
        data = await ths.fetch_stock_boards(client, code, self.catalog)
        if not data:
            self._failed.add(code)
            return False
        await self._fill_amount(client, code, data)
        await self._ensure_closes(
            client,
            {"industry": data.get("industry"), "boards": [row for row in data.get("boards") or [] if row.get("core_hint")]},
            trade_date,
        )
        data["ready"] = True
        data["version"] = BOARD_VERSION
        self.db.save_stock_boards(code, trade_date, data)
        self._failed.discard(code)
        return True

    async def fill_some(self, client: httpx.AsyncClient, codes: list[str], trade_date: str, limit: int = 6) -> int:
        if not trade_date:
            return 0
        self._as_of = trade_date
        self.remember(codes, trade_date)
        done = 0
        while self._queue and done < limit:
            code = self._queue.pop(0)
            self._queued.discard(code)
            if await self.ensure(client, code, trade_date):
                done += 1
        await self._fill_catalog_klines(client, 6, trade_date)
        return done

    def build(self, code: str, stock_returns: dict[str, float], index_pct: dict[str, float]) -> SectorInputs | None:
        cached = self.db.get_stock_boards(code)
        if not cached or cached["data"].get("version") != BOARD_VERSION or not cached["data"].get("ready"):
            return None
        data = cached["data"]
        candidates = []
        for board in _flat(data):
            returns = _pcts(self.closes.get(board["code"]) or {})
            if len(returns) < 3:
                continue
            amount_pct = board.get("amount_pct")
            name = board["name"]
            level3 = board.get("level3") or ""
            if board["kind"] == "行业" and level3 and level3 not in name:
                name = f"{name}（{level3}）"
            candidates.append(
                Candidate(
                    code=board["code"],
                    name=name,
                    kind=board["kind"],
                    returns=returns,
                    core=is_core(board["kind"], amount_pct, bool(board.get("core_hint"))),
                    amount_pct=amount_pct,
                )
            )
        choice = choose_board(candidates, stock_returns)
        if choice is None:
            return None
        days = self._days(choice, index_pct)
        if len(days) < 3:
            return None
        last = days[-1]
        return SectorInputs(
            ready=True,
            name=choice.name,
            rank=last.rank,
            total=last.total,
            pct=last.pct,
            index_pct=last.index_pct,
            kind=choice.kind,
            source=data.get("source") or "同花顺",
            corr=choice.corr,
            amount_pct=choice.amount_pct,
            days=days,
        )

    async def _ensure_catalog(self, client: httpx.AsyncClient) -> None:
        import time

        if self.catalog and time.time() - self._catalog_at < 6 * 3600:
            return
        rows = await ths.fetch_catalog(client)
        if not rows:
            return
        self.catalog = {row["code"]: row for row in rows}
        self._catalog_at = time.time()
        as_of = getattr(self, "_as_of", "")
        self._catalog_queue = [
            row["code"] for row in rows if row["kind"] == "行业" and _needs_closes(self.closes.get(row["code"]), as_of)
        ]
        self._catalog_queue += [
            row["code"] for row in rows if row["kind"] != "行业" and _needs_closes(self.closes.get(row["code"]), as_of)
        ]

    async def _fill_catalog_klines(self, client: httpx.AsyncClient, limit: int, trade_date: str = "") -> None:
        if not self._catalog_queue:
            await self._ensure_catalog(client)
        batch = []
        while self._catalog_queue and len(batch) < limit:
            code = self._catalog_queue.pop(0)
            if _needs_closes(self.closes.get(code), trade_date or getattr(self, "_as_of", "")):
                batch.append({"code": code, "kind": (self.catalog.get(code) or {}).get("kind") or "概念"})
        if batch:
            await self._ensure_closes(client, {"industry": None, "boards": batch}, trade_date or getattr(self, "_as_of", ""))

    async def _fill_amount(self, client: httpx.AsyncClient, stock: str, data: dict) -> None:
        industry = data.get("industry")
        if not industry or not str(industry.get("code") or "").isdigit():
            return
        members = await ths.fetch_members(client, industry["code"], "行业")
        industry["amount_pct"] = ths.amount_rank_pct(members, stock)

    async def _ensure_closes(self, client: httpx.AsyncClient, data: dict, trade_date: str = "") -> None:
        missing = [
            board
            for board in _flat(data)
            if str(board.get("code") or "").isdigit() and _needs_closes(self.closes.get(board["code"]), trade_date)
        ]

        async def one(board: dict) -> None:
            rows = await ths.fetch_closes(client, board["code"])
            if not rows:
                # 空结果不写死缓存，下次还能重试。
                self.closes.pop(board["code"], None)
                return
            self.closes[board["code"]] = {day: close for day, close in rows}
            self.db.save_board_closes(board["code"], rows)

        await asyncio.gather(*(one(board) for board in missing))

    def _days(self, choice: Candidate, index_pct: dict[str, float]) -> list[SectorDay]:
        dates = sorted(choice.returns)[-SECTOR_LOOKBACK:]
        inflows = tdx.board_inflows(choice.code) or {}
        days = []
        for trade_date in dates:
            pct = choice.returns[trade_date]
            rank, total = self._rank(choice.kind, trade_date, pct, choice.code)
            days.append(SectorDay(trade_date, pct, index_pct.get(trade_date, 0.0), rank, max(total, 1), inflows.get(trade_date)))
        return days

    def _rank(self, kind: str, trade_date: str, pct: float, code: str) -> tuple[int, int]:
        peers = []
        for board_code, meta in self.catalog.items():
            if meta.get("kind") != kind:
                continue
            series = _pcts(self.closes.get(board_code) or {})
            if trade_date in series:
                peers.append((board_code, series[trade_date]))
        if not any(board_code == code for board_code, _pct in peers):
            peers.append((code, pct))
        peers.sort(key=lambda item: item[1], reverse=True)
        rank = next(index for index, (board_code, _pct) in enumerate(peers, start=1) if board_code == code)
        return rank, len(peers)


def _fresh(cached: dict | None, trade_date: str) -> bool:
    return bool(cached and cached["trade_date"] == trade_date and cached["data"].get("version") == BOARD_VERSION and cached["data"].get("ready"))


def _needs_closes(closes: dict | None, trade_date: str) -> bool:
    """板块日 K 没有、或最后一根早于当前交易日，都要重拉，否则资金流对不上日期。"""
    if not closes:
        return True
    if trade_date and max(closes) < trade_date:
        return True
    return False


def _flat(data: dict) -> list[dict]:
    rows = []
    seen = set()
    industry = data.get("industry")
    if industry:
        rows.append(industry)
    rows.extend(data.get("boards") or [])
    out = []
    for row in rows:
        if not row or row.get("code") in seen:
            continue
        seen.add(row["code"])
        out.append(row)
    return out


def _pcts(closes: dict[str, float]) -> dict[str, float]:
    out = {}
    prev = None
    for trade_date in sorted(closes):
        close = closes[trade_date]
        if prev and close:
            out[trade_date] = (close / prev - 1) * 100
        if close:
            prev = close
    return out
