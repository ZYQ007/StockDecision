"""在核心板块里，用近一段日收益的相关性选出主板块。"""

from app.config import SECTOR_CORR_DAYS, SECTOR_CORR_MIN, SECTOR_CORR_OVERLAP, SECTOR_CORE_PCT
from app.data.ths import is_broad

_KIND_WEIGHT = {"行业": 2, "概念": 1, "指数": 0}


class Candidate:
    def __init__(self, code: str, name: str, kind: str, returns: dict[str, float], core: bool, amount_pct: float | None):
        self.code = code
        self.name = name
        self.kind = kind
        self.returns = returns
        self.core = core
        self.amount_pct = amount_pct
        self.corr: float | None = None


def is_core(kind: str, amount_pct: float | None, core_hint: bool) -> bool:
    if kind == "行业":
        return True
    if amount_pct is not None:
        return amount_pct <= SECTOR_CORE_PCT
    return core_hint


def choose_board(candidates: list[Candidate], stock_returns: dict[str, float]) -> Candidate | None:
    eligible = [item for item in candidates if item.kind in _KIND_WEIGHT and not is_broad(item.name) and item.core]
    if not eligible:
        industries = [item for item in candidates if item.kind == "行业" and not is_broad(item.name)]
        return industries[0] if industries else None
    for item in eligible:
        item.corr = aligned_correlation(stock_returns, item.returns)
    ranked = [item for item in eligible if item.corr is not None]
    if not ranked:
        industries = [item for item in eligible if item.kind == "行业"]
        return industries[0] if industries else eligible[0]
    ranked.sort(key=lambda item: (item.corr, _KIND_WEIGHT[item.kind]), reverse=True)
    best = ranked[0]
    if best.kind != "行业" and best.corr < SECTOR_CORR_MIN:
        industries = [item for item in ranked if item.kind == "行业"]
        if industries:
            return industries[0]
    return best


def aligned_correlation(stock_returns: dict[str, float], board_returns: dict[str, float], limit: int = SECTOR_CORR_DAYS) -> float | None:
    dates = sorted(set(stock_returns) & set(board_returns))[-limit:]
    if len(dates) < SECTOR_CORR_OVERLAP:
        return None
    xs = [stock_returns[day] for day in dates]
    ys = [board_returns[day] for day in dates]
    return _pearson(xs, ys)


def _pearson(xs: list[float], ys: list[float]) -> float | None:
    count = len(xs)
    if count < 2:
        return None
    mean_x = sum(xs) / count
    mean_y = sum(ys) / count
    diff_x = [value - mean_x for value in xs]
    diff_y = [value - mean_y for value in ys]
    numer = sum(left * right for left, right in zip(diff_x, diff_y))
    denom_x = sum(value * value for value in diff_x) ** 0.5
    denom_y = sum(value * value for value in diff_y) ** 0.5
    if denom_x == 0 or denom_y == 0:
        return None
    return numer / (denom_x * denom_y)
