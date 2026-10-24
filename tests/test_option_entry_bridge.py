from datetime import date

from backtest.models import BacktestBar
from backtest.option_entry_bridge import (
    OptionCandle,
    resolve_option_entries,
)
from backtest.position_lifecycle import SignalAction
from strategies.ktmi_trigger_strategy import (
    KTMITriggerEvent,
    TriggerDirection,
    TriggerStrategyId,
)
from strategies.option_contract_resolver import ResolvedOptionContract


class FakeResolver:
    def resolve(self, *, underlying_price, entry_date, direction):
        return ResolvedOptionContract(
            instrument_id=101,
            symbol="NIFTYTEST",
            underlying="NIFTY",
            expiry_date=date(2026, 9, 24),
            strike=23000,
            option_type="CE" if direction == "LONG" else "PE",
        )


def _event(index=1, direction=TriggerDirection.LONG):
    return KTMITriggerEvent(
        strategy_id=TriggerStrategyId.LONG_SHORT_SPEED,
        direction=direction,
        previous_value=0.49,
        current_value=0.51,
        trigger_value=0.50,
        index=index,
        timestamp=2,
    )


def _bars():
    return [
        BacktestBar(1, 100, 101, 99, 100, 0, None),
        BacktestBar(2, 101, 102, 100, 101, 0, None),
    ]


def test_entry_uses_first_option_candle_strictly_after_signal():
    def loader(instrument_id, start, end):
        return [
            OptionCandle(2, 10, 11, 9, 10.5),  # same timestamp: forbidden
            OptionCandle(3, 10.5, 12, 10, 11.5),
        ]

    entries = resolve_option_entries(
        bars=_bars(),
        events=[_event()],
        resolver=FakeResolver(),
        option_candle_loader=loader,
    )

    assert len(entries) == 1
    assert entries[0].signal_timestamp == 2
    assert entries[0].entry_timestamp == 3
    assert entries[0].entry_price == 11.5


def test_missing_next_option_candle_is_not_fabricated():
    def loader(instrument_id, start, end):
        return [OptionCandle(2, 10, 10, 10, 10)]

    entries = resolve_option_entries(
        bars=_bars(),
        events=[_event()],
        resolver=FakeResolver(),
        option_candle_loader=loader,
    )

    assert entries == []


def test_same_strategy_second_signal_is_blocked_by_lifecycle():
    def loader(instrument_id, start, end):
        return [OptionCandle(3, 10, 11, 9, 10.5)]

    events = [_event(index=1), _event(index=1)]

    entries = resolve_option_entries(
        bars=_bars(),
        events=events,
        resolver=FakeResolver(),
        option_candle_loader=loader,
    )

    assert len(entries) == 1
    assert entries[0].lifecycle_action == SignalAction.ENTER
