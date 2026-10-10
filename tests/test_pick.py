from app.engine.decide import decide
from app.engine.pick import PickInputs, pick
from app.engine.pool import candidate_of
from app.engine.types import EntryInputs, MarketInputs, SectorDay, SectorInputs


def market() -> MarketInputs:
    return MarketInputs(
        ready=True,
        sh_above_ma20=True,
        cy_above_ma20=True,
        sh_ma20_up=True,
        cy_ma20_up=True,
        sh_pct=0.4,
        cy_pct=0.5,
        amount_ratio=1.05,
        amount_reliable=True,
        sh_range_pos=0.55,
        sh_upper_shadow=0.1,
        sh_near_low=False,
        up_count=3200,
        down_count=1700,
        zt_count=35,
        dt_count=4,
        sh_price=3200,
        cy_price=2100,
        total_amount=1.8e12,
        avg_amount_5=1.7e12,
        sh_ma20=3100,
        cy_ma20=2000,
    )


def sector() -> SectorInputs:
    days = [
        SectorDay("2026-10-03", 0.6, 0.2, 12, 100),
        SectorDay("2026-10-06", 0.8, 0.2, 10, 100),
        SectorDay("2026-10-07", 0.5, 0.2, 9, 100),
        SectorDay("2026-10-08", 0.7, 0.2, 8, 100),
        SectorDay("2026-10-09", 1.1, 0.4, 8, 100),
    ]
    return SectorInputs(ready=True, name="白酒", rank=8, total=100, pct=1.1, index_pct=0.4, days=days, kind="行业", source="同花顺")


def entry() -> EntryInputs:
    return EntryInputs(
        ready=True,
        price=10.35,
        day_pct=1.0,
        ma5=10.2,
        ma10=10.0,
        ma20=9.4,
        ma20_up=True,
        high_20=11.2,
        low_20=8.6,
        ret_10d_pct=8,
        volume_ratio=0.8,
        amount=5e8,
    )


def picked(**kwargs) -> PickInputs:
    base = dict(
        price=10.35,
        day_pct=1.0,
        ma5=10.2,
        ma10=10.0,
        ma20=9.4,
        ma20_up=True,
        high_20=11.2,
        low_20=8.6,
        ret_10d_pct=8,
        ret_5d_pct=4.0,
        index_ret_5d_pct=0.5,
        limit_up=False,
        sector_ready=True,
        sector_persist="连续",
        flow_3d=[1e8, 1e8, 1e8],
        price_up_3d=True,
        flow_5d=4e8,
        amount_5d=2e9,
        sector_rank=8,
        sector_total=100,
    )
    base.update(kwargs)
    return PickInputs(**base)


def test_broken_trend_is_not_candidate():
    view = pick(picked(price=9.0, ma20_up=False))
    assert not view.selected
    assert "趋势" in view.reason


def test_flow_divergence_is_not_candidate():
    view = pick(picked(flow_3d=[-1e8, -1e8, -2e8], price_up_3d=True))
    assert not view.selected
    assert "净流入为负" in view.reason


def test_missing_stock_flow_is_weak_candidate():
    view = pick(picked(flow_3d=None))
    assert not view.selected
    assert view.weak
    assert "资金流暂缺" in view.reason


def test_sector_divergence_is_not_candidate():
    view = pick(picked(sector_persist="背离"))
    assert not view.selected


def test_candidate_does_not_become_buy():
    view = pick(picked())
    assert view.selected
    assert "近 3 日主力净流入" in view.reason
    assert "强于上证" in view.reason
    decision = decide(market(), sector(), entry())
    assert decision.verdict == "观望"
    row = candidate_of(
        market(),
        sector(),
        entry(),
        picked(),
        code="600519",
        name="贵州茅台",
        industry="白酒",
        amount=5e8,
        circ_mv=2e11,
        volume_ratio=0.8,
    )
    assert row is not None
    assert row["bucket"] == "candidate"
    assert row["verdict"] == "观望"
    assert "今天还不是买点" in row["reason"]
