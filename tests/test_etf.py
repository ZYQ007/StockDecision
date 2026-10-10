from app.engine.etf import (
    STATUS_RICH,
    STATUS_VALUE,
    STATUS_WATCH,
    classify_etf,
    drawdown_from_high,
)
from app.engine.levels import Bar


def _bars(closes: list[float]) -> list[Bar]:
    out = []
    for i, c in enumerate(closes):
        month = 1 + i // 28
        day = 1 + i % 28
        out.append(
            Bar(
                trade_date=f"2024-{month:02d}-{day:02d}",
                open=c,
                high=c * 1.01,
                low=c * 0.99,
                close=c,
                volume=1e6,
                amount=1e8,
            )
        )
    return out


def test_drawdown_from_high():
    closes = [100.0] * 50 + [90.0]
    assert abs(drawdown_from_high(closes, 60) - 0.10) < 1e-9


def test_value_when_deep_drawdown_near_ma20():
    closes = [100.0] * 40 + [90.0] * 20
    bars = _bars(closes)
    result = classify_etf(bucket="broad", price=90.0, bars=bars)
    assert result["status"] == STATUS_VALUE
    assert result["drawdown_60"] is not None and result["drawdown_60"] >= 0.08


def test_rich_when_near_high():
    closes = [80.0] * 40 + [100.0] * 20
    bars = _bars(closes)
    result = classify_etf(bucket="broad", price=100.0, bars=bars)
    assert result["status"] == STATUS_RICH


def test_watch_on_mid_drawdown():
    closes = [100.0] * 50 + [95.0] * 10
    bars = _bars(closes)
    result = classify_etf(bucket="broad", price=95.0, bars=bars)
    assert result["status"] == STATUS_WATCH
