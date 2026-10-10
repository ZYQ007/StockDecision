"""用成分股日 K 回推板块涨幅，官方快照优先。"""

from app.config import SECTOR_LOOKBACK, SECTOR_MIN_MEMBERS
from app.engine.types import SectorDay


def close_returns(series: list[tuple[str, float]]) -> dict[str, float]:
    out: dict[str, float] = {}
    prev = None
    for trade_date, close in series:
        if prev and prev > 0 and close:
            out[trade_date] = (close / prev - 1) * 100
        if close:
            prev = close
    return out


def proxy_board_pcts(
    members: dict[str, list[str]],
    series: dict[str, list[tuple[str, float]]],
    min_members: int = SECTOR_MIN_MEMBERS,
) -> dict[str, dict[str, float]]:
    """行业 -> 交易日 -> 成分股当日涨幅中位数（百分数）。"""
    returns = {code: close_returns(rows) for code, rows in series.items()}
    out: dict[str, dict[str, float]] = {}
    for name, codes in members.items():
        bucket: dict[str, list[float]] = {}
        for code in codes:
            for trade_date, pct in returns.get(code, {}).items():
                bucket.setdefault(trade_date, []).append(pct)
        daily = {}
        for trade_date, values in bucket.items():
            if len(values) >= min_members:
                daily[trade_date] = _median(values)
        if daily:
            out[name] = daily
    return out


def build_histories(
    names: list[str],
    proxy: dict[str, dict[str, float]],
    official: dict[str, dict[str, dict]],
    index_pct: dict[str, float],
    lookback: int = SECTOR_LOOKBACK,
) -> dict[str, list[SectorDay]]:
    dates = sorted(index_pct)[-lookback:]
    chosen: dict[str, dict[str, float]] = {}
    for trade_date in dates:
        for name in names:
            row = official.get(name, {}).get(trade_date) or {}
            if row.get("pct") is not None:
                chosen.setdefault(trade_date, {})[name] = row["pct"]
            elif trade_date in proxy.get(name, {}):
                chosen.setdefault(trade_date, {})[name] = proxy[name][trade_date]
    ranks: dict[str, dict[str, tuple[int, int]]] = {}
    for trade_date, board in chosen.items():
        ordered = sorted(board, key=lambda item: board[item], reverse=True)
        total = len(ordered)
        ranks[trade_date] = {item: (i, total) for i, item in enumerate(ordered, start=1)}
    histories: dict[str, list[SectorDay]] = {}
    for name in names:
        days: list[SectorDay] = []
        for trade_date in dates:
            if name not in chosen.get(trade_date, {}):
                continue
            row = official.get(name, {}).get(trade_date) or {}
            rank, total = ranks[trade_date][name]
            if row.get("rank") and row.get("total"):
                rank, total = int(row["rank"]), int(row["total"])
            days.append(
                SectorDay(
                    trade_date=trade_date,
                    pct=chosen[trade_date][name],
                    index_pct=index_pct.get(trade_date, 0.0),
                    rank=rank,
                    total=total,
                    inflow=row.get("inflow"),
                )
            )
        histories[name] = days
    return histories


def _median(values: list[float]) -> float:
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2
