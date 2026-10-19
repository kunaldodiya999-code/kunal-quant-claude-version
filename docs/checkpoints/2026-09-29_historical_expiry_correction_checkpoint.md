# Opening Breakout V2 — Historical Expiry Correction Checkpoint

Date: 2026-09-29

## Status
COMPLETED — historical expiry selection was corrected without modifying locked Resolver V2.

## Problem
The previous required-option audit delegated historical expiry selection to Resolver V2. Because the local instrument inventory is incomplete for older dates, a signal such as 2024-01-24 could incorrectly resolve to a much later expiry that happened to exist locally.

## Correction
Added `backtest/historical_nifty_expiry.py` and switched the research-only required-option audit to use it.

Historical schedule used:
- Through 2025-08-28: NIFTY weekly expiry Thursday.
- From 2025-09-02: NIFTY weekly expiry Tuesday.
- Holiday expiry dates are moved to the previous actual NIFTY session represented in the loaded underlying data.

The exchange's 2025 transition is documented by NSE circular FAOP/68747. The locked `OptionContractResolver V2` was not changed.

## Tests
Added `tests/test_historical_nifty_expiry.py` covering:
- 2024 Thursday expiry
- 2025 Thursday→Tuesday transition
- holiday shift

## Next step
Regenerate the existing acquisition manifest. Do not download from the old manifest.

```powershell
git pull
pytest -q tests/test_historical_nifty_expiry.py tests/test_opening_breakout_v2_required_options.py
python scripts/build_opening_breakout_v2_option_manifest.py --from "2024-01-01 09:15:00" --to "2026-09-22 15:30:00"
```

Then inspect the first manifest entries. A 2024-01-24 requirement should now use the 2024-01-25 NIFTY expiry rather than 2024-11-21.
