"""    python3 proposals/test_nifty_lot_size.py   (no repo needed)"""
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from nifty_lot_size import lot_size_for, nifty_lot_size  # noqa: E402

def _raises(fn):
    try:
        fn()
        return False
    except (ValueError, NotImplementedError):
        return True

fails = []


def check(label, ok):
    print(f"[{'PASS' if ok else 'FAIL'}] {label}")
    if not ok:
        fails.append(label)


# The actual bug this fixes: the bounded sample (Aug-Sep 2026) correctly
# uses 65 under both the hard-coded constant AND this table -- so the bug
# is invisible in that sample. It only bites once history reaches further
# back, e.g. the Nov 2024 option data cluster found in the coverage
# diagnostic, which the flat 65 constant would silently mis-size.
check("2024-11-15 (in the Nov-2024 option data cluster) -> 25, NOT the hard-coded 65",
      nifty_lot_size(date(2024, 11, 15)) == 25)
check("2024-04-25 (day before the cut to 25) -> 50", nifty_lot_size(date(2024, 4, 25)) == 50)
check("2024-04-26 (first day of 25) -> 25", nifty_lot_size(date(2024, 4, 26)) == 25)
check("2025-01-01 (day before reported increase) -> 25", nifty_lot_size(date(2025, 1, 1)) == 25)
check("2025-01-02 (reported increase) -> 75", nifty_lot_size(date(2025, 1, 2)) == 75)
check("2025-12-30 (last day of 75) -> 75", nifty_lot_size(date(2025, 12, 30)) == 75)
check("2025-12-31 (new 65 lot) -> 65", nifty_lot_size(date(2025, 12, 31)) == 65)
check("2026-09-16 (matches today's bounded sample, and the 65 hard-coded elsewhere) -> 65",
      nifty_lot_size(date(2026, 9, 16)) == 65)
check("date before the covered range raises instead of guessing",
      _raises(lambda: nifty_lot_size(date(2020, 1, 1))))
check("lot_size_for('nifty', ...) is case-insensitive and matches nifty_lot_size",
      lot_size_for("nifty", date(2026, 1, 1)) == nifty_lot_size(date(2026, 1, 1)))
check("lot_size_for('BANKNIFTY', ...) raises instead of guessing an unverified table",
      _raises(lambda: lot_size_for("BANKNIFTY", date(2026, 1, 1))))


print()
if fails:
    print(f"{len(fails)} FAILED: {fails}")
    raise SystemExit(1)
print("All lot-size checks passed.")
