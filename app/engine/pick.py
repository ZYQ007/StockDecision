"""2–5 日候选。只说明值不值得盯，不改可买。"""

from dataclasses import dataclass

from app.config import (
    PICK_ABOVE_MA5,
    PICK_BLOCK_PERSIST,
    PICK_PULSE_SHARE,
    PICK_RANGE_POS,
    PICK_RET_10D,
    PICK_TURNOVER_MAX,
    PICK_VOL_RATIO_MAX,
)


@dataclass
class PickInputs:
    price: float
    day_pct: float
    ma5: float
    ma10: float
    ma20: float
    ma20_up: bool
    high_20: float
    low_20: float
    ret_10d_pct: float
    ret_5d_pct: float
    index_ret_5d_pct: float
    limit_up: bool
    sector_ready: bool
    sector_persist: str
    flow_3d: list[float] | None
    price_up_3d: bool
    flow_5d: float | None
    amount_5d: float
    sector_rank: int
    sector_total: int
    volume_ratio: float | None = None
    turnover: float | None = None


@dataclass
class PickView:
    selected: bool
    weak: bool
    reason: str
    excess_5d: float
    flow_intensity: float
    dist_ma10: float
    sector_rank_pct: float


def pick(inp: PickInputs) -> PickView:
    dist_ma5 = inp.price / inp.ma5 - 1 if inp.ma5 else 0.0
    dist_ma10 = inp.price / inp.ma10 - 1 if inp.ma10 else 0.0
    span = inp.high_20 - inp.low_20
    range_pos = (inp.price - inp.low_20) / span if span > 0 else 0.5
    excess = inp.ret_5d_pct - inp.index_ret_5d_pct
    intensity = (inp.flow_5d / inp.amount_5d) if inp.flow_5d is not None and inp.amount_5d else 0.0
    rank_pct = inp.sector_rank / inp.sector_total if inp.sector_total else 1.0
    view = PickView(False, False, "", excess, intensity, dist_ma10, rank_pct)

    if inp.price <= 0 or inp.ma20 <= 0 or not inp.ma20_up or inp.price < inp.ma20:
        view.reason = "趋势不在：价格要在向上的 20 日线之上。"
        return view
    if inp.limit_up:
        view.reason = "已经涨停，买不进去。"
        return view
    if dist_ma5 > PICK_ABOVE_MA5:
        view.reason = f"现价高于 5 日线 {dist_ma5:.1%}，位置偏高。"
        return view
    if inp.ret_10d_pct >= PICK_RET_10D:
        view.reason = f"近 10 日已涨 {inp.ret_10d_pct:.1f}%，不再当候选。"
        return view
    if range_pos >= PICK_RANGE_POS:
        view.reason = f"处在近 20 日区间 {range_pos:.0%} 的高位。"
        return view
    if not inp.sector_ready or inp.sector_persist in PICK_BLOCK_PERSIST:
        name = inp.sector_persist or "没对齐"
        view.reason = f"主板块是{name}，不进候选。"
        return view
    if inp.ret_5d_pct <= inp.index_ret_5d_pct:
        view.reason = "近 5 日没有强于上证。"
        return view
    if inp.ret_5d_pct > 0 and inp.day_pct / inp.ret_5d_pct >= PICK_PULSE_SHARE:
        view.reason = "近 5 日涨幅有六成以上来自今天，像一天的脉冲。"
        return view
    if inp.volume_ratio is not None and inp.volume_ratio > PICK_VOL_RATIO_MAX:
        view.reason = f"量比 {inp.volume_ratio:.2f} 过高，短线情绪过热，不进候选。"
        return view
    if inp.turnover is not None and inp.turnover > PICK_TURNOVER_MAX:
        view.reason = f"换手率 {inp.turnover:.1f}% 过高，不进候选。"
        return view
    if not inp.flow_3d or len(inp.flow_3d) < 3:
        view.weak = True
        view.reason = (
            f"趋势、位置、板块和相对强弱都过了，个股资金流暂缺。"
            f"近 5 日强于上证 {excess:+.1f} 个百分点。"
        )
        return view
    flow_sum = sum(inp.flow_3d)
    if flow_sum < 0:
        view.reason = (
            "近 3 日股价还在涨，个股主力净流入为负，不进候选。"
            if inp.price_up_3d
            else "近 3 日个股主力净流入为负，不进候选。"
        )
        return view
    view.selected = True
    view.reason = (
        f"趋势在 20 日线上，位置还没跑飞，主板块{inp.sector_persist}，"
        f"近 3 日主力净流入 {_money(flow_sum)}，近 5 日强于上证 {excess:+.1f} 个百分点。"
    )
    return view


def _money(value: float) -> str:
    if abs(value) >= 1e8:
        return f"{value / 1e8:+.2f} 亿"
    return f"{value / 1e4:+.0f} 万"
