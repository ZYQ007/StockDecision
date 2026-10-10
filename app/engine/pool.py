from app.config import (
    BREAKOUT_LIMIT,
    CANDIDATE_LIMIT,
    HOLD_LIMIT,
    LEADER_LIMIT,
    MAX_CIRC_MV,
    MIN_AMOUNT,
    MIN_CIRC_MV,
    PULLBACK_LIMIT,
    WATCH_LIMIT,
    WAVE2_LIMIT,
    WAVE2_STARTED_LIMIT,
    WEAK_CANDIDATE_LIMIT,
)
from app.engine.decide import decide
from app.engine.pick import PickInputs, pick
from app.engine.types import Decision, EntryInputs, MarketInputs, SectorInputs


def is_st(name: str) -> bool:
    text = name.upper().replace(" ", "")
    return "ST" in text


def is_bj(code: str) -> bool:
    return code.startswith(("4", "8", "92"))


def universe_ok(code: str, name: str, amount: float, circ_mv: float, suspended: bool) -> bool:
    if suspended or is_st(name) or is_bj(code):
        return False
    if amount < MIN_AMOUNT:
        return False
    if circ_mv and (circ_mv < MIN_CIRC_MV or circ_mv > MAX_CIRC_MV):
        return False
    return True


def bucket_of(decision: Decision, market_block_new: bool, sector_weak: bool, trend_ok: bool) -> str | None:
    if decision.verdict == "可买" and decision.setup == "pullback":
        return "pullback"
    if decision.verdict == "可买" and decision.setup == "breakout":
        return "breakout"
    if decision.verdict == "可买" and decision.setup == "hold":
        return "hold"
    if decision.verdict == "可买" and decision.setup == "leader":
        return "leader"
    if (
        decision.verdict == "观望"
        and decision.setup in {"chase", "breakout", "none", "hold", "leader"}
        and trend_ok
        and not sector_weak
        and not market_block_new
    ):
        return "watch"
    return None


def screen_one(
    market: MarketInputs,
    sector: SectorInputs,
    entry: EntryInputs,
    *,
    code: str,
    name: str,
    industry: str,
    amount: float,
    circ_mv: float,
    volume_ratio: float | None,
) -> dict | None:
    if not market.ready:
        return None
    if not sector.ready:
        return None
    if not universe_ok(code, name, amount, circ_mv, entry.suspended):
        return None
    decision = decide(market, sector, entry)
    from app.engine.market import classify_market
    from app.engine.sector import classify_sector
    from app.engine.stock import classify_entry

    m = classify_market(market)
    s = classify_sector(sector)
    e = classify_entry(entry)
    bucket = bucket_of(decision, m.block_new, s.weak, e.trend_ok)
    if not bucket:
        return None
    return {
        "code": code,
        "name": name,
        "industry": industry,
        "price": entry.price,
        "pct": entry.day_pct,
        "bucket": bucket,
        "setup": decision.setup,
        "verdict": decision.verdict,
        "reason": decision.reason_line,
        "watch_text": decision.watch_text,
        "sector_rank": s.rank,
        "dist_ma10": e.dist_ma10,
        "volume_ratio": volume_ratio,
        "scores": decision.scores,
        "amount": amount,
    }


def candidate_of(
    market: MarketInputs,
    sector: SectorInputs,
    entry: EntryInputs,
    picked: PickInputs,
    *,
    code: str,
    name: str,
    industry: str,
    amount: float,
    circ_mv: float,
    volume_ratio: float | None,
) -> dict | None:
    if not market.ready or not sector.ready:
        return None
    if not universe_ok(code, name, amount, circ_mv, entry.suspended):
        return None
    view = pick(picked)
    if not view.selected and not view.weak:
        return None
    decision = decide(market, sector, entry)
    reason = view.reason
    if decision.verdict != "可买" and decision.watch_text and view.selected:
        reason = f"{reason}今天还不是买点。{decision.watch_text}"
    return {
        "code": code,
        "name": name,
        "industry": industry,
        "price": entry.price,
        "pct": entry.day_pct,
        "bucket": "weak_candidate" if view.weak else "candidate",
        "setup": decision.setup,
        "verdict": decision.verdict,
        "reason": reason,
        "watch_text": decision.watch_text,
        "sector_rank": sector.rank,
        "dist_ma10": view.dist_ma10,
        "volume_ratio": volume_ratio,
        "scores": decision.scores,
        "amount": amount,
        "excess_5d": view.excess_5d,
        "flow_intensity": view.flow_intensity,
        "sector_rank_pct": view.sector_rank_pct,
    }


def cap_groups(rows: list[dict]) -> dict:
    pullback = [r for r in rows if r["bucket"] == "pullback"]
    breakout = [r for r in rows if r["bucket"] == "breakout"]
    hold = [r for r in rows if r["bucket"] == "hold"]
    leader = [r for r in rows if r["bucket"] == "leader"]
    watch = [r for r in rows if r["bucket"] == "watch"]
    candidate = [r for r in rows if r["bucket"] == "candidate"]
    weak = [r for r in rows if r["bucket"] == "weak_candidate"]
    wave2 = [r for r in rows if r["bucket"] == "wave2"]
    wave2_started = [r for r in rows if r["bucket"] == "wave2_started"]
    pullback.sort(key=lambda r: (abs(r["dist_ma10"]), r["sector_rank"] or 999))
    breakout.sort(key=lambda r: (-(r["volume_ratio"] or 0), r["sector_rank"] or 999))
    hold.sort(key=lambda r: (abs(r["dist_ma10"]), r["sector_rank"] or 999))
    leader.sort(key=lambda r: (r["sector_rank"] or 999, abs(r["dist_ma10"])))
    watch.sort(key=lambda r: abs(r["dist_ma10"]))
    candidate.sort(key=lambda r: (-r.get("excess_5d", 0), -r.get("flow_intensity", 0), abs(r["dist_ma10"]), r.get("sector_rank_pct", 1)))
    weak.sort(key=lambda r: (-r.get("excess_5d", 0), abs(r["dist_ma10"])))
    wave2.sort(key=lambda r: (r.get("pullback_days") or 99, -(r.get("limit_days") or 0)))
    wave2_started.sort(key=lambda r: (-(r.get("volume_ratio") or 0), r.get("pullback_days") or 99))
    return {
        "pullback": pullback[:PULLBACK_LIMIT],
        "breakout": breakout[:BREAKOUT_LIMIT],
        "hold": hold[:HOLD_LIMIT],
        "leader": leader[:LEADER_LIMIT],
        "watch": watch[:WATCH_LIMIT],
        "candidate": candidate[:CANDIDATE_LIMIT],
        "weak_candidate": weak[:WEAK_CANDIDATE_LIMIT],
        "wave2": wave2[:WAVE2_LIMIT],
        "wave2_started": wave2_started[:WAVE2_STARTED_LIMIT],
    }
