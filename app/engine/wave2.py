"""龙头二波：连板后回调中等待，尚未二次启动。"""

from dataclasses import dataclass

from app.config import (
    WAVE2_MAX_DRAWDOWN,
    WAVE2_MIN_LIMIT_DAYS,
    WAVE2_PULLBACK_MAX,
    WAVE2_PULLBACK_MIN,
    WAVE2_RECLAIM,
    WAVE2_START_PCT_MAX,
    WAVE2_START_PCT_MIN,
    WAVE2_START_VOL,
)
from app.data.parse import is_limit
from app.engine.levels import Bar


@dataclass
class Wave2View:
    hit: bool
    reason: str
    limit_days: int = 0
    pullback_days: int = 0
    high: float = 0.0
    drawdown: float = 0.0
    mode: str = "waiting"  # waiting | started


def scan_wave2(
    bars: list[Bar],
    *,
    code: str,
    name: str,
    price: float,
    day_pct: float,
    volume_ratio: float | None,
) -> Wave2View:
    if len(bars) < WAVE2_MIN_LIMIT_DAYS + WAVE2_PULLBACK_MIN + 1 or price <= 0:
        return Wave2View(False, "日K不够，看不出连板回调。")
    series = list(bars)
    end = len(series) - 1
    # 找最近一段连板：以评估日前的最后一根涨停为终点
    last_limit = None
    for i in range(end, WAVE2_MIN_LIMIT_DAYS - 2, -1):
        if _bar_limit_up(series, i, code, name):
            last_limit = i
            break
    if last_limit is None:
        return Wave2View(False, "近期没有涨停板。")
    run = 1
    j = last_limit - 1
    while j >= 0 and _bar_limit_up(series, j, code, name):
        run += 1
        j -= 1
    if run < WAVE2_MIN_LIMIT_DAYS:
        return Wave2View(False, f"连板只有 {run} 天，不够 {WAVE2_MIN_LIMIT_DAYS} 天。")
    pullback_days = end - last_limit
    if pullback_days < WAVE2_PULLBACK_MIN or pullback_days > WAVE2_PULLBACK_MAX:
        return Wave2View(False, f"回调已 {pullback_days} 天，不在 {WAVE2_PULLBACK_MIN}～{WAVE2_PULLBACK_MAX} 日窗口。", run, pullback_days)
    high = max(series[k].high for k in range(last_limit - run + 1, last_limit + 1))
    if high <= 0:
        return Wave2View(False, "连板高点无效。", run, pullback_days)
    low = min(series[k].low for k in range(last_limit + 1, end + 1))
    drawdown = 1 - low / high
    if drawdown > WAVE2_MAX_DRAWDOWN:
        return Wave2View(False, f"回调回撤 {drawdown:.0%}，像 A 杀。", run, pullback_days, high, drawdown)
    for k in range(last_limit + 1, end + 1):
        pct = _bar_pct(series, k)
        if is_limit(code, name, pct, -1):
            return Wave2View(False, "回调期出现跌停，剔除。", run, pullback_days, high, drawdown)
        crash = -9.0 if not code.startswith(("300", "301", "688", "689")) else -15.0
        if pct <= crash:
            return Wave2View(False, f"回调期单日跌 {pct:.1f}%，剔除。", run, pullback_days, high, drawdown)
    if price > high:
        return Wave2View(False, "已突破一波高点，不是回调等待。", run, pullback_days, high, drawdown)
    # 已二次启动：不进「等待」名单（另见 scan_wave2_started）
    if _second_wave_started(series, end, code, name, day_pct, volume_ratio, high, price):
        return Wave2View(
            False,
            "已出现二波启动迹象，本名单只收回调等待。",
            run,
            pullback_days,
            high,
            drawdown,
            mode="started",
        )
    return Wave2View(
        True,
        f"一波连板 {run} 天，回调第 {pullback_days} 天，相对高点回撤 {drawdown:.0%}，未 A 杀，仍在等二波。",
        run,
        pullback_days,
        high,
        drawdown,
        mode="waiting",
    )


def scan_wave2_started(
    bars: list[Bar],
    *,
    code: str,
    name: str,
    price: float,
    day_pct: float,
    volume_ratio: float | None,
) -> Wave2View:
    """二波已启动：连板后回调窗口内出现放量再起，单独名单，不等于可买。"""
    waiting = scan_wave2(
        bars,
        code=code,
        name=name,
        price=price,
        day_pct=day_pct,
        volume_ratio=volume_ratio,
    )
    if waiting.hit:
        return Wave2View(False, "仍在回调等待，不是已启动。", waiting.limit_days, waiting.pullback_days, waiting.high, waiting.drawdown, "waiting")
    if waiting.mode != "started" and "二波启动" not in waiting.reason:
        # 允许：已破高点或放量阳线但回撤仍在窗口内
        if len(bars) < WAVE2_MIN_LIMIT_DAYS + WAVE2_PULLBACK_MIN + 1 or price <= 0:
            return Wave2View(False, waiting.reason, mode="started")
        series = list(bars)
        end = len(series) - 1
        last_limit = None
        for i in range(end, WAVE2_MIN_LIMIT_DAYS - 2, -1):
            if _bar_limit_up(series, i, code, name):
                last_limit = i
                break
        if last_limit is None:
            return Wave2View(False, "近期没有涨停板。", mode="started")
        run = 1
        j = last_limit - 1
        while j >= 0 and _bar_limit_up(series, j, code, name):
            run += 1
            j -= 1
        if run < WAVE2_MIN_LIMIT_DAYS:
            return Wave2View(False, f"连板只有 {run} 天。", run, mode="started")
        pullback_days = end - last_limit
        if pullback_days < WAVE2_PULLBACK_MIN or pullback_days > WAVE2_PULLBACK_MAX + 2:
            return Wave2View(False, "不在二波启动观察窗。", run, pullback_days, mode="started")
        high = max(series[k].high for k in range(last_limit - run + 1, last_limit + 1))
        if not _second_wave_started(series, end, code, name, day_pct, volume_ratio, high, price) and price <= high:
            return Wave2View(False, waiting.reason or "未见二波启动。", run, pullback_days, high, mode="started")
        return Wave2View(
            True,
            f"一波连板 {run} 天后出现二波启动迹象（放量再起或逼近/越过前高），不等于三道门可买。",
            run,
            pullback_days,
            high,
            mode="started",
        )
    # waiting 已标 started
    series = list(bars)
    end = len(series) - 1
    last_limit = None
    for i in range(end, WAVE2_MIN_LIMIT_DAYS - 2, -1):
        if _bar_limit_up(series, i, code, name):
            last_limit = i
            break
    if last_limit is None:
        return Wave2View(False, waiting.reason, mode="started")
    run = waiting.limit_days or 1
    high = waiting.high or max(series[k].high for k in range(max(0, last_limit - run + 1), last_limit + 1))
    return Wave2View(
        True,
        f"一波连板后已现二波启动迹象，回调观察结束。不等于三道门可买。",
        waiting.limit_days,
        waiting.pullback_days,
        high,
        waiting.drawdown,
        mode="started",
    )


def _second_wave_started(
    series: list[Bar],
    end: int,
    code: str,
    name: str,
    day_pct: float,
    volume_ratio: float | None,
    high: float,
    price: float,
) -> bool:
    if is_limit(code, name, day_pct, 1):
        return True
    if price >= high * WAVE2_RECLAIM and WAVE2_START_PCT_MIN <= day_pct <= WAVE2_START_PCT_MAX:
        if volume_ratio is not None and volume_ratio >= WAVE2_START_VOL:
            return True
    bar = series[end]
    prev = series[end - 1].close if end > 0 else 0
    if prev and bar.close > prev and WAVE2_START_PCT_MIN <= day_pct <= WAVE2_START_PCT_MAX:
        if volume_ratio is not None and volume_ratio >= WAVE2_START_VOL:
            return True
    return False


def _bar_limit_up(series: list[Bar], i: int, code: str, name: str) -> bool:
    pct = _bar_pct(series, i)
    return is_limit(code, name, pct, 1)


def _bar_pct(series: list[Bar], i: int) -> float:
    if i <= 0:
        return 0.0
    prev = series[i - 1].close
    if prev <= 0:
        return 0.0
    return (series[i].close / prev - 1) * 100
