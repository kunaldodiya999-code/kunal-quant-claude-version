from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time
from typing import Iterable, Sequence
from zoneinfo import ZoneInfo

from config.settings import TIMEZONE


MARKET_TZ = ZoneInfo(TIMEZONE)
SESSION_START = time(9, 15)
SESSION_END = time(15, 29)
SUPPORTED_MINUTES = (3, 5, 10, 15, 30, 60)


@dataclass(frozen=True)
class Candle:
    timestamp: int
    open: float
    high: float
    low: float
    close: float
    volume: int | None = None
    open_interest: int | None = None


@dataclass(frozen=True)
class DerivedBar:
    timestamp: int
    open: float
    high: float
    low: float
    close: float
    volume: int | None
    open_interest: int | None
    resolution: str
    expected_1m_candles: int
    actual_1m_candles: int
    complete: bool


def _session_bounds(day: date) -> tuple[int, int]:
    start = datetime.combine(day, SESSION_START, tzinfo=MARKET_TZ)
    end = datetime.combine(day, SESSION_END, tzinfo=MARKET_TZ)
    return int(start.timestamp()), int(end.timestamp())


def _is_regular_timestamp(timestamp: int) -> bool:
    dt = datetime.fromtimestamp(timestamp, tz=MARKET_TZ)
    start, end = _session_bounds(dt.date())
    return start <= timestamp <= end


def _expected_timestamps(start: int, end: int) -> list[int]:
    return list(range(start, end + 60, 60))


def aggregate_day(candles: Sequence[Candle], minutes: int) -> list[DerivedBar]:
    if minutes not in SUPPORTED_MINUTES:
        raise ValueError(f"minutes must be one of {SUPPORTED_MINUTES}")

    if not candles:
        return []

    ordered = sorted(candles, key=lambda c: c.timestamp)
    day = datetime.fromtimestamp(ordered[0].timestamp, tz=MARKET_TZ).date()
    if any(datetime.fromtimestamp(c.timestamp, tz=MARKET_TZ).date() != day for c in ordered):
        raise ValueError("aggregate_day accepts candles from one calendar day only")

    session_start, session_end = _session_bounds(day)
    buckets: dict[int, list[Candle]] = {}

    for candle in ordered:
        if not _is_regular_timestamp(candle.timestamp):
            continue
        offset = candle.timestamp - session_start
        bucket_start = session_start + (offset // (minutes * 60)) * minutes * 60
        buckets.setdefault(bucket_start, []).append(candle)

    bars: list[DerivedBar] = []

    for bucket_start in sorted(buckets):
        bucket = sorted(buckets[bucket_start], key=lambda c: c.timestamp)
        # Buckets are anchored at 09:15 like TradingView. The day's last bucket
        # may be shorter (e.g. 60m: 15:15-15:29) and closes with the session;
        # 3m and 5m divide the 375-minute session exactly, so never shorter.
        last_minute = min(bucket_start + (minutes - 1) * 60, session_end)
        expected_ts = _expected_timestamps(bucket_start, last_minute)
        expected = len(expected_ts)
        actual_ts = {c.timestamp for c in bucket}
        complete = len(bucket) == expected and actual_ts == set(expected_ts)

        bars.append(
            DerivedBar(
                timestamp=bucket_start,
                open=bucket[0].open,
                high=max(c.high for c in bucket),
                low=min(c.low for c in bucket),
                close=bucket[-1].close,
                volume=None if any(c.volume is None for c in bucket) else sum(c.volume for c in bucket),
                open_interest=bucket[-1].open_interest,
                resolution=str(minutes),
                expected_1m_candles=expected,
                actual_1m_candles=len(bucket),
                complete=complete,
            )
        )

    return bars


def aggregate_regular_session(candles: Iterable[Candle], minutes: int) -> list[DerivedBar]:
    grouped: dict[date, list[Candle]] = {}
    for candle in candles:
        day = datetime.fromtimestamp(candle.timestamp, tz=MARKET_TZ).date()
        grouped.setdefault(day, []).append(candle)

    bars: list[DerivedBar] = []
    for day in sorted(grouped):
        day_candles = grouped[day]
        start, end = _session_bounds(day)
        timestamps = {c.timestamp for c in day_candles if start <= c.timestamp <= end}
        if not timestamps:
            continue

        expected_day = set(_expected_timestamps(start, end))
        # A derived day is eligible only when the source day has no
        # gap larger than the policy threshold. Smaller gaps remain
        # represented as incomplete derived bars and are never filled.
        missing = sorted(expected_day - timestamps)
        max_run = 0
        run = 0
        previous = None
        for ts in missing:
            if previous is not None and ts == previous + 60:
                run += 1
            else:
                run = 1
            max_run = max(max_run, run)
            previous = ts

        # The source validator's policy is: <=3 missing consecutive
        # minutes is eligible; 4+ is excluded.
        if max_run > 3:
            continue

        bars.extend(aggregate_day(day_candles, minutes))

    return bars
