from app.config import (
    CHASE_ABOVE_MA5,
    HOLD_MA10_BAND,
    HOLD_PCT_MAX,
    HOLD_PCT_MIN,
    HOLD_VOL_RATIO_MAX,
    LEADER_AMOUNT_PCT,
    LEADER_PCT_MAX,
    LEADER_PCT_MIN,
    LEADER_RANK,
    LEADER_RET_5D_MAX,
    LEADER_RET_5D_MIN,
    PICK_PULSE_SHARE,
    SECTOR_RANK_MIN,
)
from app.engine.market import classify_market
from app.engine.sector import classify_sector
from app.engine.stock import classify_entry
from app.engine.types import Decision, EntryInputs, EntryView, Gate, MarketInputs, SectorInputs, SectorView

_MARKET_SCORE = {"进攻": 80, "震荡": 55, "高潮": 40, "防守": 15}
_ENTRY_SCORE = {
    "pullback": 85,
    "breakout": 72,
    "hold": 78,
    "leader": 80,
    "chase": 28,
    "none": 45,
    "broken": 10,
}


def decide(market: MarketInputs, sector: SectorInputs, entry: EntryInputs, warnings: list[str] | None = None) -> Decision:
    m = classify_market(market)
    s = classify_sector(sector)
    e = classify_entry(entry)
    notes = list(warnings or [])

    if m.block_new:
        verdict = "不买"
        line = "大盘处于防守，今天不做新开仓"
    elif not e.ready:
        verdict = "观望"
        line = "个股日K不够，先不下结论"
    elif e.setup == "broken" or not e.trend_ok:
        verdict = "不买"
        line = "个股趋势已破坏或尚未形成"
    elif s.unknown:
        verdict = "观望"
        line = "同花顺板块还没对齐，先不按板块放行"
    elif s.weak:
        verdict = "不买"
        line = "板块偏弱，个股再强也不做"
    elif s.fade:
        verdict = "不买"
        line = "板块近几日连续走弱，今天不做"
    elif e.terminal:
        verdict = "不买"
        line = "已经在加速末端，买进去容易被套"
    elif entry.limit_up:
        verdict = "不买"
        line = "已经涨停，买不进去"
    elif _pulse_day(entry):
        verdict = "不买"
        line = "近 5 日涨幅有六成以上来自今天，像一天的脉冲"
    elif _stock_flow_divergence(entry):
        verdict = "观望"
        line = "近 3 日股价还在涨，个股主力净流入为负"
    elif s.block_buy:
        verdict = "观望"
        line = _sector_line(s.persist)
    elif e.setup == "pullback":
        verdict = "可买"
        line = "三道门通过，买点是回踩"
    elif e.setup == "breakout":
        if m.block_chase or s.extended:
            verdict = "观望"
            line = "突破形态有了，但大盘高潮或板块已经涨满，不追"
        else:
            verdict = "可买"
            line = "三道门通过，买点是刚放量突破"
    elif _hold_ok(entry, e, s):
        e.setup = "hold"
        e.reason = _hold_reason(entry, e)
        verdict = "可买"
        line = "三道门通过，买点是续航"
    elif _leader_ok(entry, e, s):
        e.setup = "leader"
        e.reason = _leader_reason(entry, e, s)
        verdict = "可买"
        line = "三道门通过，买点是主线核心"
    else:
        verdict = "观望"
        line = "位置不合适，等回到观察价再看"

    if not m.ready and verdict == "可买":
        verdict = "观望"
        line = "大盘数据不完整，暂不给可买"
        notes.append("指数均线未就绪")

    watch_text = e.watch_text
    if s.persist == "涨满" and verdict == "观望":
        watch_text = "等板块歇一天、相对强弱还在再看"
    gates = [
        Gate("大盘", "不过" if m.block_new or not m.ready else ("否决" if m.block_chase and e.setup == "breakout" else "过"), m.reason),
        Gate("板块", _sector_status(s), s.reason),
        Gate("个股", _entry_status(e, verdict), e.reason),
    ]
    if m.block_chase and e.setup not in {"breakout"} and m.ready and not m.block_new:
        gates[0].status = "过"

    rank_score = 0
    if s.ready and s.total:
        rank_score = max(0, round(100 * (1 - s.rank / s.total)))
    scores = {
        "market": _MARKET_SCORE.get(m.regime, 50),
        "sector": rank_score,
        "entry": _ENTRY_SCORE.get(e.setup, 40),
        "regime": m.regime,
        "sector_persist": s.persist,
        "env_tier": m.env_tier,
        "theme_quality": s.theme_quality,
        "sector_stage": s.stage,
    }
    if s.theme_quality == "伪题材" and verdict == "可买" and e.setup in {"breakout", "leader"}:
        verdict = "观望"
        line = "板块偏伪题材，技术买点有了也不追，等主线确认"
        notes.append("伪题材挡突破/主线可买")
        gates[1].status = "不过"
    pos = _position_advice(m.env_tier, m.position_cap, verdict)
    return Decision(
        verdict=verdict,
        setup=e.setup,
        reason_line=line,
        gates=gates,
        vetoes=list(e.vetoes),
        watch_text=watch_text,
        watch_price=e.watch_price,
        scores=scores,
        warnings=notes,
        logic_track="短期主线交易",
        env_tier=m.env_tier,
        position_advice=pos,
        theme_quality=s.theme_quality or "",
        sector_stage=s.stage or "",
    )


def _position_advice(env_tier: str, cap: float, verdict: str) -> str:
    pct = int(round(cap * 10))
    base = f"环境{env_tier}，建议总仓位上限约 {pct} 成（须自设止损，本工具不下单）。"
    if verdict == "可买":
        return base + "当前结论是可买，仍只做短线主线交易轨道，勿与中长期价值混谈。"
    if verdict == "不买":
        return base + "今天不做新开仓或趋势未过。"
    return base + "先观望，等观察价或主线更干净再看。"


def _pulse_day(entry: EntryInputs) -> bool:
    return entry.ret_5d_pct > 0 and entry.day_pct / entry.ret_5d_pct >= PICK_PULSE_SHARE


def _stock_flow_divergence(entry: EntryInputs) -> bool:
    if entry.stock_flow_3d is None:
        return False
    return entry.stock_flow_3d < 0 and entry.ret_5d_pct > 0


def _hold_ok(entry: EntryInputs, e: EntryView, s: SectorView) -> bool:
    if not e.trend_ok or e.vetoes or entry.limit_up:
        return False
    if s.persist != "连续":
        return False
    if entry.stock_flow_3d is None or entry.stock_flow_3d <= 0:
        return False
    if entry.ret_5d_pct <= entry.index_ret_5d_pct:
        return False
    dist_ma10 = e.dist_ma10
    on_ma10 = entry.price >= entry.ma10 or abs(dist_ma10) <= HOLD_MA10_BAND
    if not on_ma10:
        return False
    if not (HOLD_PCT_MIN <= entry.day_pct <= HOLD_PCT_MAX):
        return False
    if e.dist_ma5 > CHASE_ABOVE_MA5:
        return False
    vol_ok = entry.volume_ratio is None or entry.volume_ratio <= HOLD_VOL_RATIO_MAX
    return vol_ok


def _leader_ok(entry: EntryInputs, e: EntryView, s: SectorView) -> bool:
    if not e.trend_ok or e.vetoes or entry.limit_up:
        return False
    if s.persist != "连续":
        return False
    if s.total < SECTOR_RANK_MIN or s.rank / s.total > LEADER_RANK:
        return False
    core = entry.board_core or (s.amount_pct is not None and s.amount_pct <= LEADER_AMOUNT_PCT)
    if not core:
        return False
    if entry.stock_flow_3d is None or entry.stock_flow_3d <= 0:
        return False
    if not (LEADER_RET_5D_MIN <= entry.ret_5d_pct <= LEADER_RET_5D_MAX):
        return False
    if not (LEADER_PCT_MIN <= entry.day_pct <= LEADER_PCT_MAX):
        return False
    return entry.price >= entry.ma20


def _hold_reason(entry: EntryInputs, e: EntryView) -> str:
    return (
        f"趋势还在，现价相对 MA10 {e.dist_ma10:+.1%}，当日 {entry.day_pct:+.2f}%，"
        f"近 5 日强于上证，近 3 日主力净流入为正。这是续航，不是追高。"
    )


def _leader_reason(entry: EntryInputs, e: EntryView, s: SectorView) -> str:
    place = f"板块前 {max(1, round((s.amount_pct or 0) * 100))}%" if s.amount_pct is not None else "板块核心"
    return (
        f"主板块连续且排名靠前，个股是{place}，近 5 日涨幅 {entry.ret_5d_pct:.1f}%，"
        f"当日 {entry.day_pct:+.2f}%，资金仍在流入。这是主线核心。"
    )


def _sector_status(sector) -> str:
    if sector.unknown:
        return "缺失"
    if sector.weak or sector.fade or sector.block_buy:
        return "不过"
    return "过"


def _sector_line(persist: str) -> str:
    return {
        "一日游": "板块只有今天强，近几日没有连续性",
        "涨满": "板块近几日已经涨满，等歇一天再看",
        "背离": "板块价格还在涨，但主力资金在流出",
        "样本不足": "板块持续性样本不足，先不下可买",
        "不足": "板块近几日没有形成连续强弱，先不买",
    }.get(persist, "板块这一段还撑不住，先不买")


def _entry_status(entry, verdict: str) -> str:
    if not entry.ready:
        return "缺失"
    if entry.setup in {"pullback", "breakout", "hold", "leader"} and not entry.vetoes and not entry.terminal:
        return "过"
    if entry.setup == "broken" or entry.terminal or entry.vetoes:
        return "否决"
    return "不过"
