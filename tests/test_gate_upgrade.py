from app.ai.report import build_report
from app.engine.decide import decide
from app.engine.market import classify_market
from app.engine.pick import PickInputs, pick
from app.engine.sector import classify_sector
from app.engine.types import EntryInputs, MarketInputs, SectorDay, SectorInputs
from app.engine.wave2 import scan_wave2, scan_wave2_started
from app.engine.levels import Bar
from app.store.journal import summarize


def market(**kwargs) -> MarketInputs:
    base = dict(
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
        zt_count=55,
        dt_count=4,
        sh_price=3200,
        cy_price=2100,
        total_amount=1.8e12,
        avg_amount_5=1.7e12,
        sh_ma20=3100,
        cy_ma20=2000,
    )
    base.update(kwargs)
    return MarketInputs(**base)


def sector_days(rank=8, pct=1.1) -> list[SectorDay]:
    rows = [
        ("2026-10-03", 0.6, 0.2, 12),
        ("2026-10-06", 0.8, 0.2, 10),
        ("2026-10-07", 0.5, 0.2, 9),
        ("2026-10-08", 0.7, 0.2, 8),
        ("2026-10-09", pct, 0.4, rank),
    ]
    return [SectorDay(d, p, i, r, 100) for d, p, i, r in rows]


def sector(**kwargs) -> SectorInputs:
    days = kwargs.pop("days", None) or sector_days(kwargs.get("rank", 8), kwargs.get("pct", 1.1))
    base = dict(ready=True, name="白酒", rank=8, total=100, pct=1.1, index_pct=0.4, days=days)
    base.update(kwargs)
    base["days"] = days
    return SectorInputs(**base)


def entry(**kwargs) -> EntryInputs:
    base = dict(
        ready=True,
        price=10.0,
        day_pct=0.4,
        ma5=10.05,
        ma10=10.0,
        ma20=9.4,
        ma20_up=True,
        high_20=11.2,
        low_20=8.6,
        ret_10d_pct=8,
        volume_ratio=0.8,
        vwap=10.0,
        amount=5e8,
        board_core=True,
    )
    base.update(kwargs)
    return EntryInputs(**base)


def test_env_tier_strong_and_position_advice():
    view = classify_market(market())
    assert view.env_tier == "强势"
    decision = decide(market(), sector(), entry())
    assert decision.env_tier == "强势"
    assert decision.logic_track == "短期主线交易"
    assert "7 成" in decision.position_advice or "仓位" in decision.position_advice


def test_emotion_weak_maps_to_weak_tier():
    view = classify_market(
        market(
            sh_above_ma20=False,
            cy_above_ma20=False,
            sh_pct=-0.8,
            cy_pct=-1.0,
            amount_ratio=0.7,
            zt_count=10,
            dt_count=45,
            up_count=1000,
            down_count=4000,
        )
    )
    assert view.env_tier == "弱势"
    assert view.block_new


def test_theme_quality_on_continuous_sector():
    view = classify_sector(sector())
    assert view.theme_quality in {"真主线", "中性", "未知"}
    assert view.stage


def test_pseudo_theme_blocks_breakout_buy():
    one_day = [
        SectorDay("2026-10-03", -0.5, 0.2, 70, 100),
        SectorDay("2026-10-06", -0.4, 0.2, 65, 100),
        SectorDay("2026-10-07", -0.3, 0.2, 60, 100),
        SectorDay("2026-10-08", 0.2, 0.2, 55, 100),
        SectorDay("2026-10-09", 4.5, 0.4, 5, 100),
    ]
    decision = decide(
        market(),
        sector(days=one_day, rank=5, pct=4.5),
        entry(price=11.3, day_pct=3.5, ma5=10.9, ma10=10.5, ma20=9.8, high_20=11.0, low_20=9.0, volume_ratio=1.8, vwap=11.15, ret_10d_pct=12, board_core=True),
    )
    assert decision.theme_quality == "伪题材" or decision.verdict != "可买" or decision.setup != "breakout"


def test_stall_volume_veto():
    decision = decide(
        market(),
        sector(),
        entry(price=11.0, day_pct=0.3, ma5=10.9, ma10=10.6, ma20=9.8, high_20=11.1, low_20=8.5, volume_ratio=2.2, ret_10d_pct=10),
    )
    assert decision.verdict != "可买" or "滞涨" in "".join(decision.vetoes) or decision.setup in {"none", "chase", "broken"}


def test_pick_rejects_high_volume_ratio():
    view = pick(
        PickInputs(
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
            amount_5d=1e9,
            sector_rank=8,
            sector_total=100,
            volume_ratio=4.0,
        )
    )
    assert not view.selected
    assert "量比" in view.reason


def test_wave2_started_list_separate():
    seq = [10.0]
    for _ in range(3):
        seq.append(round(seq[-1] * 1.1, 2))
    high = seq[-1]
    for factor in (0.97, 0.96, 0.99):
        seq.append(round(high * factor, 2))
    bars = []
    prev = seq[0]
    for i, close in enumerate(seq):
        day = f"2026-09-{i + 1:02d}"
        bars.append(Bar(day, prev, max(prev, close) * 1.01, min(prev, close) * 0.99, close, 1e6, 1e8))
        prev = close
    waiting = scan_wave2(bars, code="600000", name="测试", price=seq[-1], day_pct=5.0, volume_ratio=1.5)
    started = scan_wave2_started(bars, code="600000", name="测试", price=seq[-1], day_pct=5.0, volume_ratio=1.5)
    assert not waiting.hit
    assert started.hit


def test_report_nine_sections_do_not_change_verdict():
    m = market()
    s = sector()
    e = entry()
    decision = decide(m, s, e)
    report = build_report(
        quote={"code": "600519", "name": "贵州茅台"},
        market=m,
        sector=s,
        entry=e,
        decision_verdict=decision.verdict,
    )
    assert report["ok"]
    assert report["changes_verdict"] is False
    sections = report["sections"]
    for key in (
        "1_market",
        "2_sector",
        "3_stock_logic",
        "4_flow",
        "5_valuation",
        "6_tech",
        "7_risks",
        "8_plan",
        "9_summary",
    ):
        assert key in sections
    assert len(sections["7_risks"]) >= 3
    assert "仓位" in sections["8_plan"]


def test_summarize_by_env_does_not_rewrite_verdict():
    rows = [
        {
            "setup_type": "pullback",
            "ret_3d": 0.02,
            "max_dd_5d": -0.01,
            "detail_json": '{"env_tier":"强势"}',
        },
        {
            "setup_type": "pullback",
            "ret_3d": -0.01,
            "max_dd_5d": -0.03,
            "detail_json": '{"env_tier":"弱势"}',
        },
    ]
    out = summarize(rows)
    assert "by_env" in out
    assert "不直接改写" in out["promotion_note"]
