"""Historical NIFTY option expiry calendar used for research-only contract selection.

This intentionally does not modify the locked OptionContractResolver V2.  It supplies
the historical exchange expiry date independently because local instrument inventory
may be incomplete for older dates.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Iterable

# NSE NIFTY weekly expiry was Thursday through 2025-08-28.  The revised
# Tuesday schedule starts with the 2025-09-02 expiry.
THURSDAY_LAST_EXPIRY = date(2025, 8, 28)
TUESDAY_FIRST_EXPIRY = date(2025, 9, 2)

# NSE declared 21-Oct-2025 a trading holiday for the normal F&O calendar.
# Muhurat trading was held that day, but the scheduled Tuesday NIFTY expiry
# therefore moved to the previous trading day, 20-Oct-2025. Keep this separate
# from session_dates because a special Muhurat session may still appear there.
NIFTY_FO_HOLIDAYS = {
    date(2025, 4, 10),  # Mahavir Jayanti
    date(2025, 5, 1),   # Maharashtra Day
    date(2025, 10, 21), # Diwali / Laxmi Puja
}


def _next_weekday(start: date, weekday: int) -> date:
    delta = (weekday - start.weekday()) % 7
    return start + timedelta(days=delta)


def historical_nifty_expiry(signal_date: date, session_dates: Iterable[date]) -> date:
    """Return the first historically valid NIFTY expiry on/after signal_date.

    The supplied session dates are used to move a scheduled expiry backward to
    the previous actual NIFTY trading session when the scheduled day was a
    market holiday.
    """
    sessions = set(session_dates)
    if signal_date not in sessions:
        raise ValueError("signal_date must be an actual NIFTY trading session")

    if signal_date <= THURSDAY_LAST_EXPIRY:
        weekday = 3  # Thursday
    else:
        weekday = 1  # Tuesday

    candidate = _next_weekday(signal_date, weekday)

    # A scheduled expiry remains the contract expiry even if the local NIFTY
    # dataset stops before that future date. Only an exchange-declared holiday
    # moves the expiry backward.
    if candidate == signal_date and candidate in NIFTY_FO_HOLIDAYS:
        # A special session can occur on the normal scheduled expiry date.
        # Do not select an expiry before the signal; use the next scheduled
        # expiry available after that session.
        candidate = _next_weekday(candidate + timedelta(days=1), weekday)
        while candidate in NIFTY_FO_HOLIDAYS:
            candidate = _next_weekday(candidate + timedelta(days=1), weekday)
    elif candidate in NIFTY_FO_HOLIDAYS or (
        sessions and candidate <= max(sessions) and candidate not in sessions
    ):
        # Move backward for a declared holiday or for a scheduled expiry that
        # falls inside the supplied dataset but is absent from its sessions.
        # If the scheduled expiry is beyond the dataset boundary, preserve it
        # because it is still the historically valid future contract expiry.
        candidate -= timedelta(days=1)
        while candidate not in sessions:
            candidate -= timedelta(days=1)

    return candidate
