from app.config import (
    BREAKOUT_PCT_MAX,
    BREAKOUT_PCT_MIN,
    BREAKOUT_VOL_RATIO,
    CHASE_10D_PCT,
    CHASE_10D_TODAY_PCT,
    CHASE_ABOVE_MA5,
    CHASE_DAY_PCT,
    PULLBACK_MA10_BAND,
    PULLBACK_PCT_MAX,
    PULLBACK_PCT_MIN,
    PULLBACK_VOL_RATIO_MAX,
    RANGE_POS_HIGH,
    STALL_DAY_PCT_MAX,
    STALL_RANGE_POS,
    STALL_VOL_RATIO,
    VWAP_CHASE,
)
from app.engine.types import EntryInputs, EntryView


def _empty(reason: str) -> EntryView:
    return EntryView(
        ready=False,
        trend_ok=False,
        setup="none",
        terminal=False,
        vetoes=[],
        reason=reason,
        watch_price=None,
        watch_text="",
        dist_ma5=0.0,
        dist_ma10=0.0,
        range_pos=0.0,
    )


def classify_entry(inp: EntryInputs) -> EntryView:
    if inp.suspended or inp.price <= 0:
        view = _empty("停牌或没有成交，不能买")
        view.vetoes = ["停牌或无成交"]
        view.setup = "broken"
        return view
    if not inp.ready or inp.ma20 <= 0 or inp.ma10 <= 0 or inp.ma5 <= 0:
        return _empty("日K不足，算不出均线，先不判断")

    dist_ma5 = inp.price / inp.ma5 - 1
    dist_ma10 = inp.price / inp.ma10 - 1
    span = inp.high_20 - inp.low_20
    range_pos = (inp.price - inp.low_20) / span if span > 0 else 0.5
    trend_ok = inp.price >= inp.ma20 and inp.ma20_up
    watch = inp.ma10
    watch_text = f"回到 MA10 约 {watch:.2f} 元再看"

    vetoes: list[str] = []
    if dist_ma5 > CHASE_ABOVE_MA5:
        vetoes.append(f"现价高于5日线 {dist_ma5:.1%}，偏离过大")
    if inp.day_pct > CHASE_DAY_PCT:
        vetoes.append(f"当日涨幅 {inp.day_pct:.2f}%，已经不适合追")
    if inp.ret_10d_pct > CHASE_10D_PCT and inp.day_pct > CHASE_10D_TODAY_PCT:
        vetoes.append(f"近10日已涨 {inp.ret_10d_pct:.1f}%，当天还在大涨")
    if inp.vwap and inp.price > inp.vwap * (1 + VWAP_CHASE):
        vetoes.append("现价远离分时均价，属于盘中追价")
    if (
        range_pos >= STALL_RANGE_POS
        and inp.day_pct <= STALL_DAY_PCT_MAX
        and inp.volume_ratio is not None
        and inp.volume_ratio >= STALL_VOL_RATIO
    ):
        vetoes.append(f"高位放量滞涨（区间 {range_pos:.0%}，量比 {inp.volume_ratio:.2f}）")

    vol_ok = inp.volume_ratio is not None and inp.volume_ratio >= BREAKOUT_VOL_RATIO
    price_veto = any("5日线" in v or "当日涨幅" in v or "近10日" in v or "分时" in v for v in vetoes)
    breakout_shape = (
        trend_ok
        and inp.price > inp.high_20
        and BREAKOUT_PCT_MIN <= inp.day_pct <= BREAKOUT_PCT_MAX
        and vol_ok
        and not price_veto
    )
    if range_pos > RANGE_POS_HIGH and not breakout_shape:
        vetoes.append(f"处在近20日区间 {range_pos:.0%} 的高位，又不是刚放量突破")

    shrunk = inp.volume_ratio is None or inp.volume_ratio <= PULLBACK_VOL_RATIO_MAX
    pullback = (
        trend_ok
        and abs(dist_ma10) <= PULLBACK_MA10_BAND
        and PULLBACK_PCT_MIN <= inp.day_pct <= PULLBACK_PCT_MAX
        and shrunk
        and not vetoes
    )

    terminal = (inp.day_pct > CHASE_DAY_PCT and dist_ma5 > CHASE_ABOVE_MA5) or len(vetoes) >= 2

    if not trend_ok:
        setup = "broken"
        if inp.price < inp.ma20:
            reason = f"现价 {inp.price:.2f} 在20日线 {inp.ma20:.2f} 下方，这段趋势已经坏了"
        else:
            reason = f"20日线没有向上，趋势还没走出来。现价 {inp.price:.2f}，MA20 {inp.ma20:.2f}"
        watch_text = f"重新站上并站稳 MA20 约 {inp.ma20:.2f} 元再看"
        watch = inp.ma20
    elif pullback:
        setup = "pullback"
        vol_txt = "量能没有放大" if shrunk else "量能数据缺失，先按价格位置看"
        reason = (
            f"趋势还在（MA20 向上且价格在其上），现价贴近 MA10（偏离 {dist_ma10:+.1%}），"
            f"当日 {inp.day_pct:+.2f}%，{vol_txt}。这是回踩，不是追高。"
        )
        watch_text = f"回踩参考 MA10 约 {inp.ma10:.2f} 元"
    elif breakout_shape:
        setup = "breakout"
        ratio_txt = f"量比 {inp.volume_ratio:.2f}" if inp.volume_ratio is not None else "量比缺失"
        reason = (
            f"刚越过近20日高点 {inp.high_20:.2f}，当日涨幅 {inp.day_pct:.2f}% 还在可接受范围，{ratio_txt}。"
            "这是刚突破，不是加速末端。"
        )
        watch_text = f"若冲高回落，等回到 MA10 约 {inp.ma10:.2f} 元再看"
    elif vetoes:
        setup = "chase"
        reason = "个股趋势或许还在，但当前位置是追高。" + "；".join(vetoes)
    else:
        setup = "none"
        reason = (
            f"没有形成回踩或合格突破。现价 {inp.price:.2f}，MA10 {inp.ma10:.2f}，MA20 {inp.ma20:.2f}，"
            f"当日 {inp.day_pct:+.2f}%。"
        )

    return EntryView(
        ready=True,
        trend_ok=trend_ok,
        setup=setup,
        terminal=terminal and trend_ok,
        vetoes=vetoes,
        reason=reason,
        watch_price=watch,
        watch_text=watch_text,
        dist_ma5=dist_ma5,
        dist_ma10=dist_ma10,
        range_pos=range_pos,
    )
