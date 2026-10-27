"""The real money in the FYERS account (owner 27 Oct 2026: "send orders according to the funds we have").

FYERS API v3 ``funds()`` returns ``fund_limit``: rows with ``id`` / ``title`` and ``equityAmount``; the row
"Available Balance" (id 10) is what a new F&O buy can use. Read-only, cached for a few seconds (no order calls).
"""

from __future__ import annotations

import time
from typing import Any, Callable

AVAILABLE_ID = 10
AVAILABLE_TITLE = "available balance"


def available_balance(response: Any) -> float:
    """Rupees free for new trades from a FYERS funds() response; raises ValueError when it cannot be read."""
    if not isinstance(response, dict) or response.get("s") not in ("ok", None):
        raise ValueError(f"FYERS funds not available: {response!r}"[:200])
    for row in response.get("fund_limit") or []:
        if row.get("id") == AVAILABLE_ID or str(row.get("title", "")).strip().lower() == AVAILABLE_TITLE:
            return float(row.get("equityAmount") or 0.0)
    raise ValueError("FYERS funds: no 'Available Balance' row")


def funds_provider(model: Any, *, max_age: float = 15.0, clock: Callable[[], float] = time.monotonic,
                   log: Callable[[str], Any] = print) -> Callable[[], float]:
    """A function giving the current available balance; asks FYERS at most every ``max_age`` seconds."""
    cache: dict = {}

    def current() -> float:
        now = clock()
        if "at" in cache and now - cache["at"] < max_age:
            return cache["value"]
        value = available_balance(model.funds())        # an error here = no entry (session catches it)
        if cache.get("value") != value:
            log(f"FYERS available funds: Rs {value:,.2f}")
        cache.update(at=now, value=value)
        return value
    return current


__all__ = ["available_balance", "funds_provider"]
