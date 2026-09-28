"""
Date-aware NSE F&O session definition (PROPOSAL, pure functions, no I/O).

Why: the reference backtest hard-codes "regular option session = candle
starts 09:15..15:29" and MARKET_CLOSE = 15:30. NSE moved the equity
derivatives close from 15:30 to 15:40 effective 2026-08-03 (NSE circular
NSE/FAOP/74467 as reported in the press on 2026-09-28 -- verify against
the primary NSE circular before relying on the exact date). The option
candles already in the local database confirm the change: 385 one-minute
candles/day ending 15:39 from Aug 2026, versus 375 ending 15:29 in Nov 2024.

So the correct session depends on the trading date. Everything here is
data, not strategy: nothing in KTMI, the resolver, or lifecycle rules is
touched. Holidays/special sessions (e.g. Muhurat) are NOT modelled.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")

FNO_EXTENDED_CLOSE_EFFECTIVE = date(2026, 8, 3)


@dataclass(frozen=True)
class OptionSession:
    open: time
    close: time              # exchange close; no candle STARTS at/after this
    last_candle_start: time  # last 1-minute candle start inside the session

    @property
    def expected_1m_candles(self) -> int:
        minutes = (self.close.hour * 60 + self.close.minute) - (
            self.open.hour * 60 + self.open.minute
        )
        return minutes


_OLD = OptionSession(time(9, 15), time(15, 30), time(15, 29))
_NEW = OptionSession(time(9, 15), time(15, 40), time(15, 39))


def option_session(day: date) -> OptionSession:
    return _NEW if day >= FNO_EXTENDED_CLOSE_EFFECTIVE else _OLD


def session_close_timestamp(day: date) -> int:
    s = option_session(day)
    return int(datetime.combine(day, s.close, tzinfo=IST).timestamp())


def is_in_session_candle(candle_start_ts: int) -> bool:
    """True if a 1-minute candle starting at this epoch second is inside
    that day's option session."""
    dt = datetime.fromtimestamp(candle_start_ts, tz=IST)
    s = option_session(dt.date())
    return s.open <= dt.time() <= s.last_candle_start
