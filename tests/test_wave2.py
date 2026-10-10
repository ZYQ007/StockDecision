from app.engine.levels import Bar
from app.engine.wave2 import scan_wave2


def bars_from(closes: list[float]) -> list[Bar]:
    out = []
    prev = closes[0]
    for i, close in enumerate(closes):
        day = f"2026-09-{i + 1:02d}"
        high = max(prev, close) * 1.01
        low = min(prev, close) * 0.99
        out.append(Bar(day, prev, high, low, close, 1e6, 1e8))
        prev = close
    return out


def three_limit_then(extra: list[float]) -> list[float]:
    seq = [10.0]
    for _ in range(3):
        seq.append(round(seq[-1] * 1.1, 2))
    high = seq[-1]
    for factor in extra:
        seq.append(round(high * factor, 2))
    return seq


def test_gentle_pullback_after_three_limits_is_waiting():
    seq = three_limit_then([0.97, 0.95])
    rows = bars_from(seq)
    view = scan_wave2(rows, code="600000", name="测试", price=seq[-1], day_pct=-2.0, volume_ratio=0.8)
    assert view.hit
    assert view.limit_days >= 3
    assert "等二波" in view.reason


def test_a_kill_rejected():
    seq = three_limit_then([0.75])
    rows = bars_from(seq)
    view = scan_wave2(rows, code="600000", name="测试", price=seq[-1], day_pct=-8.0, volume_ratio=1.2)
    assert not view.hit
    assert "A 杀" in view.reason or "回撤" in view.reason


def test_second_wave_started_not_in_waiting_list():
    seq = three_limit_then([0.97, 0.96, 0.99])
    rows = bars_from(seq)
    view = scan_wave2(rows, code="600000", name="测试", price=seq[-1], day_pct=5.0, volume_ratio=1.5)
    assert not view.hit
    assert "二波启动" in view.reason
