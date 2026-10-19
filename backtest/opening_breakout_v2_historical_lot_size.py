"""Historical NIFTY lot-size policy for Opening Breakout V2 acquisition.

This module is intentionally acquisition-specific. It does not alter resolver,
strategy, execution, or live instrument metadata.

For the Jan-Oct 2025 Opening Breakout V2 historical sample, required contracts
were already existing NIFTY contracts before the Oct 2025 lot-size revision.
NSE retained the previous 75-lot size for existing weekly/monthly contracts
with expiry through 2025-12-30. Contracts introduced under the revised regime
use 65.

The helper requires the contract's historical context explicitly so a future
caller cannot silently inherit the current database lot size.
"""

from __future__ import annotations

from datetime import date

NIFTY_OLD_LOT_SIZE = 75
NIFTY_NEW_LOT_SIZE = 65

# NSE revision effective after the 2025-10-28 trading session.
NIFTY_REVISION_DATE = date(2025, 10, 28)
NIFTY_OLD_CONTRACT_CUTOFF = date(2025, 12, 30)


def historical_nifty_lot_size(
    *,
    signal_date: date,
    expiry_date: date,
) -> int:
    """Return the historically applicable lot size for a V2-required contract.

    V2 signals in this acquisition workflow occur no later than 2025-10-28.
    Those contracts were already part of the pre-revision contract set, so
    their 75-lot size remains applicable even where expiry extends beyond the
    revision date, up to the NSE transition cutoff.

    For contracts first selected on/after the revision date, the revised
    65-lot regime applies.
    """
    if signal_date < NIFTY_REVISION_DATE:
        return NIFTY_OLD_LOT_SIZE

    if signal_date == NIFTY_REVISION_DATE and expiry_date <= NIFTY_OLD_CONTRACT_CUTOFF:
        return NIFTY_OLD_LOT_SIZE

    return NIFTY_NEW_LOT_SIZE
