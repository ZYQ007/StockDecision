"""持仓出场规则。只给出持有/减仓观望/建议卖出，不下单。"""

from dataclasses import dataclass

from app.config import (
    EXIT_GIVEBACK,
    EXIT_MA10_BREAK,
    EXIT_MAX_HOLD_DAYS,
    EXIT_PROFIT_MIN,
    EXIT_STOP_PCT,
    EXIT_VOL_BREAK,
)


@dataclass
class ExitInputs:
    entry_price: float
    price: float
    stop_pct: float
    hold_days: int
    ma10: float
    ma20: float
    ma20_up: bool
    volume_ratio: float | None
    high_20: float
    market_block_new: bool
    env_tier: str
    sector_persist: str
    sector_weak: bool = False


@dataclass
class ExitView:
    status: str  # 持有 | 减仓观望 | 建议卖出
    reason: str
    urgency: str  # low | mid | high
    tag: str
    pnl_pct: float


def classify_exit(inp: ExitInputs) -> ExitView:
    if inp.entry_price <= 0 or inp.price <= 0:
        return ExitView("持有", "成本或现价无效，暂不给出场建议。", "low", "持有", 0.0)
    pnl = (inp.price / inp.entry_price - 1) * 100
    stop = inp.stop_pct if inp.stop_pct and inp.stop_pct > 0 else EXIT_STOP_PCT

    if pnl <= -stop:
        return ExitView(
            "建议卖出",
            f"相对成本已跌 {pnl:.1f}%，触及止损线约 -{stop:.1f}%。提醒≠下单指令。",
            "high",
            "止损",
            pnl,
        )

    below_ma10 = inp.ma10 > 0 and inp.price < inp.ma10 * (1 - EXIT_MA10_BREAK)
    if (inp.market_block_new or inp.env_tier == "弱势") and below_ma10:
        return ExitView(
            "建议卖出",
            f"大盘弱势/防守，且现价跌破 MA10；浮盈 {pnl:+.1f}%。环境转弱优先防守。",
            "high",
            "环境",
            pnl,
        )

    bad_persist = inp.sector_persist in {"走弱", "偏弱", "一日游", "背离"} or inp.sector_weak
    if bad_persist:
        return ExitView(
            "建议卖出",
            f"主板块状态是{inp.sector_persist or '偏弱'}，短线主线交易优先兑现；浮盈 {pnl:+.1f}%。",
            "high",
            "板块",
            pnl,
        )

    if inp.ma20 > 0 and inp.price < inp.ma20 and not inp.ma20_up:
        return ExitView(
            "建议卖出",
            f"现价 {inp.price:.2f} 已跌破未抬头的 MA20 {inp.ma20:.2f}，趋势破坏；浮盈 {pnl:+.1f}%。",
            "high",
            "趋势",
            pnl,
        )

    vol_ok = inp.volume_ratio is not None and inp.volume_ratio >= EXIT_VOL_BREAK
    if below_ma10 and vol_ok:
        return ExitView(
            "建议卖出",
            f"放量跌破 MA10（量比 {inp.volume_ratio:.2f}）；浮盈 {pnl:+.1f}%。",
            "high",
            "趋势",
            pnl,
        )

    if inp.hold_days >= EXIT_MAX_HOLD_DAYS and pnl <= EXIT_PROFIT_MIN:
        return ExitView(
            "减仓观望",
            f"已持有约 {inp.hold_days} 个交易日，浮盈 {pnl:+.1f}% 未明显走强，短线窗口将尽。",
            "mid",
            "时间",
            pnl,
        )

    if (
        inp.high_20 > 0
        and pnl >= EXIT_PROFIT_MIN
        and inp.price <= inp.high_20 * (1 - EXIT_GIVEBACK)
    ):
        giveback = (1 - inp.price / inp.high_20) * 100
        return ExitView(
            "减仓观望",
            f"浮盈 {pnl:+.1f}%，但相对近20日高回撤约 {giveback:.0f}%，可考虑兑现部分。",
            "mid",
            "兑现",
            pnl,
        )

    return ExitView(
        "持有",
        f"未触发出场条件；浮盈 {pnl:+.1f}%，持有第 {max(inp.hold_days, 0)} 日。继续盯止损与板块。",
        "low",
        "持有",
        pnl,
    )
