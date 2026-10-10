from app.engine.levels import Bar
from app.engine.stock_read import stock_read
from app.engine.types import EntryInputs


def test_stock_read_mentions_ma_and_flow():
    entry = EntryInputs(
        ready=True,
        price=10.0,
        day_pct=0.5,
        ma5=10.0,
        ma10=9.9,
        ma20=9.5,
        ma20_up=True,
        high_20=11.0,
        low_20=8.5,
        ret_10d_pct=4.0,
        volume_ratio=0.9,
        amount=2e8,
        ret_5d_pct=3.0,
        stock_flow_3d=1.2e8,
    )
    bars = [
        Bar(f"2026-09-{i:02d}", 9.5, 10.2, 9.4, 9.8, 1e6, 1.5e8)
        for i in range(1, 12)
    ]
    text = stock_read(entry, bars, volume_ratio=0.9, flow_3d=1.2e8)
    assert "均线" in text
    assert "量能" in text
    assert "主力净流入" in text
