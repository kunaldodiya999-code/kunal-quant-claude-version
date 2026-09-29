"""
Date-aware NIFTY lot size (PROPOSAL, pure function, no I/O).

Why: `proposals/diagnose_option_allocation_failures.py` hard-codes
LOT_SIZE = 65, and the canonical repo's `instruments/contract_specs.py`
hard-codes lot_size=25 -- two different constants in two places, and
NEITHER is correct across the full history the brief wants (5-year NIFTY
1-minute data, and the earlier commits show historical option data going
back to Nov 2024). NSE revises the NIFTY lot size periodically per SEBI's
minimum-contract-value rule. 65 is only correct for trades from
2025-12-31 onward; 25 is only correct for 2024-04-26 through 2025-01-01.
Applying either constant to the rest of the history misstates quantity,
capital deployed, and P&L for every historical trade outside its window.

Sources (cross-checked across NSE circular summaries and 3+ independent
broker/community posts, listed oldest to newest; verify the exact
circular numbers before relying on this for the 5-year run):
  - 2021-04-30: NSE/F&O/028/2021 -> 50
  - 2024-04-26: NSE circular (FAOP61415-referenced) -> 25
  - 2025-01-02: reported lot size increase -> 75 (source: community
    report; the exact circular was not found in this search pass --
    verify before relying on it)
  - 2025-12-31: NSE circular dated 2025-10-03, effective for Jan-2026-
    onward expiries -> 65 (implemented from 2025-10-28 for new contracts;
    final old-lot contract expired 2025-12-30)

BANK NIFTY / SENSEX are NOT included: sources only confirm Bank Nifty was
15 as of mid-2023 and 30 as of late 2025, with no confirmed date for the
transition between those two points, and Sensex lot-size history wasn't
searched at all. Calling lot_size_for() with those underlyings raises
NotImplementedError rather than guess. The current codebase only trades
NIFTY, so this doesn't block anything today.
"""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class LotSizeEra:
    effective_from: date
    lot_size: int
    note: str


# Sorted ascending by effective_from. The era in effect on a given date is
# the last one whose effective_from is <= that date.
_NIFTY_ERAS: tuple[LotSizeEra, ...] = (
    LotSizeEra(date(2021, 4, 30), 50, "NSE/F&O/028/2021"),
    LotSizeEra(date(2024, 4, 26), 25, "NSE circular, ~FAOP61415"),
    LotSizeEra(date(2025, 1, 2), 75, "reported increase -- circular not confirmed, verify"),
    LotSizeEra(date(2025, 12, 31), 65, "NSE circular dated 2025-10-03"),
)

_ERA_STARTS = [era.effective_from for era in _NIFTY_ERAS]


def nifty_lot_size(trade_date: date) -> int:
    """Lot size in effect on `trade_date` (the date a contract's quantity
    is set at entry, i.e. the historical trade date -- NOT today's date)."""

    if trade_date < _ERA_STARTS[0]:
        raise ValueError(
            f"No lot-size era covers {trade_date}; earliest covered date "
            f"is {_ERA_STARTS[0]}. Extend _NIFTY_ERAS before using dates "
            "this old."
        )
    idx = bisect_right(_ERA_STARTS, trade_date) - 1
    return _NIFTY_ERAS[idx].lot_size


def lot_size_for(underlying: str, trade_date: date) -> int:
    underlying = underlying.upper()
    if underlying == "NIFTY":
        return nifty_lot_size(trade_date)
    raise NotImplementedError(
        f"No verified historical lot-size table for {underlying}. "
        "Confirmed sources only cover NIFTY -- add a table (with sources) "
        "before trading this underlying historically."
    )
