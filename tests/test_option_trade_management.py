from datetime import date

from backtest.models import BacktestBar
from backtest.option_entry_bridge import OptionCandle, OptionEntry
from backtest.option_trade_lifecycle import OptionExitReason
from backtest.option_trade_management import run_option_trade_management
from indicators.kama_trend_follower.universal import KAMAResult
from strategies.ktmi_trigger_strategy import (
    KTMITriggerEvent,
    TriggerDirection,
    TriggerStrategyId,
)
from strategies.option_contract_resolver import ResolvedOptionContract


def _entry():
    event = KTMITriggerEvent(
        strategy_id=TriggerStrategyId.LONG_SHORT_SPEED,
        direction=TriggerDirection.LONG,
        previous_value=0.49,
        current_value=0.51,
        trigger_value=0.50,
        index=0,
        timestamp=100,
    )
    contract = ResolvedOptionContract(
        instrument_id=1,
        symbol="NIFTYTEST",
        underlying="NIFTY",
        expiry_date=date(2026, 9, 24),
        strike=23000,
        option_type="CE",
    )
    return OptionEntry(
        event=event,
        contract=contract,
        signal_timestamp=100,
        entry_timestamp=101,
        underlying_price=100.0,
        entry_price=100.0,
        lifecycle_action=None,
        lifecycle_reason="test",
    )


def _kama(value):
    return KAMAResult(
        kama=value,
        kama_direction=1,
        kama_percentage_change=0.0,
        kama_bull=False,
        kama_bear=False,
        kama_sideways=True,
        ma50=None,
        ma100=None,
        ma200=None,
    )


def test_runner_uses_existing_kama_exit_rule():
    underlying = [
        BacktestBar(100, 100, 101, 99, 100),
        BacktestBar(102, 100, 101, 99, 90),
    ]
    kama = [_kama(95), _kama(95)]

    options = [
        OptionCandle(101, 100, 101, 99, 100),
        OptionCandle(102, 95, 96, 94, 95),
    ]

    result = run_option_trade_management(
        entry=_entry(),
        option_candles=options,
        underlying_bars=underlying,
        kama_results=kama,
    ).result

    assert result.closed is True
    assert result.exits[-1].reason == OptionExitReason.KAMA_EXIT
    assert result.exits[-1].price == 95


def test_runner_does_not_use_same_entry_candle():
    underlying = [BacktestBar(100, 100, 101, 99, 100)]
    kama = [_kama(95)]

    options = [
        OptionCandle(101, 100, 101, 99, 100),
        OptionCandle(102, 95, 96, 94, 95),
    ]

    result = run_option_trade_management(
        entry=_entry(),
        option_candles=options,
        underlying_bars=underlying,
        kama_results=kama,
    ).result

    assert result.closed is False
