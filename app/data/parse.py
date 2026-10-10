def fnum(value, default=None):
    if value is None or value == "-" or value == "":
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def vwap_from_turnover(price: float, volume: float, amount: float) -> float | None:
    """成交量可能是股或手，用现价挑一个说得通的均价。"""
    if not price or not volume or not amount:
        return None
    per_share = amount / volume
    per_hand = amount / (volume * 100)
    if abs(per_share - price) / price < 0.2:
        return per_share
    if abs(per_hand - price) / price < 0.2:
        return per_hand
    return None


def is_limit(code: str, name: str, pct: float | None, direction: int) -> bool:
    if pct is None:
        return False
    upper = name.upper()
    if "ST" in upper:
        limit = 4.8
    elif code.startswith(("300", "301", "688", "689")):
        limit = 19.5
    elif code.startswith(("4", "8", "92")):
        limit = 29.5
    else:
        limit = 9.8
    if direction > 0:
        return pct >= limit
    return pct <= -limit


def market_of(code: str) -> int:
    if code.startswith(("6", "9", "5")):
        return 1
    return 0


def index_market(code: str) -> int:
    # 上证指数 000001 和个股 000001 不是同一个市场。
    if code.startswith(("000", "880")):
        return 1
    return 0


def secid(code: str, index: bool = False) -> str:
    market = index_market(code) if index else market_of(code)
    return f"{market}.{code}"
