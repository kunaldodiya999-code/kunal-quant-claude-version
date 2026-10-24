import sqlite3

from backtest.models import BacktestBar
from market_data.backtest_loader import load_eligible_bars


def make_db(path):
    with sqlite3.connect(path) as connection:
        connection.execute(
            """
            CREATE TABLE derived_candles (
                id INTEGER PRIMARY KEY,
                symbol TEXT,
                timestamp INTEGER,
                open REAL,
                high REAL,
                low REAL,
                close REAL,
                volume INTEGER,
                open_interest INTEGER,
                resolution TEXT,
                source TEXT,
                complete INTEGER
            )
            """
        )
        connection.executemany(
            """
            INSERT INTO derived_candles
            (symbol,timestamp,open,high,low,close,volume,open_interest,
             resolution,source,complete)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)
            """,
            [
                ("NSE:NIFTY50-INDEX", 1, 100, 101, 99, 100.5, 10, 1000, "3", "TEST", 1),
                ("NSE:NIFTY50-INDEX", 2, 101, 102, 100, 101.5, 10, 1001, "3", "TEST", 0),
                ("NSE:NIFTY50-INDEX", 3, 102, 103, 101, 102.5, 10, 1002, "3", "TEST", 1),
            ],
        )


def test_loader_excludes_incomplete_bars(tmp_path):
    db = tmp_path / "derived.db"
    make_db(db)

    bars = load_eligible_bars(
        db, "NSE:NIFTY50-INDEX", "3", "TEST"
    )

    assert [bar.timestamp for bar in bars] == [1, 3]
    assert all(isinstance(bar, BacktestBar) for bar in bars)


def test_loader_preserves_ohlcv_fields(tmp_path):
    db = tmp_path / "derived.db"
    make_db(db)

    bar = load_eligible_bars(
        db, "NSE:NIFTY50-INDEX", "3", "TEST"
    )[0]

    assert bar.open == 100
    assert bar.high == 101
    assert bar.low == 99
    assert bar.close == 100.5
    assert bar.volume == 10
    assert bar.open_interest == 1000
