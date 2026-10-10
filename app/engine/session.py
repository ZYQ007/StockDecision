"""上海交易时段。不含节假日日历，法定假日会显示为交易时段，但行情不更新时界面会标数据年龄。"""

from datetime import datetime, time
from zoneinfo import ZoneInfo

SH = ZoneInfo("Asia/Shanghai")

OPEN_AM = time(9, 30)
CLOSE_AM = time(11, 30)
OPEN_PM = time(13, 0)
CLOSE_PM = time(15, 0)
AUCTION = time(9, 15)
SESSION_MINUTES = 240


def now_sh(now: datetime | None = None) -> datetime:
    if now is None:
        return datetime.now(SH)
    if now.tzinfo is None:
        return now.replace(tzinfo=SH)
    return now.astimezone(SH)


def session_info(now: datetime | None = None) -> dict:
    current = now_sh(now)
    weekday = current.weekday()
    clock = current.time()
    if weekday >= 5:
        return _pack(current, "closed", 1.0, "周末休市")

    if OPEN_AM <= clock < CLOSE_AM:
        elapsed = _minutes(clock, OPEN_AM)
        return _pack(current, "open", elapsed / SESSION_MINUTES, "交易中")
    if OPEN_PM <= clock < CLOSE_PM:
        elapsed = 120 + _minutes(clock, OPEN_PM)
        return _pack(current, "open", elapsed / SESSION_MINUTES, "交易中")
    if CLOSE_AM <= clock < OPEN_PM:
        return _pack(current, "break", 120 / SESSION_MINUTES, "午间休市")
    if AUCTION <= clock < OPEN_AM:
        return _pack(current, "auction", 0.0, "集合竞价")
    if clock < AUCTION:
        return _pack(current, "closed", 1.0, "未开盘")
    return _pack(current, "closed", 1.0, "已收盘")


def _minutes(clock: time, start: time) -> float:
    return (clock.hour * 60 + clock.minute + clock.second / 60) - (start.hour * 60 + start.minute)


def _pack(current: datetime, state: str, progress: float, label: str) -> dict:
    progress = max(0.0, min(1.0, progress))
    return {
        "state": state,
        "label": label,
        "progress": progress,
        "open": state == "open",
        "amount_reliable": state != "open" or progress >= 0.25,
        "as_of_date": current.date().isoformat(),
        "clock": current.strftime("%H:%M:%S"),
    }
