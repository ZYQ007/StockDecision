from app.config import (
    AMOUNT_DUMP,
    AMOUNT_EXPAND,
    AMOUNT_SHRINK,
    CLIMAX_RANGE_POS,
    CLIMAX_SHADOW,
    CLIMAX_STAGNANT_PCT,
    CLIMAX_ZT,
    DUMP_PCT,
    ENV_POS_CAP_CHOP,
    ENV_POS_CAP_STRONG,
    ENV_POS_CAP_WEAK,
    ENV_STRONG_ZT,
    ENV_WEAK_DT,
    ENV_WEAK_ZT,
)
from app.engine.types import MarketInputs, MarketView


def amount_label(ratio: float) -> str:
    if ratio >= AMOUNT_EXPAND:
        return "放量"
    if ratio <= AMOUNT_SHRINK:
        return "缩量"
    return "常态"


def classify_market(inp: MarketInputs) -> MarketView:
    label = amount_label(inp.amount_ratio)
    base = MarketView(
        ready=inp.ready,
        regime="震荡",
        block_new=False,
        block_chase=False,
        reason="",
        amount_label=label,
        amount_ratio=inp.amount_ratio,
        sh_price=inp.sh_price,
        sh_pct=inp.sh_pct,
        cy_price=inp.cy_price,
        cy_pct=inp.cy_pct,
        sz_price=inp.sz_price,
        sz_pct=inp.sz_pct,
        total_amount=inp.total_amount,
        avg_amount_5=inp.avg_amount_5,
        up_count=inp.up_count,
        down_count=inp.down_count,
        zt_count=inp.zt_count,
        dt_count=inp.dt_count,
        sh_ma20=inp.sh_ma20,
        cy_ma20=inp.cy_ma20,
        env_tier="震荡",
        position_cap=ENV_POS_CAP_CHOP,
        northbound_note=inp.northbound_note or "",
    )
    if not inp.ready:
        base.regime = "等待"
        base.env_tier = "弱势"
        base.position_cap = ENV_POS_CAP_WEAK
        base.reason = "指数日K不足，大盘这一关先不放行"
        return base

    dump = (
        inp.amount_reliable
        and inp.amount_ratio >= AMOUNT_DUMP
        and (inp.sh_pct <= DUMP_PCT or inp.cy_pct <= DUMP_PCT)
        and inp.sh_near_low
    )
    both_below = (not inp.sh_above_ma20) and (not inp.cy_above_ma20)
    both_down = inp.sh_pct < 0 and inp.cy_pct < 0
    shrink = inp.amount_ratio < AMOUNT_SHRINK and inp.amount_reliable
    emotion_weak = inp.dt_count >= ENV_WEAK_DT and inp.zt_count <= ENV_WEAK_ZT
    defense = dump or (both_below and both_down and shrink) or (emotion_weak and shrink)

    stagnant = abs(inp.sh_pct) < CLIMAX_STAGNANT_PCT and inp.amount_ratio >= 1.30
    climax = (
        inp.amount_reliable
        and inp.sh_range_pos >= CLIMAX_RANGE_POS
        and inp.amount_ratio >= AMOUNT_EXPAND
        and (inp.zt_count >= CLIMAX_ZT or inp.sh_upper_shadow >= CLIMAX_SHADOW or stagnant)
    )

    ratio_txt = f"两市成交额约为近5日的 {inp.amount_ratio:.0%}（{label}）"
    if inp.amount_basis == "volume":
        ratio_txt = f"成交额历史暂时拿不到，两市成交量约为近5日的 {inp.amount_ratio:.0%}（{label}）"
    breadth = f"涨 {inp.up_count} 家，跌 {inp.down_count} 家，涨停 {inp.zt_count}，跌停 {inp.dt_count}"
    if not inp.amount_reliable:
        ratio_txt += "，开盘不久，量能先不作为否决"
    macro = ""
    if inp.northbound_note:
        macro = f" {inp.northbound_note}"
    elif inp.emotion_source:
        macro = f" 情绪源 {inp.emotion_source}"
    else:
        macro = " 宏观资金缺失，不假装有北向数据"

    if defense:
        base.regime = "防守"
        base.env_tier = "弱势"
        base.position_cap = ENV_POS_CAP_WEAK
        base.block_new = True
        why = "放量长阴" if dump else ("跌停扩散且缩量" if emotion_weak else "指数在20日线下且缩量下跌")
        base.reason = f"大盘{why}，新开仓默认放弃。{ratio_txt}。{breadth}。{macro}。"
        return base

    if climax:
        base.regime = "高潮"
        base.env_tier = "强势"
        base.position_cap = ENV_POS_CAP_STRONG
        base.block_chase = True
        base.reason = f"指数处于阶段高位且量能放大，情绪偏高潮，已经涨起来的不追。{ratio_txt}。{breadth}。{macro}。"
        return base

    both_above = inp.sh_above_ma20 and inp.cy_above_ma20
    breadth_ok = inp.up_count > inp.down_count
    amount_ok = inp.amount_ratio >= 0.90 or not inp.amount_reliable
    strong_emotion = inp.zt_count >= ENV_STRONG_ZT and inp.dt_count < ENV_WEAK_DT
    if both_above and inp.sh_ma20_up and amount_ok and breadth_ok and (strong_emotion or inp.amount_ratio >= 1.0):
        base.regime = "进攻"
        base.env_tier = "强势"
        base.position_cap = ENV_POS_CAP_STRONG
        base.reason = f"上证与创业板都在20日线上，量能和涨跌家数没有拖后腿。{ratio_txt}。{breadth}。{macro}。"
        return base

    base.regime = "震荡"
    base.env_tier = "震荡"
    base.position_cap = ENV_POS_CAP_CHOP
    base.reason = f"大盘没有形成单边进攻或明确防守，个股只能做位置合适的回踩或刚突破。{ratio_txt}。{breadth}。{macro}。"
    return base
