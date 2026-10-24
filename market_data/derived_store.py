from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Iterable

from market_data.resampling import DerivedBar


SCHEMA = """
CREATE TABLE IF NOT EXISTS derived_candles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    timestamp INTEGER NOT NULL,
    open REAL NOT NULL,
    high REAL NOT NULL,
    low REAL NOT NULL,
    close REAL NOT NULL,
    volume INTEGER,
    open_interest INTEGER,
    resolution TEXT NOT NULL,
    source TEXT NOT NULL,
    expected_1m_candles INTEGER NOT NULL,
    actual_1m_candles INTEGER NOT NULL,
    complete INTEGER NOT NULL CHECK (complete IN (0, 1)),
    UNIQUE(symbol, timestamp, resolution, source)
);

CREATE INDEX IF NOT EXISTS idx_derived_symbol_resolution_timestamp
ON derived_candles(symbol, resolution, timestamp);
"""


def initialize_store(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as connection:
        connection.executescript(SCHEMA)


def replace_bars(
    path: Path,
    symbol: str,
    resolution: str,
    source: str,
    bars: Iterable[DerivedBar],
) -> int:
    initialize_store(path)
    rows = [
        (
            symbol,
            bar.timestamp,
            bar.open,
            bar.high,
            bar.low,
            bar.close,
            bar.volume,
            bar.open_interest,
            resolution,
            source,
            bar.expected_1m_candles,
            bar.actual_1m_candles,
            int(bar.complete),
        )
        for bar in bars
    ]

    with sqlite3.connect(path) as connection:
        connection.execute(
            "DELETE FROM derived_candles WHERE symbol = ? AND resolution = ? AND source = ?",
            (symbol, resolution, source),
        )
        connection.executemany(
            """
            INSERT INTO derived_candles (
                symbol, timestamp, open, high, low, close,
                volume, open_interest, resolution, source,
                expected_1m_candles, actual_1m_candles, complete
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        connection.commit()

    return len(rows)
