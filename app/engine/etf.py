"""ETF 性价比 / 观望 / 偏贵分档。不改写个股三道门。"""

from __future__ import annotations

from app.config_etf import (
    ETF_LOOKBACK,
    ETF_MA20_BIAS_MAX,
    ETF_MIN_BARS,
    ETF_REBOUND_5D_BLOCK,
    ETF_VALUE_DD_BROAD,
    ETF_VALUE_DD_THEME,
    ETF_WATCH_DD_BROAD,
    ETF_WATCH_DD_THEME,
)
from app.engine.levels import Bar


STATUS_VALUE = "性价比关注"
STATUS_WATCH = "观望"
STATUS_RICH = "偏贵"
STATUS_NA = "样本不足"


def drawdown_from_high(closes: list[float], lookback: int = ETF_LOOKBACK) -> float | None:
    if not closes:
        return None
    window = closes[-lookback:] if len(closes) >= lookback else closes
    if not window:
        return None
    peak = max(window)
    last = window[-1]
    if peak <= 0:
        return None
    return (peak - last) / peak


def ma_bias(price: float, ma: float | None) -> float | None:
    if not price or not ma:
        return None
    return (price - ma) / ma


def ret_nd(closes: list[float], n: int) -> float | None:
    if len(closes) < n + 1:
        return None
    base = closes[-(n + 1)]
    if base <= 0:
        return None
    return (closes[-1] - base) / base


def classify_etf(
    *,
    bucket: str,
    price: float,
    bars: list[Bar],
) -> dict:
    """纯函数：根据日 K 给出 status / 回撤 / 均线偏离 / 理由。"""
    if not price or len(bars) < ETF_MIN_BARS:
        return {
            "status": STATUS_NA,
            "drawdown_60": None,
            "ma20_bias": None,
            "ret_5d": None,
            "reason": "日K未齐，暂不评级",
        }

    closes = [b.close for b in bars if b.close and b.close > 0]
    if len(closes) < ETF_MIN_BARS:
        return {
            "status": STATUS_NA,
            "drawdown_60": None,
            "ma20_bias": None,
            "ret_5d": None,
            "reason": "有效收盘样本不足",
        }

    # 评估用「含当日」的收盘序列；现价优先
    if closes:
        closes = list(closes)
        closes[-1] = price

    dd = drawdown_from_high(closes, ETF_LOOKBACK)
    ma20 = sum(closes[-20:]) / 20 if len(closes) >= 20 else None
    bias = ma_bias(price, ma20)
    r5 = ret_nd(closes, 5)

    is_broad = bucket == "broad"
    value_dd = ETF_VALUE_DD_BROAD if is_broad else ETF_VALUE_DD_THEME
    watch_dd = ETF_WATCH_DD_BROAD if is_broad else ETF_WATCH_DD_THEME

    if dd is None:
        return {
            "status": STATUS_NA,
            "drawdown_60": None,
            "ma20_bias": bias,
            "ret_5d": r5,
            "reason": "无法计算回撤",
        }

    near_ma = bias is not None and abs(bias) <= ETF_MA20_BIAS_MAX
    above_ma = bias is not None and bias >= 0
    rebound_hot = r5 is not None and r5 >= ETF_REBOUND_5D_BLOCK

    if dd >= value_dd and not rebound_hot and (near_ma or (above_ma and dd >= value_dd)):
        tip = "贴近均线" if near_ma else "回撤仍深且站上均线"
        return {
            "status": STATUS_VALUE,
            "drawdown_60": dd,
            "ma20_bias": bias,
            "ret_5d": r5,
            "reason": f"近{ETF_LOOKBACK}日回撤{dd * 100:.1f}%·{tip}",
        }

    if rebound_hot and dd >= value_dd:
        return {
            "status": STATUS_WATCH,
            "drawdown_60": dd,
            "ma20_bias": bias,
            "ret_5d": r5,
            "reason": f"回撤{dd * 100:.1f}%但近5日反弹偏快，防假性价比",
        }

    if dd >= watch_dd:
        return {
            "status": STATUS_WATCH,
            "drawdown_60": dd,
            "ma20_bias": bias,
            "ret_5d": r5,
            "reason": f"回撤{dd * 100:.1f}%·未进性价比区或均线未收敛",
        }

    return {
        "status": STATUS_RICH,
        "drawdown_60": dd,
        "ma20_bias": bias,
        "ret_5d": r5,
        "reason": f"回撤仅{dd * 100:.1f}%·接近阶段高，偏贵",
    }


def build_etf_rows(
    meta_map: dict[str, dict],
    quotes: dict[str, dict],
    bars_by_code: dict[str, list[Bar]],
    *,
    env_tier: str = "",
    regime: str = "",
    active_limit: int = 15,
) -> dict:
    """组装 broad / value / active / all。"""
    all_rows: list[dict] = []
    for code, meta in meta_map.items():
        q = quotes.get(code) or {}
        price = float(q.get("price") or 0)
        bars = bars_by_code.get(code) or []
        graded = classify_etf(bucket=str(meta.get("bucket") or "theme"), price=price, bars=bars)
        row = {
            "code": code,
            "name": q.get("name") or meta.get("name") or code,
            "track": meta.get("track") or "",
            "bucket": meta.get("bucket") or "theme",
            "rescue_priority": int(meta.get("rescue_priority") or 0),
            "price": price or None,
            "pct": q.get("pct"),
            "amount": q.get("amount") or 0,
            "volume_ratio": q.get("volume_ratio"),
            "status": graded["status"],
            "drawdown_60": graded["drawdown_60"],
            "ma20_bias": graded["ma20_bias"],
            "ret_5d": graded["ret_5d"],
            "reason": graded["reason"],
        }
        all_rows.append(row)

    all_rows.sort(key=lambda r: (-int(r.get("rescue_priority") or 0), -(r.get("amount") or 0)))

    broad = [r for r in all_rows if r.get("bucket") == "broad"]
    broad.sort(key=lambda r: (-int(r.get("rescue_priority") or 0), -(r.get("drawdown_60") or 0)))

    value = [r for r in all_rows if r.get("status") == STATUS_VALUE]
    value.sort(key=lambda r: (-(r.get("drawdown_60") or 0), -int(r.get("rescue_priority") or 0)))

    active = sorted(all_rows, key=lambda r: -(r.get("amount") or 0))[:active_limit]

    weak_env = env_tier == "弱势" or regime == "防守"
    note = (
        "环境弱·宽基性价比更值得盯（经验标签，非官方救市监测）"
        if weak_env
        else "宽基「救市敏感」为历史经验排序，不构成救市信号"
    )

    return {
        "broad": broad,
        "value": value,
        "active": active,
        "all": all_rows,
        "env_note": note,
        "weak_env": weak_env,
        "whitelist_size": len(meta_map),
        "quoted": len(quotes),
    }
