from dataclasses import dataclass

from app.engine.types import EntryInputs


@dataclass
class Bar:
    trade_date: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    amount: float


def compute_reference(bars: list[Bar]) -> dict | None:
    """用「评估日之前」的日 K 计算均线和前高。bars 必须按日期升序，且不含正在评估的那一根。"""
    if len(bars) < 21:
        return None
    closes = [b.close for b in bars]

    def ma(n: int) -> float | None:
        if len(closes) < n:
            return None
        return sum(closes[-n:]) / n

    ma20 = ma(20)
    ma20_prev = sum(closes[-21:-1]) / 20 if len(closes) >= 21 else None
    window = bars[-20:]
    high_20 = max(b.high for b in window)
    low_20 = min(b.low for b in window)
    return {
        "ma5": ma(5),
        "ma10": ma(10),
        "ma20": ma20,
        "ma60": ma(60),
        "ma20_up": bool(ma20 and ma20_prev and ma20 > ma20_prev),
        "high_20": high_20,
        "low_20": low_20,
        "close_10_ago": closes[-10] if len(closes) >= 10 else None,
        "avg_amount_5": sum(b.amount for b in bars[-5:]) / 5,
        "avg_volume_5": sum(b.volume for b in bars[-5:]) / 5,
        "ref_close": closes[-1],
        "ref_date": bars[-1].trade_date,
    }


def split_bars(bars: list[Bar], eval_date: str | None) -> tuple[list[Bar], Bar | None]:
    if eval_date and bars and bars[-1].trade_date == eval_date:
        return bars[:-1], bars[-1]
    return bars, None


def index_range_pos(price: float, bars: list[Bar]) -> float:
    if len(bars) < 5 or price <= 0:
        return 0.5
    window = bars[-20:]
    high = max(b.high for b in window)
    low = min(b.low for b in window)
    if high <= low:
        return 0.5
    return (price - low) / (high - low)


def upper_shadow(open_: float, high: float, low: float, close: float) -> float:
    span = high - low
    if span <= 0:
        return 0.0
    return (high - max(open_, close)) / span


def near_low(price: float, high: float, low: float) -> bool:
    span = high - low
    if span <= 0:
        return False
    return (price - low) / span <= 0.35


def entry_from_quote(ref: dict | None, price: float, day_pct: float, volume_ratio: float | None, vwap: float | None, amount: float, suspended: bool) -> EntryInputs:
    if not ref or not ref.get("ma20") or price <= 0:
        return EntryInputs(ready=False, price=price, day_pct=day_pct, suspended=suspended, amount=amount)
    close_10 = ref.get("close_10_ago") or 0
    ret_10 = ((price / close_10) - 1) * 100 if close_10 else 0.0
    return EntryInputs(
        ready=True,
        price=price,
        day_pct=day_pct,
        ma5=ref["ma5"] or 0,
        ma10=ref["ma10"] or 0,
        ma20=ref["ma20"] or 0,
        ma20_up=bool(ref["ma20_up"]),
        high_20=ref["high_20"],
        low_20=ref["low_20"],
        ret_10d_pct=ret_10,
        volume_ratio=volume_ratio,
        vwap=vwap,
        amount=amount,
        suspended=suspended,
    )
