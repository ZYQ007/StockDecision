from app.config import (
    SECTOR_BACK_RANK,
    SECTOR_BEAT_DAYS,
    SECTOR_EXTENDED_PCT,
    SECTOR_FADE_RANK,
    SECTOR_MIN_DAYS,
    SECTOR_PULSE_RANK,
    SECTOR_PULSE_SHARE,
    SECTOR_RUN_PCT,
    SECTOR_RUN_RANK,
    SECTOR_RUN_TODAY_PCT,
    SECTOR_RANK_MIN,
    SECTOR_STAGE_MILD,
    SECTOR_STAGE_RUN,
    SECTOR_TOP_DAYS,
    SECTOR_TOP_RANK,
    SECTOR_WEAK_PCT,
    SECTOR_WEAK_RANK,
)
from app.engine.types import SectorDay, SectorInputs, SectorView


def classify_sector(inp: SectorInputs) -> SectorView:
    if not inp.ready or not inp.name or inp.total <= 0:
        return SectorView(
            ready=False,
            name=inp.name,
            rank=inp.rank,
            total=inp.total,
            pct=inp.pct,
            weak=False,
            extended=False,
            unknown=True,
            reason="没有对上可用的行业或概念，这一关不能给可买",
            matched_concepts=list(inp.matched_concepts),
        )
    days = [d for d in inp.days if d.total > 0]
    rank_weak = inp.total >= SECTOR_RANK_MIN and (inp.rank / inp.total) > SECTOR_WEAK_RANK
    weak = inp.pct <= SECTOR_WEAK_PCT or rank_weak
    extended = inp.pct >= SECTOR_EXTENDED_PCT
    persist, fade, block_buy = _persist(days)
    if weak and not fade:
        persist = "偏弱"
    theme = _theme_quality(persist, weak, fade, days)
    stage = _stage(days, persist)
    reason = _reason(inp, days, weak, extended, persist)
    if theme == "伪题材":
        reason = f"{reason}定性偏伪题材（一日游或无连续修复）。"
    elif theme == "真主线":
        reason = f"{reason}定性偏真主线（连续且反复强于大盘）。"
    if stage and stage != "未知":
        reason = f"{reason}阶段粗判：{stage}。"
    return SectorView(
        ready=True,
        name=inp.name,
        rank=inp.rank,
        total=inp.total,
        pct=inp.pct,
        weak=weak,
        extended=extended,
        unknown=False,
        reason=reason,
        matched_concepts=list(inp.matched_concepts),
        persist=persist,
        fade=fade,
        block_buy=block_buy and not weak,
        amount_pct=inp.amount_pct,
        theme_quality=theme,
        stage=stage,
    )


def _theme_quality(persist: str, weak: bool, fade: bool, days: list[SectorDay]) -> str:
    if persist == "一日游" or (persist in {"不足", "样本不足"} and not _continuous(days)):
        return "伪题材"
    if fade or weak or persist in {"走弱", "偏弱", "背离"}:
        return "伪题材" if persist == "一日游" else "中性"
    if persist == "连续":
        return "真主线"
    if persist == "涨满":
        return "中性"
    return "未知"


def _stage(days: list[SectorDay], persist: str) -> str:
    if len(days) < SECTOR_MIN_DAYS:
        return "未知"
    window = days[-5:]
    run = sum(day.pct for day in window)
    if persist == "走弱" or _fading(days):
        return "分歧"
    if persist == "涨满" or run >= SECTOR_STAGE_RUN:
        return "尾声" if persist == "涨满" else "主升"
    if persist == "连续" and run >= SECTOR_STAGE_MILD:
        return "发酵"
    if persist == "一日游":
        return "萌芽"
    if run < SECTOR_STAGE_MILD:
        return "萌芽"
    return "未知"


def _persist(days: list[SectorDay]) -> tuple[str, bool, bool]:
    if len(days) < SECTOR_MIN_DAYS:
        return "样本不足", False, True
    if _fading(days):
        return "走弱", True, False
    if _pulse(days):
        return "一日游", False, True
    if _exhausted(days):
        return "涨满", False, True
    if _flow_divergence(days):
        return "背离", False, True
    if _continuous(days):
        return "连续", False, False
    return "不足", False, True


def _continuous(days: list[SectorDay]) -> bool:
    window = days[-5:]
    beats = sum(1 for day in window if day.pct > day.index_pct)
    last3 = days[-3:]
    top = sum(1 for day in last3 if _rank_ok(day) and day.rank / day.total <= SECTOR_TOP_RANK)
    return beats >= SECTOR_BEAT_DAYS or top >= SECTOR_TOP_DAYS


def _pulse(days: list[SectorDay]) -> bool:
    if len(days) < 4:
        return False
    today = days[-1]
    prior = days[-4:-1]
    if not _rank_ok(today) or any(not _rank_ok(day) for day in prior):
        return False
    if today.rank / today.total > SECTOR_PULSE_RANK:
        return False
    if any(day.rank / day.total <= SECTOR_BACK_RANK for day in prior):
        return False
    window = days[-5:]
    total = sum(day.pct for day in window)
    if total <= 0:
        return today.pct > 0
    return today.pct / total >= SECTOR_PULSE_SHARE


def _fading(days: list[SectorDay]) -> bool:
    if len(days) < 4:
        return False
    last4 = days[-4:]
    if any(not _rank_ok(day) for day in last4):
        return False
    pcts = [day.rank / day.total for day in last4]
    worsening = all(pcts[i] > pcts[i - 1] for i in range(1, 4))
    return worsening and pcts[-1] > SECTOR_FADE_RANK


def _exhausted(days: list[SectorDay]) -> bool:
    window = days[-5:]
    if sum(day.pct for day in window) < SECTOR_RUN_PCT:
        return False
    today = days[-1]
    if not _rank_ok(today):
        return False
    front = today.rank / today.total <= SECTOR_RUN_RANK
    return front and today.pct >= SECTOR_RUN_TODAY_PCT


def _flow_divergence(days: list[SectorDay]) -> bool:
    last3 = days[-3:]
    if len(last3) < 3 or any(day.inflow is None for day in last3):
        return False
    return sum(day.inflow for day in last3) < 0 and sum(day.pct for day in last3) > 0


def _rank_ok(day: SectorDay) -> bool:
    return day.total >= SECTOR_RANK_MIN


def _reason(inp: SectorInputs, days: list[SectorDay], weak: bool, extended: bool, persist: str) -> str:
    rel = inp.pct - inp.index_pct
    rank = f"排名 {inp.rank}/{inp.total}，" if inp.total >= SECTOR_RANK_MIN else ""
    corr = f"近20日和个股相关 {inp.corr:.2f}。" if inp.corr is not None else ""
    place = ""
    if inp.amount_pct is not None:
        place = f"按成交额排在该板块前 {max(1, round(inp.amount_pct * 100))}%。"
    if inp.kind:
        head = (
            f"主板块是{inp.source or '同花顺'}{inp.kind}「{inp.name}」。{corr}{place}"
            f"今日 {inp.pct:+.2f}%，{rank}相对上证 {rel:+.2f} 个百分点。"
        )
    else:
        head = f"行业「{inp.name}」今日 {inp.pct:+.2f}%，排名 {inp.rank}/{inp.total}，相对上证 {rel:+.2f} 个百分点。"
    detail = {
        "偏弱": "板块当天偏弱，个股服从板块。",
        "走弱": "排名连续走差，今天已经到后一半。",
        "一日游": "今天冲到前排，但前几个交易日都在后一半，这根占了近几日大部分涨幅，像一日游。",
        "涨满": "近几日累计涨幅已经比较满，今天还在前排，等板块歇一天再看。",
        "背离": "近 3 日价格还在涨，板块主力净流入为负，价和资金不一致。" + _flow_amount(days),
        "样本不足": "能对上的交易日还不到 3 天，板块持续性样本不足。",
        "不足": "近几个交易日没有连续跑赢，今天强也撑不住一段波段。",
    }.get(persist, "")
    if persist == "连续":
        detail = _window_phrase(days) + "，今天不是单独脉冲。"
        if extended:
            detail += "板块今天涨得比较满，突破容易买在分歧，回踩还可以看。"
    concept = ""
    if inp.matched_concepts and persist == "连续" and not weak:
        concept = "关联概念今日靠前：" + "、".join(inp.matched_concepts[:3]) + "。"
    flow = "" if persist == "背离" else _flow_phrase(days)
    return f"{head}{detail}{concept}{flow}".strip()


def _window_phrase(days: list[SectorDay]) -> str:
    window = days[-5:]
    beats = sum(1 for day in window if day.pct > day.index_pct)
    last3 = days[-3:]
    ranked = [day for day in last3 if _rank_ok(day)]
    if not ranked:
        return f"近 {len(window)} 日 {beats} 天跑赢上证"
    top = sum(1 for day in ranked if day.rank / day.total <= SECTOR_TOP_RANK)
    return f"近 {len(window)} 日 {beats} 天跑赢上证，近 3 日 {top} 天排在前 40%"


def _flow_phrase(days: list[SectorDay]) -> str:
    last3 = days[-3:]
    if len(last3) < 3 or any(day.inflow is None for day in last3):
        return "资金流没有，用近 5 日相对强弱。"
    return f"近 3 日板块主力净流入 {_money(sum(day.inflow for day in last3))}，没有和涨幅背离。"


def _flow_amount(days: list[SectorDay]) -> str:
    last3 = days[-3:]
    if len(last3) < 3 or any(day.inflow is None for day in last3):
        return ""
    return f"合计 {_money(sum(day.inflow for day in last3))}。"


def _money(value: float) -> str:
    if abs(value) >= 1e8:
        return f"{value / 1e8:+.2f} 亿"
    return f"{value / 1e4:+.0f} 万"
