"""单只量价细读：只解释，不改可买结论。"""

from app.engine.levels import Bar
from app.engine.types import EntryInputs


def stock_read(
    entry: EntryInputs,
    bars: list[Bar],
    *,
    volume_ratio: float | None,
    flow_3d: float | None,
) -> str:
    if not entry.ready or entry.price <= 0:
        return "日K或现价不够，细读先空着。"
    parts = []
    parts.append(
        f"均线：现价 {entry.price:.2f}，相对 MA5 {(entry.price / entry.ma5 - 1) if entry.ma5 else 0:+.1%}、"
        f"MA10 {(entry.price / entry.ma10 - 1) if entry.ma10 else 0:+.1%}、"
        f"MA20 {(entry.price / entry.ma20 - 1) if entry.ma20 else 0:+.1%}；"
        f"MA20 {'向上' if entry.ma20_up else '未抬头'}。"
    )
    span = entry.high_20 - entry.low_20
    range_pos = (entry.price - entry.low_20) / span if span > 0 else 0.5
    avg5 = 0.0
    if len(bars) >= 5:
        avg5 = sum(b.amount for b in bars[-5:]) / 5
    amount_txt = "—"
    if avg5 > 0 and entry.amount:
        amount_txt = f"{entry.amount / avg5:.2f} 倍近5日额"
    vol_txt = f"量比 {volume_ratio:.2f}" if volume_ratio is not None else "量比缺失"
    style = "缩量" if volume_ratio is not None and volume_ratio <= 1.0 else ("放量" if volume_ratio and volume_ratio >= 1.5 else "量能中性")
    parts.append(f"量能：{vol_txt}，成交额约 {amount_txt}，观感{style}。")
    streak = _streak(bars, entry.price, entry.day_pct)
    parts.append(
        f"走势：近10日 {entry.ret_10d_pct:+.1f}%（细读用近10日），近20日区间位置 {range_pos:.0%}，"
        f"{streak}{'，刚过前高' if entry.price > entry.high_20 else ''}。"
    )
    if flow_3d is None:
        parts.append("资金：近 3 日个股主力净流入没有。")
    else:
        parts.append(f"资金：近 3 日个股主力净流入 {_money(flow_3d)}。")
    return "".join(parts)


def _streak(bars: list[Bar], price: float, day_pct: float) -> str:
    if len(bars) < 2:
        return f"当日 {day_pct:+.2f}%"
    ups = 0
    downs = 0
    # include today via day_pct on last bar close path
    closes = [b.close for b in bars]
    if closes:
        closes = closes[:-1] + [price]
    for i in range(len(closes) - 1, 0, -1):
        if closes[i] > closes[i - 1]:
            if downs:
                break
            ups += 1
        elif closes[i] < closes[i - 1]:
            if ups:
                break
            downs += 1
        else:
            break
    if ups >= 2:
        return f"连涨 {ups} 日，当日 {day_pct:+.2f}%"
    if downs >= 2:
        return f"连跌 {downs} 日，当日 {day_pct:+.2f}%"
    return f"当日 {day_pct:+.2f}%"


def _money(value: float) -> str:
    if abs(value) >= 1e8:
        return f"{value / 1e8:+.2f} 亿"
    return f"{value / 1e4:+.0f} 万"
