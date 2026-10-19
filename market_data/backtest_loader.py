from __future__ import annotations

import sqlite3
from pathlib import Path

from backtest.models import BacktestBar


def load_eligible_bars(
    path: Path,
    symbol: str,
    resolution: str,
    source: str,
) -> list[BacktestBar]:
    """Load only complete derived bars for backtest signal processing.

    Incomplete derived bars remain stored for audit/research but are excluded
    at the database boundary before bars reach the backtest engine.
    """
    with sqlite3.connect(path) as connection:
        rows = connection.execute(
            """
            SELECT timestamp, open, high, low, close, volume, open_interest
            FROM derived_candles
            WHERE symbol = ?
              AND resolution = ?
              AND source = ?
              AND complete = 1
            ORDER BY timestamp
            """,
            (symbol, resolution, source),
        ).fetchall()

    return [
        BacktestBar(
            timestamp=timestamp,
            open=open_price,
            high=high,
            low=low,
            close=close,
            volume=0 if volume is None else volume,
            open_interest=open_interest,
        )
        for timestamp, open_price, high, low, close, volume, open_interest in rows
    ]
