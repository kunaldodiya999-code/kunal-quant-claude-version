"""    python3 proposals/test_session_calendar.py   (no repo needed)"""
import sys
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from session_calendar import IST, is_in_session_candle, option_session, session_close_timestamp  # noqa: E402


def t(y, m, d, hh, mm):
    return int(datetime(y, m, d, hh, mm, tzinfo=IST).timestamp())


fails = []


def check(label, ok):
    print(f"[{'PASS' if ok else 'FAIL'}] {label}")
    if not ok:
        fails.append(label)


check("2024-11-28: 375 candles, last start 15:29", option_session(date(2024, 11, 28)).expected_1m_candles == 375)
check("2026-07-31 (Fri, before change): 375 candles", option_session(date(2026, 7, 31)).expected_1m_candles == 375)
check("2026-08-03 (first extended day): 385 candles", option_session(date(2026, 8, 3)).expected_1m_candles == 385)
check("2026-09-16: 385 candles (matches the 385/day in your DB)", option_session(date(2026, 9, 16)).expected_1m_candles == 385)
check("before change: 15:29 in session, 15:30 not", is_in_session_candle(t(2026, 7, 31, 15, 29)) and not is_in_session_candle(t(2026, 7, 31, 15, 30)))
check("after change: 15:30 and 15:39 in session, 15:40 not",
      is_in_session_candle(t(2026, 9, 16, 15, 30)) and is_in_session_candle(t(2026, 9, 16, 15, 39))
      and not is_in_session_candle(t(2026, 9, 16, 15, 40)))
check("09:14 never in session, 09:15 always", not is_in_session_candle(t(2026, 9, 16, 9, 14)) and is_in_session_candle(t(2026, 9, 16, 9, 15)))
check("close timestamps: 15:30 before, 15:40 after",
      session_close_timestamp(date(2026, 7, 31)) == t(2026, 7, 31, 15, 30)
      and session_close_timestamp(date(2026, 9, 16)) == t(2026, 9, 16, 15, 40))
print()
raise SystemExit(1 if fails else print("All session-calendar checks passed.") or 0)
