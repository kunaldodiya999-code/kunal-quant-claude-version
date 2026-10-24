from dataclasses import dataclass

from backtest.opening_breakout_v2_option_integration import run_opening_breakout_trade
from backtest.opening_breakout_v2_signal_engine import OpeningBreakoutEvent
from execution.opening_breakout_v2_execution import V2ExecutionPolicy
from research.opening_breakout_1m_v2 import Candle, V2Config


@dataclass(frozen=True)
class Contract:
    instrument_id: int = 101
    symbol: str = "NSE:NIFTY26SEP25000CE"
    underlying: str = "NIFTY"
    expiry_date: object = None
    strike: int = 25000
    option_type: str = "CE"


class FakeResolver:
    def resolve(self, *, underlying_price, entry_date, direction):
        assert underlying_price == 25010
        assert direction == "LONG"
        return Contract()


def test_v2_signal_resolves_contract_and_completes_historical_trade():
    event = OpeningBreakoutEvent(
        symbol="candidate",
        option_type="CE",
        strike=25000,
        lot_size=65,
        direction="LONG",
        instrument="CALL",
        setup_timestamp=100,
        trigger_timestamp=120,
        breakout_price=101.0,
        trigger_reasons=("CANDLE_HIGH",),
    )
    underlying = [Candle(100, 25000, 25015, 24990, 25010)]
    called = []

    def loader(instrument_id, start, end):
        called.append((instrument_id, start, end))
        return [
            Candle(100, 100, 102, 99, 101),
            Candle(120, 102, 103, 101, 102),
            Candle(121, 103, 108, 102, 107),
            Candle(122, 107, 110, 106, 109),
            Candle(123, 109, 110, 90, 91),
        ]

    config = V2Config(
        capital_allocation_percent=25.0,
        custom_sl_points=5.0,
        tp_mode="CUSTOM_POINTS",
        custom_tp_points=8.0,
        risk_per_trade_value=10000.0,
    )

    result = run_opening_breakout_trade(
        event=event,
        underlying_candles=underlying,
        resolver=FakeResolver(),
        option_loader=loader,
        config=config,
        execution_policy=V2ExecutionPolicy(
            entry_buffer_points=1.0,
            max_slippage_points=2.0,
            fill_timeout_seconds=10,
        ),
        capital=100000,
        lot_size_loader=lambda instrument_id: 65,
    )

    assert called[0][0] == 101
    assert result.contract.symbol == "NSE:NIFTY26SEP25000CE"
    assert result.option_signal_price == 102
    assert result.entry.filled
    assert result.entry.timestamp == 121
    assert result.entry.price == 103
    assert result.quantity == 195
    assert result.lots == 3
    assert result.stop_price == 98
    assert result.target_price == 111
    assert result.exit.reason == "STOP_LOSS"
    assert result.exit.timestamp == 123
    assert result.exit.price == 96
    assert result.gross_pnl == (96 - 103) * 195


def test_missing_lot_size_is_rejected_instead_of_invented():
    event = OpeningBreakoutEvent(
        symbol="candidate",
        option_type="CE",
        strike=25000,
        lot_size=65,
        direction="LONG",
        instrument="CALL",
        setup_timestamp=100,
        trigger_timestamp=120,
        breakout_price=101.0,
        trigger_reasons=("CANDLE_HIGH",),
    )

    class Resolver:
        def resolve(self, **kwargs):
            return Contract()

    def loader(*args):
        return [
            Candle(100, 100, 102, 99, 101),
            Candle(120, 102, 103, 101, 102),
            Candle(121, 103, 104, 102, 103),
        ]

    try:
        run_opening_breakout_trade(
            event=event,
            underlying_candles=[
                Candle(100, 25000, 25015, 24990, 25010)
            ],
            resolver=Resolver(),
            option_loader=loader,
            config=V2Config(custom_sl_points=2.0),
            execution_policy=V2ExecutionPolicy(),
            capital=100000,
            lot_size_loader=lambda instrument_id: (
                (_ for _ in ()).throw(
                    LookupError("lot size missing")
                )
            ),
        )
    except LookupError as exc:
        assert "lot size missing" in str(exc)
    else:
        raise AssertionError("missing lot size must be rejected")


def test_stop_uses_setup_session_candle_not_earliest_loaded_history():
    event = OpeningBreakoutEvent(
        symbol="candidate",
        option_type="CE",
        strike=25000,
        lot_size=65,
        direction="LONG",
        instrument="CALL",
        setup_timestamp=100,
        trigger_timestamp=120,
        breakout_price=101.0,
        trigger_reasons=("CANDLE_HIGH",),
    )

    class Resolver:
        def resolve(self, **kwargs):
            return Contract()

    def loader(*args):
        return [
            # Older history must not determine the stop.
            Candle(50, 70, 80, 60, 75),
            Candle(100, 100, 102, 99, 101),
            Candle(120, 102, 103, 101, 102),
            Candle(121, 103, 104, 102, 103),
            Candle(123, 103, 104, 90, 91),
        ]

    result = run_opening_breakout_trade(
        event=event,
        underlying_candles=[Candle(100, 25000, 25015, 24990, 25010)],
        resolver=Resolver(),
        option_loader=loader,
        config=V2Config(
            custom_sl_points=5.0,
            tp_mode="OFF",
            risk_per_trade_value=10000.0,
        ),
        execution_policy=V2ExecutionPolicy(
            entry_buffer_points=1.0,
            max_slippage_points=2.0,
            fill_timeout_seconds=10,
        ),
        capital=100000,
        lot_size_loader=lambda instrument_id: 65,
    )

    assert result.entry.filled
    assert result.stop_price == 98

def test_slippage_check_uses_option_premium_not_underlying_breakout():
    event = OpeningBreakoutEvent(
        symbol="candidate",
        option_type="CE",
        strike=25000,
        lot_size=65,
        direction="LONG",
        instrument="CALL",
        setup_timestamp=100,
        trigger_timestamp=120,
        breakout_price=25000.0,
        trigger_reasons=("CANDLE_HIGH",),
    )

    class Resolver:
        def resolve(self, **kwargs):
            return Contract()

    def loader(*args):
        return [
            Candle(100, 100, 102, 99, 101),
            Candle(120, 102, 103, 101, 102),
            Candle(121, 103, 104, 102, 103),
            Candle(123, 103, 104, 90, 91),
        ]

    result = run_opening_breakout_trade(
        event=event,
        underlying_candles=[Candle(100, 25000, 25015, 24990, 25010)],
        resolver=Resolver(),
        option_loader=loader,
        config=V2Config(
            custom_sl_points=5.0,
            tp_mode="OFF",
            risk_per_trade_value=10000.0,
        ),
        execution_policy=V2ExecutionPolicy(
            entry_buffer_points=1.0,
            max_slippage_points=2.0,
            fill_timeout_seconds=10,
        ),
        capital=100000,
        lot_size_loader=lambda instrument_id: 65,
    )

    assert result.entry.filled
    assert result.option_signal_price == 102


def test_non_positive_custom_stop_is_rejected_without_exception():
    event = OpeningBreakoutEvent(symbol="candidate", option_type="CE", strike=25000, lot_size=65, direction="LONG", instrument="CALL", setup_timestamp=100, trigger_timestamp=120, breakout_price=101.0, trigger_reasons=("CANDLE_HIGH",))
    class Resolver:
        def resolve(self, **kwargs): return Contract()
    def loader(*args):
        return [Candle(100, 15, 18, 10, 12), Candle(120, 14, 16, 13, 15), Candle(121, 14, 17, 13, 16)]
    result = run_opening_breakout_trade(
        event=event,
        underlying_candles=[Candle(100, 25000, 25015, 24990, 25010)],
        resolver=Resolver(), option_loader=loader,
        config=V2Config(custom_sl_points=20.0),
        execution_policy=V2ExecutionPolicy(entry_buffer_points=1.0, max_slippage_points=2.0, fill_timeout_seconds=10),
        capital=100000, lot_size_loader=lambda instrument_id: 65,
    )
    assert result.status == "INVALID_STOP"
    assert result.stop_price <= 0



def test_invalid_option_ohlc_is_rejected_with_exact_data_diagnostic():
    event = OpeningBreakoutEvent(
        symbol="candidate", option_type="CE", strike=25000, lot_size=65,
        direction="LONG", instrument="CALL", setup_timestamp=100,
        trigger_timestamp=120, breakout_price=101.0,
        trigger_reasons=("CANDLE_HIGH",),
    )

    class Resolver:
        def resolve(self, **kwargs):
            return Contract()

    def loader(*args):
        return [
            Candle(100, 100, 102, 99, 101),
            Candle(120, 102, 103, 101, 102),
            Candle(121, 103, 100, 102, 107),
        ]

    result = run_opening_breakout_trade(
        event=event,
        underlying_candles=[Candle(100, 25000, 25015, 24990, 25010)],
        resolver=Resolver(), option_loader=loader,
        config=V2Config(custom_sl_points=5.0),
        execution_policy=V2ExecutionPolicy(
            entry_buffer_points=1.0, max_slippage_points=2.0, fill_timeout_seconds=10
        ),
        capital=100000, lot_size_loader=lambda instrument_id: 65,
    )

    assert result.status == "INVALID_DATA|symbol=NSE:NIFTY26SEP25000CE|timestamp=121|ohlc=103.0,100.0,102.0,107.0"
    assert result.entry.reason == "INVALID_DATA"
    assert result.quantity == 0
    assert result.gross_pnl == 0.0
