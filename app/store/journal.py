import json
from datetime import datetime
from zoneinfo import ZoneInfo

from app.config import STATS_MIN_SAMPLE
from app.engine.levels import Bar
from app.engine.types import Decision

SH = ZoneInfo("Asia/Shanghai")


def forward_returns(entry_price: float, future: list[Bar]) -> tuple[float | None, float | None, float | None, float | None]:
    if entry_price <= 0:
        return None, None, None, None

    def ret(n: int) -> float | None:
        if len(future) < n:
            return None
        return future[n - 1].close / entry_price - 1

    max_dd = None
    if len(future) >= 5:
        max_dd = min(b.low for b in future[:5]) / entry_price - 1
    return ret(1), ret(3), ret(5), max_dd


def log_buy(db, decision: Decision, *, code: str, name: str, price: float, trade_date: str, sector_name: str, sector_rank: int, source: str) -> None:
    if decision.verdict != "可买":
        return
    detail = {
        "reason": decision.reason_line,
        "gates": [{"name": g.name, "status": g.status, "text": g.text} for g in decision.gates],
        "vetoes": decision.vetoes,
        "scores": decision.scores,
        "sector_persist": decision.scores.get("sector_persist", ""),
        "watch_text": decision.watch_text,
        "env_tier": decision.env_tier,
        "theme_quality": decision.theme_quality,
        "logic_track": decision.logic_track,
    }
    db.insert_signal(
        {
            "ts": datetime.now(SH).isoformat(timespec="seconds"),
            "trade_date": trade_date,
            "code": code,
            "name": name,
            "price": price,
            "verdict": decision.verdict,
            "setup_type": decision.setup,
            "market_regime": decision.scores.get("regime", ""),
            "sector_name": sector_name,
            "sector_rank": sector_rank,
            "detail_json": json.dumps(detail, ensure_ascii=False),
            "source": source,
        }
    )


def backfill(db) -> int:
    updated = 0
    for row in db.open_signals():
        bars = [b for b in db.load_bars(row["code"]) if b.trade_date > row["trade_date"]]
        r1, r3, r5, dd = forward_returns(row["price"] or 0, bars)
        if r1 is None and r3 is None and r5 is None:
            continue
        db.update_returns(
            row["id"],
            r1 if r1 is not None else row["ret_1d"],
            r3 if r3 is not None else row["ret_3d"],
            r5 if r5 is not None else row["ret_5d"],
            dd if dd is not None else row["max_dd_5d"],
        )
        updated += 1
    return updated


def summarize(rows: list[dict]) -> dict:
    groups: dict[str, list[dict]] = {}
    by_env: dict[str, list[dict]] = {}
    for row in rows:
        groups.setdefault(row["setup_type"] or "unknown", []).append(row)
        tier = _env_tier_of(row)
        by_env.setdefault(tier, []).append(row)
    out = []
    labels = {"pullback": "回踩", "breakout": "突破", "hold": "续航", "leader": "主线"}
    for setup in ("pullback", "breakout", "hold", "leader"):
        items = groups.get(setup, [])
        out.append(_stat_block(setup, labels[setup], items))
    env_out = []
    for tier in ("强势", "震荡", "弱势", "未知"):
        items = by_env.get(tier, [])
        if not items and tier == "未知":
            continue
        env_out.append(_stat_block(tier, f"环境·{tier}", items))
    return {
        "setups": out,
        "by_env": env_out,
        "min_sample": STATS_MIN_SAMPLE,
        "total": len(rows),
        "promotion_note": "分层统计只作验收，不直接改写可买/观望/不买；样本不足不宣称变好。",
    }


def _env_tier_of(row: dict) -> str:
    try:
        detail = json.loads(row.get("detail_json") or "{}")
    except (TypeError, json.JSONDecodeError):
        detail = {}
    tier = detail.get("env_tier") or (detail.get("scores") or {}).get("env_tier") or ""
    if tier in {"强势", "震荡", "弱势"}:
        return tier
    return "未知"


def _stat_block(key: str, label: str, items: list[dict]) -> dict:
    filled = [r for r in items if r["ret_3d"] is not None]
    block = {
        "setup": key,
        "label": label,
        "signals": len(items),
        "verified": len(filled),
        "sample_enough": len(filled) >= STATS_MIN_SAMPLE,
    }
    if block["sample_enough"]:
        wins = sum(1 for r in filled if r["ret_3d"] > 0)
        block["win_rate_3d"] = wins / len(filled)
        block["avg_ret_3d"] = sum(r["ret_3d"] for r in filled) / len(filled)
        dds = [r["max_dd_5d"] for r in filled if r["max_dd_5d"] is not None]
        block["avg_max_dd_5d"] = sum(dds) / len(dds) if dds else None
    else:
        block["note"] = "样本不足"
    return block


def recent_signals(db, limit: int = 30) -> list[dict]:
    rows = []
    for row in db.recent_buy_signals(limit):
        rows.append(
            {
                "trade_date": row["trade_date"],
                "code": row["code"],
                "name": row["name"],
                "price": row["price"],
                "setup": row["setup_type"],
                "sector_name": row["sector_name"],
                "ret_1d": row["ret_1d"],
                "ret_3d": row["ret_3d"],
                "ret_5d": row["ret_5d"],
            }
        )
    return rows
