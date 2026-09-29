"""    python3 proposals/test_nifty_lot_size.py   (no repo needed)"""
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from nifty_lot_size import in_mixed_lot_window, lot_size_for, nifty_lot_size  # noqa: E402


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


check("2021-08-01 (first day of the earliest covered era) -> 50", nifty_lot_size(date(2021, 8, 1)) == 50)
check("2024-04-25 (day before the cut to 25) -> 50", nifty_lot_size(date(2024, 4, 25)) == 50)
check("2024-04-26 (first day of 25) -> 25", nifty_lot_size(date(2024, 4, 26)) == 25)
check("2024-11-15 (Nov-2024 option data cluster, before the Nov-20 change) -> 25",
      nifty_lot_size(date(2024, 11, 15)) == 25)
check("2024-11-19 (day before the increase) -> 25", nifty_lot_size(date(2024, 11, 19)) == 25)
check("2024-11-20 (new contracts start at 75) -> 75", nifty_lot_size(date(2024, 11, 20)) == 75)
check("2025-01-02 -> 75 (well inside the 75 era)", nifty_lot_size(date(2025, 1, 2)) == 75)
check("2025-12-30 (last day of 75) -> 75", nifty_lot_size(date(2025, 12, 30)) == 75)
check("2025-12-31 (new 65 lot, user-confirmed current value) -> 65", nifty_lot_size(date(2025, 12, 31)) == 65)
check("2026-09-16 (matches the bounded sample) -> 65", nifty_lot_size(date(2026, 9, 16)) == 65)
check("date before the covered range raises instead of guessing",
      _raises(lambda: nifty_lot_size(date(2020, 1, 1))))
check("lot_size_for('nifty', ...) is case-insensitive and matches nifty_lot_size",
      lot_size_for("nifty", date(2026, 1, 1)) == nifty_lot_size(date(2026, 1, 1)))
check("lot_size_for('BANKNIFTY', ...) raises instead of guessing an unverified table",
      _raises(lambda: lot_size_for("BANKNIFTY", date(2026, 1, 1))))

check("2024-11-20 to 2024-12-26 flagged as a mixed-lot window", in_mixed_lot_window(date(2024, 12, 1)))
check("2024-11-19 (just before) NOT flagged", not in_mixed_lot_window(date(2024, 11, 19)))
check("2024-12-27 (just after) NOT flagged", not in_mixed_lot_window(date(2024, 12, 27)))
check("2026-09-16 (bounded sample, far from any boundary) NOT flagged",
      not in_mixed_lot_window(date(2026, 9, 16)))

print()
if fails:
    print(f"{len(fails)} FAILED: {fails}")
    raise SystemExit(1)
print("All lot-size checks passed.")
