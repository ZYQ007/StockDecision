from app.engine.exit import ExitInputs, classify_exit


def base(**kwargs) -> ExitInputs:
    data = dict(
        entry_price=10.0,
        price=10.2,
        stop_pct=5.0,
        hold_days=1,
        ma10=10.0,
        ma20=9.5,
        ma20_up=True,
        volume_ratio=0.9,
        high_20=10.5,
        market_block_new=False,
        env_tier="强势",
        sector_persist="连续",
        sector_weak=False,
    )
    data.update(kwargs)
    return ExitInputs(**data)


def test_stop_loss_triggers_sell():
    view = classify_exit(base(price=9.4))
    assert view.status == "建议卖出"
    assert view.tag == "止损"
    assert view.urgency == "high"
    assert view.pnl_pct < -5


def test_sector_fade_triggers_sell():
    view = classify_exit(base(sector_persist="一日游", price=10.1))
    assert view.status == "建议卖出"
    assert view.tag == "板块"


def test_broken_ma20_triggers_sell():
    # 未触及 -5% 止损，但跌破未抬头 MA20
    view = classify_exit(base(price=9.6, ma10=9.8, ma20=9.7, ma20_up=False))
    assert view.status == "建议卖出"
    assert view.tag == "趋势"


def test_time_stop_is_trim():
    view = classify_exit(base(hold_days=5, price=10.1))
    assert view.status == "减仓观望"
    assert view.tag == "时间"
    assert view.urgency == "mid"


def test_hold_when_healthy():
    view = classify_exit(base())
    assert view.status == "持有"
    assert view.urgency == "low"
    assert view.tag == "持有"


def test_env_weak_below_ma10():
    view = classify_exit(base(env_tier="弱势", market_block_new=True, price=9.7, ma10=10.0))
    assert view.status == "建议卖出"
    assert view.tag == "环境"
