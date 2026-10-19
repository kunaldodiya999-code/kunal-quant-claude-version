"""Real FYERS option-candle loader.

This is the data-access boundary for the existing historical option
candles stored by the FYERS F&O downloader. It deliberately does not
resolve contracts or alter trade-management behavior.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from backtest.option_entry_bridge import OptionCandle


DEFAULT_OPTION_SOURCE = "FYERS_FNO_HISTORY"


class FyersOptionCandleLoader:
    """Load stored 1-minute FYERS option candles by instrument."""

    def __init__(
        self,
        database_path: Path,
        *,
        resolution: str = "1",
        source: str = DEFAULT_OPTION_SOURCE,
    ) -> None:
        self.database_path = Path(database_path)
        self.resolution = resolution
        self.source = source

    def load(
        self,
        instrument_id: int,
        start_timestamp: int,
        end_timestamp: int,
    ) -> list[OptionCandle]:
        if end_timestamp < start_timestamp:
            raise ValueError(
                "end_timestamp must be >= start_timestamp"
            )

        with sqlite3.connect(self.database_path) as connection:
            rows = connection.execute(
                """
                SELECT timestamp, open, high, low, close
                FROM candles
                WHERE instrument_id = ?
                  AND resolution = ?
                  AND source = ?
                  AND timestamp BETWEEN ? AND ?
                ORDER BY timestamp ASC
                """,
                (
                    instrument_id,
                    self.resolution,
                    self.source,
                    start_timestamp,
                    end_timestamp,
                ),
            ).fetchall()

        return [
            OptionCandle(
                timestamp=int(row[0]),
                open=float(row[1]),
                high=float(row[2]),
                low=float(row[3]),
                close=float(row[4]),
            )
            for row in rows
        ]

    def __call__(
        self,
        instrument_id: int,
        start_timestamp: int,
        end_timestamp: int,
    ) -> list[OptionCandle]:
        return self.load(
            instrument_id,
            start_timestamp,
            end_timestamp,
        )
