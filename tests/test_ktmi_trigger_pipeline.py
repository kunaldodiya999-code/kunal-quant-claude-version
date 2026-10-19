from backtest.models import BacktestBar
from indicators.ktmi.config import KTMIConfig, MomentumConfig
from backtest.ktmi_trigger_pipeline import run_ktmi_trigger_pipeline


def test_pipeline_preserves_bar_count_and_indices():
    bars = [
        BacktestBar(i, 100+i, 101+i, 99+i, 100+i)
        for i in range(20)
    ]

    config = KTMIConfig(
        momentum=MomentumConfig(source="Close", speed_length=5, signal_length=9, smoothing="EMA", enabled=True, calculation="TRIX"),
        long_momentum=MomentumConfig(source="Close", speed_length=5, signal_length=9, smoothing="EMA", enabled=True, calculation="TRIX"),
        short_momentum=MomentumConfig(source="Low", speed_length=5, signal_length=9, smoothing="EMA", enabled=True, calculation="TRIX"),
        momentum_buy_trigger=None,
        momentum_sell_trigger=None,
        long_buy_trigger=None,
        long_sell_trigger=None,
        short_buy_trigger=None,
        short_sell_trigger=None,
    )

    result = run_ktmi_trigger_pipeline(bars, config)

    assert len(result.bars) == 20
    assert len(result.ktmi_results) == 20
    assert all(0 <= e.index < len(bars) for e in result.events)
    assert all(e.timestamp == bars[e.index].timestamp for e in result.events)


def test_pipeline_respects_disabled_strategy_a_and_b():
    bars = [
        BacktestBar(i, 100+i, 101+i, 99+i, 100+i)
        for i in range(20)
    ]

    config = KTMIConfig()
    trigger_config = __import__(
        "strategies.ktmi_trigger_strategy",
        fromlist=["KTMITriggerStrategyConfig"],
    ).KTMITriggerStrategyConfig(
        long_short_speed_enabled=False,
        momentum_only_enabled=False,
    )

    result = run_ktmi_trigger_pipeline(bars, config, trigger_config)

    assert result.events == ()
