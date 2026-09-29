"""
Date-aware NIFTY lot size (PROPOSAL, pure function, no I/O).

Why: two different hard-coded constants existed in this project (65 in
`diagnose_option_allocation_failures.py`, 25 in canonical
`instruments/contract_specs.py`) and neither is correct across the full
history the brief wants (5-year NIFTY data). NSE revises the NIFTY lot
size periodically under SEBI's minimum-contract-value rule.

Sources -- primary NSE circulars found and read directly where marked
[PRIMARY]; correctly-dated major financial press otherwise. All checked
2026-09-28.

  - [PRIMARY] NSE/FAOP/47854, Circular Ref. 28/2021, 31-Mar-2021:
    NIFTY 75 -> 50. "Contracts with August 2021 Weekly expiry & beyond
    will have revised market lots"; monthly from July 2021. This era
    predates this project's actual data (which starts ~Nov 2024), so the
    exact date has no impact on current results -- included for
    completeness/correctness only.
  - Business Standard, correctly dated 02-Apr-2024: NIFTY 50 -> 25,
    "available for trading from the trade date of April 26, 2024,
    onwards will be with the revised market lot size" (i.e. immediate
    for ALL contract types, not just new listings).
  - Business Standard, correctly dated 19-Oct-2024, reporting the SEBI
    Rs-15-lakh-minimum mandate: NIFTY 25 -> 75, effective for NEW
    contracts from 20-Nov-2024. Existing weekly/monthly contracts
    continued at the OLD lot (25) until their own expiry -- so both lot
    sizes traded simultaneously for roughly the following 1-2 weeks.
    Quarterly/half-yearly transitioned on 26-Dec-2024 (EOD).
  - [PRIMARY] NSE/FAOP/70616, Circular Ref. 176/2025, 03-Oct-2025:
    NIFTY 75 -> 65. Last weekly expiry at the old lot: 23-Dec-2025;
    first weekly expiry at the new lot: 06-Jan-2026. Quarterly/
    half-yearly transitioned 30-Dec-2025 (EOD). Matches the current lot
    size of 65 the user confirmed directly.

IMPORTANT CAVEAT this table does NOT fully capture: each transition
applies to *new* contract listings, while contracts already listed
before the change keep the old lot until their own expiry. That creates
a roughly 1-2 week window around every boundary where BOTH lot sizes are
simultaneously live, depending on which specific contract (by its own
listing date) a trade actually touches -- not just the trade's entry
date. This module answers "what lot size was standard for freshly-listed
NIFTY contracts on this date", which is the right answer for the large
majority of historical trades, but a trade whose entry falls within ~2
weeks of a boundary above should have its actual resolved contract's
lot size cross-checked individually rather than trusted from this table
alone.
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
    LotSizeEra(date(2021, 8, 1), 50, "NSE/FAOP/47854 (28/2021), 31-Mar-2021 [PRIMARY]; predates project data range"),
    LotSizeEra(date(2024, 4, 26), 25, "Reported effective 26-Apr-2024, immediate for all contract types"),
    LotSizeEra(date(2024, 11, 20), 75, "Effective for NEW contracts from 20-Nov-2024; ~1-2wk mixed-lot window follows"),
    LotSizeEra(date(2025, 12, 31), 65, "NSE/FAOP/70616 (176/2025), 03-Oct-2025 [PRIMARY]; user-confirmed current value"),
)

_ERA_STARTS = [era.effective_from for era in _NIFTY_ERAS]

# Boundaries where a ~1-2 week window can have BOTH the old and new lot
# simultaneously live (new listings vs. already-listed contracts still
# running to their own expiry). See module docstring.
MIXED_LOT_WINDOWS: tuple[tuple[date, date], ...] = (
    (date(2024, 11, 20), date(2024, 12, 26)),
)


def nifty_lot_size(trade_date: date) -> int:
    """Lot size standard for FRESHLY-LISTED NIFTY contracts on
    `trade_date` (the historical trade date, not today's date). See the
    module docstring's caveat for trades near a transition boundary."""

    if trade_date < _ERA_STARTS[0]:
        raise ValueError(
            f"No lot-size era covers {trade_date}; earliest covered date "
            f"is {_ERA_STARTS[0]}. Extend _NIFTY_ERAS before using dates "
            "this old."
        )
    idx = bisect_right(_ERA_STARTS, trade_date) - 1
    return _NIFTY_ERAS[idx].lot_size


def in_mixed_lot_window(trade_date: date) -> bool:
    """True if `trade_date` falls in a window where relying on
    nifty_lot_size() alone is risky -- the actual resolved contract's lot
    size should be cross-checked individually instead."""

    return any(start <= trade_date <= end for start, end in MIXED_LOT_WINDOWS)


def lot_size_for(underlying: str, trade_date: date) -> int:
    underlying = underlying.upper()
    if underlying == "NIFTY":
        return nifty_lot_size(trade_date)
    raise NotImplementedError(
        f"No verified historical lot-size table for {underlying}. "
        "Confirmed sources only cover NIFTY -- add a table (with sources) "
        "before trading this underlying historically."
    )
