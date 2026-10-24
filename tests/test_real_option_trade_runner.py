from pathlib import Path

import sqlite3

from backtest.fyers_option_candles import FyersOptionCandleLoader
from backtest.models import BacktestBar
from backtest.real_option_trade_runner import calculate_nifty_kama
from strategies.ktmi_trigger_strategy import (
    KTMITriggerEvent,
    TriggerDirection,
    TriggerStrategyId,
)


def test_real_runner_uses_existing_kama_implementation():
    bars = [
        BacktestBar(100, 100, 101, 99, 100),
        BacktestBar(101, 101, 102, 100, 101),
        BacktestBar(102, 102, 103, 101, 102),
    ]

    results = calculate_nifty_kama(bars)

    assert len(results) == len(bars)


def test_option_loader_reads_real_data_contract(tmp_path: Path):
    db = tmp_path / "real.db"

    with sqlite3.connect(db) as connection:
        connection.execute(
            """
            CREATE TABLE candles (
                instrument_id INTEGER,
                timestamp INTEGER,
                open REAL,
                high REAL,
                low REAL,
                close REAL,
                volume INTEGER,
                open_interest INTEGER,
                resolution TEXT,
                source TEXT
            )
            """
        )
        connection.execute(
            "INSERT INTO candles VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (99, 10, 10, 11, 9, 10.5, 1, 1, "1", "FYERS_FNO_HISTORY"),
        )

    loader = FyersOptionCandleLoader(db)
    candles = loader(99, 10, 10)

    assert candles[0].timestamp == 10
    assert candles[0].close == 10.5


def test_runner_counts_resolver_lookup_as_data_miss():
    from backtest.real_option_trade_runner import run_real_option_trades

    class MissingResolver:
        def resolve(self, **kwargs):
            raise LookupError("contract unavailable")

    class Loader:
        def __call__(self, *args):
            return []

    bars = [BacktestBar(100, 100, 101, 99, 100)]
    event = KTMITriggerEvent(
        strategy_id=TriggerStrategyId.LONG_SHORT_SPEED,
        direction=TriggerDirection.LONG,
        previous_value=0.1,
        current_value=0.2,
        trigger_value=0.15,
        index=0,
        timestamp=100,
    )

    result = run_real_option_trades(
        bars=bars,
        events=[event],
        resolver=MissingResolver(),
        option_loader=Loader(),
    )

    assert result.trades == ()
    assert result.unresolved_events == 1
    assert result.no_entry_candle_events == 0
