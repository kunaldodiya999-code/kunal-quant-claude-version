"""Candles: FYERS 1-minute history -> 1 / 3 / 5-minute candles from 09:15 (like a TradingView chart of NSE / BSE).

A candle is FINISHED (closed) only when its last minute has ended: the strategy only ever looks at finished candles.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time
from typing import Iterable, Optional, Sequence
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")
SESSION_OPEN = time(9, 15)
SESSION_LAST_MINUTE = time(15, 29)


@dataclass(frozen=True)
class Candle:
    ts: int                   # start of the candle, epoch seconds
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0


def parse_history(response) -> list[Candle]:
    """FYERS history() answer -> candles. Raises ValueError with FYERS' message when it is not 'ok'."""
    if not isinstance(response, dict) or response.get("s") not in ("ok", "no_data"):
        raise ValueError(f"FYERS history failed: {response!r}"[:300])
    out = []
    for row in response.get("candles") or []:
        ts, o, h, l, c = row[:5]
        v = row[5] if len(row) > 5 and row[5] is not None else 0.0
        out.append(Candle(int(ts), float(o), float(h), float(l), float(c), float(v)))
    return sorted({c.ts: c for c in out}.values(), key=lambda c: c.ts)


def local(ts: int) -> datetime:
    return datetime.fromtimestamp(int(ts), IST)


def in_session(ts: int) -> bool:
    return SESSION_OPEN <= local(ts).time() <= SESSION_LAST_MINUTE


def bucket_start(ts: int, minutes: int) -> int:
    """Start of the N-minute candle that this minute belongs to (09:15, 09:18, 09:21 ... for N = 3)."""
    t = local(ts)
    open_ts = int(t.replace(hour=9, minute=15, second=0, microsecond=0).timestamp())
    return open_ts + ((int(ts) - open_ts) // (minutes * 60)) * minutes * 60


def resample(minutes_1m: Iterable[Candle], minutes: int) -> list[Candle]:
    """1-minute candles -> N-minute candles (session minutes only, volume added up)."""
    groups: dict[int, list[Candle]] = {}
    for c in sorted(minutes_1m, key=lambda c: c.ts):
        if in_session(c.ts):
            groups.setdefault(bucket_start(c.ts, minutes) if minutes > 1 else c.ts, []).append(c)
    return [Candle(start, g[0].open, max(x.high for x in g), min(x.low for x in g), g[-1].close,
                   sum(x.volume for x in g)) for start, g in sorted(groups.items())]


def close_time(candle_ts: int, minutes: int) -> int:
    """When an N-minute candle closes (the day's last candle closes at 15:30 at the latest)."""
    end = candle_ts + minutes * 60
    t = local(candle_ts)
    session_end = int(t.replace(hour=15, minute=30, second=0, microsecond=0).timestamp())
    return min(end, session_end)


def finished(candles: Sequence[Candle], minutes: int, now: int) -> list[Candle]:
    """Only the candles that have closed by ``now``."""
    return [c for c in candles if close_time(c.ts, minutes) <= now]


def last_finished(candles: Sequence[Candle], minutes: int, now: int) -> Optional[Candle]:
    done = finished(candles, minutes, now)
    return done[-1] if done else None


__all__ = ["Candle", "IST", "bucket_start", "close_time", "finished", "in_session", "last_finished", "local",
           "parse_history", "resample"]
