"""Fetch recent 1-minute underlying candles from FYERS to warm up KTMI.

Read-only: uses the FYERS history API, never places orders. Only candles that
have fully closed before ``now`` are returned, so a forming minute is never
treated as history.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta
from typing import Any

from market_data.resampling import Candle

TARGET_SIGNAL_BARS = 300      # EMA/TRIX state is settled to ~1e-10 well before this
SESSION_MINUTES = 375         # 09:15 .. 15:29
CHUNK_DAYS = 30               # stay well inside FYERS' per-request range limit


def warmup_calendar_days(resolution_minutes: int, target_bars: int = TARGET_SIGNAL_BARS) -> int:
    """Calendar days of 1-minute history needed for ``target_bars`` signal bars."""
    bars_per_day = math.ceil(SESSION_MINUTES / resolution_minutes)
    trading_days = math.ceil(target_bars / bars_per_day)
    # Weekends (7/5) plus a margin for exchange holidays.
    return max(3, math.ceil(trading_days * 7 / 5) + 4)


def parse_history_candles(response: Any) -> list[Candle]:
    rows = response.get("candles") if isinstance(response, dict) else None
    if not isinstance(rows, list):
        raise ValueError("FYERS history response has no 'candles' list.")
    candles = []
    for row in rows:
        ts, o, h, l, c = (row[0], row[1], row[2], row[3], row[4])
        volume = row[5] if len(row) > 5 else None
        candles.append(Candle(int(ts), float(o), float(h), float(l), float(c),
                              None if volume is None else int(volume)))
    return candles


def fetch_minute_history(client: Any, symbol: str, *, resolution_minutes: int, now: datetime) -> list[Candle]:
    """1-minute candles for the warm-up window ending now (closed minutes only)."""
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    start = (now - timedelta(days=warmup_calendar_days(resolution_minutes))).date()
    end = now.date()
    candles: dict[int, Candle] = {}
    chunk_start = start
    while chunk_start <= end:
        chunk_end = min(chunk_start + timedelta(days=CHUNK_DAYS - 1), end)
        response = client.history(
            symbol, resolution="1",
            range_from=chunk_start.isoformat(), range_to=chunk_end.isoformat(),
        )
        for candle in parse_history_candles(response):
            candles[candle.timestamp] = candle
        chunk_start = chunk_end + timedelta(days=1)
    cutoff = int(now.timestamp())
    return [candles[ts] for ts in sorted(candles) if ts + 60 <= cutoff]


__all__ = [
    "TARGET_SIGNAL_BARS", "fetch_minute_history", "parse_history_candles", "warmup_calendar_days",
]
