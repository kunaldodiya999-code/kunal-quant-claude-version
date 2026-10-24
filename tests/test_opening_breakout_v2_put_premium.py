"""BUY PE is a long-premium position.

A bearish V2 signal buys a PUT. The PUT premium must be managed as a LONG
position: stop below entry, target above entry, positive P&L when the
premium rises. Only the CE/PE contract choice follows the signal direction.
"""

from dataclasses import dataclass, replace
from datetime import date

from backtest.opening_breakout_v2_economic_attribution import attribute_trade_economics
from backtest.opening_breakout_v2_option_integration import (
    premium_direction,
    run_opening_breakout_trade,
)
from backtest.opening_breakout_v2_signal_engine import OpeningBreakoutEvent
from execution.opening_breakout_v2_execution import V2ExecutionPolicy
from research.opening_breakout_1m_v2 import Candle, V2Config


@dataclass(frozen=True)
class PutContract:
    instrument_id: int = 202
    symbol: str = "NSE:NIFTY26SEP25000PE"
    underlying: str = "NIFTY"
    expiry_date: object = None
    strike: int = 25000
    option_type: str = "PE"


class RecordingResolver:
    def __init__(self):
        self.directions = []

    def resolve(self, *, underlying_price, entry_date, direction):
        self.directions.append(direction)
        return PutContract()


PUT_EVENT = OpeningBreakoutEvent(
    symbol="candidate",
    option_type="PE",
    strike=25000,
    lot_size=65,
    direction="SHORT",
    instrument="PUT",
    setup_timestamp=0,
    trigger_timestamp=60,
    breakout_price=24990.0,
    trigger_reasons=("CANDLE_LOW",),
)

POLICY = V2ExecutionPolicy(
    entry_buffer_points=1.0,
    max_slippage_points=2.0,
    fill_timeout_seconds=60,
)

CONFIG = V2Config(
    trade_instrument="PUT",
    custom_sl_points=10.0,
    tp_mode="CUSTOM_POINTS",
    custom_tp_points=12.0,
    risk_per_trade_value=5000.0,
)


def _run(option_bars):
    resolver = RecordingResolver()
    trade = run_opening_breakout_trade(
        event=PUT_EVENT,
        underlying_candles=[Candle(0, 25000, 25010, 24985, 24990)],
        resolver=resolver,
        option_loader=lambda *args: option_bars,
        config=CONFIG,
        execution_policy=POLICY,
        capital=100000,
        lot_size_loader=lambda instrument_id: 65,
    )
    return trade, resolver


def test_premium_direction_is_long_for_both_option_instruments():
    assert premium_direction(PUT_EVENT) == "LONG"
    assert premium_direction(replace(PUT_EVENT, direction="LONG", instrument="CALL")) == "LONG"
    assert premium_direction(replace(PUT_EVENT, instrument="FUTURES")) == "SHORT"


def test_rising_put_premium_is_a_winning_long_premium_trade():
    trade, resolver = _run(
        [
            Candle(0, 100, 101, 99, 100),
            Candle(60, 100, 101, 99, 100),
            Candle(120, 100, 101, 99.5, 100.5),
            Candle(180, 101, 108, 100.5, 107),
            Candle(240, 107, 116, 106, 115),
        ]
    )

    assert resolver.directions == ["SHORT"]  # still resolves the PE contract
    assert trade.entry.price == 100
    assert trade.stop_price == 90  # below entry
    assert trade.target_price == 112  # above entry
    assert trade.exit.reason == "TARGET"
    assert trade.gross_pnl > 0
    assert trade.gross_pnl == (trade.exit.price - trade.entry.price) * trade.quantity


def test_falling_put_premium_stops_out_below_entry():
    trade, _ = _run(
        [
            Candle(0, 100, 101, 99, 100),
            Candle(60, 100, 101, 99, 100),
            Candle(120, 100, 101, 99.5, 100.5),
            Candle(180, 99, 99.5, 85, 86),
        ]
    )

    assert trade.exit.reason == "STOP_LOSS"
    assert trade.exit.price <= 90
    assert trade.gross_pnl < 0


def test_put_entry_above_signal_premium_is_adverse_slippage():
    trade, _ = _run(
        [
            Candle(0, 100, 101, 99, 100),
            Candle(60, 100, 101, 99, 100),
            Candle(120, 103, 104, 102.5, 103),
        ]
    )

    # Limit = 100 + 1 buffer = 101 is never reachable (low 102.5): no fill.
    assert not trade.entry.filled

    trade, _ = _run(
        [
            Candle(0, 100, 101, 99, 100),
            Candle(60, 100, 101, 99, 100),
            Candle(120, 98, 100, 97, 99),
            Candle(180, 99, 116, 98, 115),
        ]
    )
    # Filling below the signal premium is favourable, never rejected.
    assert trade.entry.filled
    assert trade.status == "CLOSED"


def test_put_economic_attribution_uses_long_premium_sign():
    trade, _ = _run(
        [
            Candle(0, 100, 101, 99, 100),
            Candle(60, 100, 101, 99, 100),
            Candle(120, 100, 101, 99.5, 100.5),
            Candle(180, 101, 108, 100.5, 107),
            Candle(240, 107, 116, 106, 115),
        ]
    )
    attribution = attribute_trade_economics(
        trade, intended_risk=5000.0, trade_date=date(2026, 9, 1)
    )

    assert attribution.theoretical_strategy_pnl == (112 - 100) * trade.quantity
    assert attribution.theoretical_strategy_pnl > 0
