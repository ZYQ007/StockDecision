from datetime import date, datetime, timedelta

from app.engine.decide import decide
from app.engine.levels import Bar, compute_reference, split_bars
from app.engine.pool import screen_one
from app.engine.sector_history import build_histories, proxy_board_pcts
from app.engine.session import session_info
from app.engine.types import EntryInputs, MarketInputs, SectorDay, SectorInputs
from app.store.journal import forward_returns


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
        zt_count=35,
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


def persistent_days(rank=8, pct=1.1, index_pct=0.4) -> list[SectorDay]:
    rows = [
        ("2026-10-03", 0.6, 0.2, 12),
        ("2026-10-06", 0.8, 0.2, 10),
        ("2026-10-07", 0.5, 0.2, 9),
        ("2026-10-08", 0.7, 0.2, 8),
        ("2026-10-09", pct, index_pct, rank),
    ]
    return [SectorDay(trade_date, day_pct, idx, day_rank, 100) for trade_date, day_pct, idx, day_rank in rows]


def sector(**kwargs) -> SectorInputs:
    days = kwargs.pop("days", None)
    base = dict(ready=True, name="白酒", rank=8, total=100, pct=1.1, index_pct=0.4)
    base.update(kwargs)
    if days is None:
        days = persistent_days(base["rank"], base["pct"], base["index_pct"])
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
        suspended=False,
    )
    base.update(kwargs)
    return EntryInputs(**base)


def test_pullback_is_buy():
    decision = decide(market(), sector(), entry())
    assert decision.verdict == "可买"
    assert decision.setup == "pullback"
    assert decision.gates[0].status == "过"
    assert decision.gates[2].status == "过"


def test_chase_is_not_buy():
    decision = decide(
        market(),
        sector(),
        entry(price=11.5, day_pct=8.2, ma5=10.6, ma10=10.2, ma20=9.5, high_20=11.8, low_20=8.0, ret_10d_pct=32, vwap=10.8),
    )
    assert decision.verdict == "不买"
    assert decision.setup == "chase"
    assert decision.watch_price == 10.2


def test_mild_extension_is_wait():
    decision = decide(
        market(),
        sector(),
        entry(price=11.0, day_pct=3.0, ma5=10.7, ma10=10.4, ma20=9.6, high_20=11.2, low_20=8.0, ret_10d_pct=12, vwap=10.9),
    )
    assert decision.verdict == "观望"
    assert decision.verdict != "可买"
    assert "MA10" in decision.watch_text


def test_defense_blocks_pullback():
    decision = decide(
        market(
            sh_above_ma20=False,
            cy_above_ma20=False,
            sh_pct=-1.2,
            cy_pct=-1.4,
            amount_ratio=0.7,
            up_count=800,
            down_count=4200,
        ),
        sector(),
        entry(),
    )
    assert decision.verdict == "不买"
    assert decision.scores["regime"] == "防守"
    assert decision.gates[0].status == "不过"
    assert decision.gates[2].status == "过"


def test_weak_sector_blocks():
    decision = decide(market(), sector(rank=80, total=100, pct=-1.8), entry())
    assert decision.verdict == "不买"


def test_breakout_is_buy():
    decision = decide(
        market(),
        sector(),
        entry(price=11.3, day_pct=3.5, ma5=10.9, ma10=10.5, ma20=9.8, high_20=11.0, low_20=9.0, volume_ratio=1.8, vwap=11.15, ret_10d_pct=12),
    )
    assert decision.verdict == "可买"
    assert decision.setup == "breakout"


def test_climax_does_not_chase_breakout_but_allows_pullback():
    hot = market(sh_range_pos=0.92, amount_ratio=1.4, zt_count=96, sh_pct=0.2)
    breakout = decide(
        hot,
        sector(),
        entry(price=11.3, day_pct=3.5, ma5=10.9, ma10=10.5, ma20=9.8, high_20=11.0, low_20=9.0, volume_ratio=1.8, vwap=11.15),
    )
    pullback = decide(hot, sector(), entry())
    assert breakout.verdict == "观望"
    assert pullback.verdict == "可买"


def test_broken_trend():
    decision = decide(market(), sector(), entry(price=9.0, ma20=9.4, ma20_up=False))
    assert decision.verdict == "不买"
    assert decision.setup == "broken"


def test_unaligned_sector_stays_out_of_pool():
    row = screen_one(
        market(),
        SectorInputs(ready=False),
        entry(price=11.0, day_pct=3.0, ma5=10.7, ma10=10.4, high_20=11.2, low_20=8.0),
        code="600519",
        name="贵州茅台",
        industry="白酒",
        amount=5e8,
        circ_mv=2e11,
        volume_ratio=0.8,
    )
    assert row is None


def test_pool_pullback_bucket():
    row = screen_one(
        market(),
        sector(),
        entry(),
        code="600519",
        name="贵州茅台",
        industry="白酒",
        amount=5e8,
        circ_mv=2e11,
        volume_ratio=0.8,
    )
    assert row is not None
    assert row["bucket"] == "pullback"


def test_reference_excludes_eval_day():
    start = date(2026, 1, 1)
    bars = []
    for i in range(40):
        close = 10 + i * 0.1
        bars.append(Bar((start + timedelta(days=i)).isoformat(), close, close + 0.2, close - 0.2, close, 1_000_000, 2e8))
    ref, last = split_bars(bars, bars[-1].trade_date)
    levels = compute_reference(ref)
    assert last is not None
    assert levels is not None
    assert abs(levels["ma5"] - sum(b.close for b in ref[-5:]) / 5) < 1e-9
    assert levels["high_20"] < last.high


def test_forward_returns():
    future = [
        Bar("2026-10-10", 10.2, 11.2, 10.1, 11.0, 1, 1),
        Bar("2026-10-13", 11.0, 12.0, 10.8, 12.0, 1, 1),
        Bar("2026-10-14", 12.0, 12.0, 8.0, 9.0, 1, 1),
        Bar("2026-10-15", 9.0, 10.5, 8.8, 10.0, 1, 1),
        Bar("2026-10-16", 10.0, 13.2, 9.9, 13.0, 1, 1),
    ]
    r1, r3, r5, dd = forward_returns(10, future)
    assert abs(r1 - 0.1) < 1e-9
    assert abs(r3 - (-0.1)) < 1e-9
    assert abs(r5 - 0.3) < 1e-9
    assert abs(dd - (-0.2)) < 1e-9


def test_persistent_sector_still_buy():
    decision = decide(market(), sector(), entry())
    assert decision.verdict == "可买"
    assert decision.scores["sector_persist"] == "连续"
    assert decision.gates[1].status == "过"
    assert "跑赢上证" in decision.gates[1].text


def test_one_day_sector_is_wait():
    days = [
        SectorDay("2026-10-03", -0.5, 0.2, 70, 100),
        SectorDay("2026-10-06", -0.4, 0.1, 72, 100),
        SectorDay("2026-10-07", -0.3, 0.2, 68, 100),
        SectorDay("2026-10-08", -0.2, 0.2, 65, 100),
        SectorDay("2026-10-09", 3.2, 0.3, 8, 100),
    ]
    decision = decide(market(), sector(rank=8, total=100, pct=3.2, index_pct=0.3, days=days), entry())
    assert decision.verdict == "观望"
    assert decision.scores["sector_persist"] == "一日游"
    assert decision.gates[1].status == "不过"


def test_fading_sector_is_not_buy():
    days = [
        SectorDay("2026-10-06", 1.2, 0.2, 18, 100),
        SectorDay("2026-10-07", 0.8, 0.2, 30, 100),
        SectorDay("2026-10-08", 0.4, 0.2, 44, 100),
        SectorDay("2026-10-09", 0.2, 0.3, 58, 100),
    ]
    decision = decide(market(), sector(rank=58, total=100, pct=0.2, index_pct=0.3, days=days), entry())
    assert decision.verdict == "不买"
    assert decision.scores["sector_persist"] == "走弱"


def test_flow_amount_is_shown_when_present():
    days = persistent_days()
    for day in days[-3:]:
        day.inflow = 1.5e8
    decision = decide(market(), sector(days=days), entry())
    assert "板块主力净流入 +4.50 亿" in decision.gates[1].text


def test_flow_divergence_is_wait():
    days = persistent_days()
    for day in days[-3:]:
        day.inflow = -1e8
    decision = decide(market(), sector(days=days), entry())
    assert decision.verdict == "观望"
    assert decision.scores["sector_persist"] == "背离"


def test_exhausted_sector_waits():
    days = [
        SectorDay("2026-10-03", 1.5, 0.2, 12, 100),
        SectorDay("2026-10-06", 1.8, 0.2, 10, 100),
        SectorDay("2026-10-07", 2.0, 0.2, 8, 100),
        SectorDay("2026-10-08", 1.6, 0.2, 9, 100),
        SectorDay("2026-10-09", 2.2, 0.3, 6, 100),
    ]
    decision = decide(market(), sector(rank=6, total=100, pct=2.2, index_pct=0.3, days=days), entry())
    assert decision.verdict == "观望"
    assert decision.scores["sector_persist"] == "涨满"
    assert "歇一天" in decision.watch_text


def test_proxy_history_prefers_official():
    members = {"白酒": ["a", "b", "c"], "银行": ["d", "e", "f"]}
    series = {
        "a": [("d1", 10.0), ("d2", 11.0)],
        "b": [("d1", 10.0), ("d2", 10.0)],
        "c": [("d1", 10.0), ("d2", 12.0)],
        "d": [("d1", 10.0), ("d2", 9.0)],
        "e": [("d1", 10.0), ("d2", 9.0)],
        "f": [("d1", 10.0), ("d2", 8.0)],
    }
    proxy = proxy_board_pcts(members, series, min_members=3)
    assert abs(proxy["白酒"]["d2"] - 10) < 1e-9
    assert "空" not in proxy_board_pcts({"空": ["a"]}, {"a": [("d1", 1.0), ("d2", 2.0)]}, 3)
    histories = build_histories(
        ["白酒", "银行"],
        proxy,
        {"白酒": {"d2": {"pct": 1.5, "rank": 3, "total": 40, "inflow": None}}},
        {"d2": 0.5},
    )
    assert histories["白酒"][-1].pct == 1.5
    assert histories["白酒"][-1].rank == 3
    assert histories["银行"][-1].pct < 0
    assert histories["银行"][-1].index_pct == 0.5


def test_session_clock():
    from zoneinfo import ZoneInfo

    sh = ZoneInfo("Asia/Shanghai")
    friday = session_info(datetime(2026, 10, 9, 10, 30, tzinfo=sh))
    saturday = session_info(datetime(2026, 10, 10, 10, 30, tzinfo=sh))
    assert friday["open"] is True
    assert abs(friday["progress"] - 0.25) < 0.01
    assert saturday["state"] == "closed"
    assert saturday["amount_reliable"] is True


def test_hold_is_buy():
    decision = decide(
        market(),
        sector(),
        entry(
            price=10.0,
            day_pct=1.0,
            ma5=10.05,
            ma10=10.0,
            ma20=9.4,
            high_20=12.0,
            low_20=8.0,
            volume_ratio=1.25,
            ret_5d_pct=5.0,
            index_ret_5d_pct=1.0,
            stock_flow_3d=1e8,
        ),
    )
    assert decision.verdict == "可买"
    assert decision.setup == "hold"


def test_leader_is_buy():
    decision = decide(
        market(),
        sector(amount_pct=0.1),
        entry(
            price=10.5,
            day_pct=2.0,
            ma5=10.2,
            ma10=10.0,
            ma20=9.5,
            high_20=12.0,
            low_20=8.0,
            volume_ratio=1.6,
            vwap=10.4,
            ret_5d_pct=6.0,
            index_ret_5d_pct=1.0,
            stock_flow_3d=1e8,
            board_core=True,
        ),
    )
    assert decision.verdict == "可买"
    assert decision.setup == "leader"


def test_climax_does_not_block_hold():
    decision = decide(
        market(sh_range_pos=0.92, amount_ratio=1.4, zt_count=96, sh_pct=0.2),
        sector(),
        entry(
            price=10.0,
            day_pct=1.0,
            ma5=10.05,
            ma10=10.0,
            ma20=9.4,
            high_20=12.0,
            low_20=8.0,
            volume_ratio=1.25,
            ret_5d_pct=5.0,
            index_ret_5d_pct=1.0,
            stock_flow_3d=1e8,
        ),
    )
    assert decision.scores["regime"] == "高潮"
    assert decision.verdict == "可买"
    assert decision.setup == "hold"
