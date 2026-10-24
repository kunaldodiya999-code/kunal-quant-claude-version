import sqlite3

from pathlib import Path

from backtest.fyers_option_candles import FyersOptionCandleLoader


def test_loader_reads_only_requested_fyers_option_rows(tmp_path: Path):
    db = tmp_path / "test.db"

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

        connection.executemany(
            "INSERT INTO candles VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (10, 100, 1, 2, 0.5, 1.5, 10, 20, "1", "FYERS_FNO_HISTORY"),
                (10, 101, 1.5, 2.5, 1, 2, 10, 20, "1", "FYERS_FNO_HISTORY"),
                (10, 102, 2, 3, 1.5, 2.5, 10, 20, "1", "OTHER"),
                (11, 101, 9, 10, 8, 9, 10, 20, "1", "FYERS_FNO_HISTORY"),
            ],
        )

    loader = FyersOptionCandleLoader(db)

    candles = loader.load(10, 100, 101)

    assert [c.timestamp for c in candles] == [100, 101]
    assert candles[0].close == 1.5


def test_loader_is_callable_for_entry_bridge(tmp_path: Path):
    db = tmp_path / "test.db"

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
            (10, 200, 5, 6, 4, 5.5, 1, 2, "1", "FYERS_FNO_HISTORY"),
        )

    loader = FyersOptionCandleLoader(db)

    candles = loader(10, 200, 200)

    assert len(candles) == 1
    assert candles[0].timestamp == 200
