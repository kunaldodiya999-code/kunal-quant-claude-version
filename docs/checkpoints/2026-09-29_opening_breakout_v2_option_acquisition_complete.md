# Checkpoint — Opening Breakout V2 Historical Option Acquisition Complete

Date: 2026-09-29

## Status

Phase: Opening Breakout V2 historical option-data acquisition

Status: **COMPLETE / VERIFIED**

## Verified pipeline

1. Opening Breakout V2 required-option manifest generated.
2. Historical NIFTY expiry calendar corrected for the 21-Oct-2025 Muhurat session.
3. FYERS historical contract discovery identified exact symbols.
4. Targeted acquisition downloaded only required contract-days.
5. Existing HistoricalDownloader was reused.
6. No Resolver V2 changes were required.
7. Special-session coverage was made session-aware.
8. Final manifest reports all required contract-days complete.

## Final sample coverage

- Required contract-days: 12
- Unique contracts: 12
- Complete: 12
- Partial: 0
- Empty: 0
- Unregistered: 0
- Missing contract-days: 0
- Candles received: 4,186
- Candles inserted: 4,186
- Duplicate candles: 0
- Failed chunks: 0

## Special session

21-Oct-2025 was handled as the Muhurat session. The required
NSE:NIFTY25OCT25900PE contract returned 61 one-minute candles. Coverage
validation now compares required option candles with the actual underlying
session length instead of blindly requiring 375 candles for every date.

## Files added/changed in this milestone

- scripts/acquire_opening_breakout_v2_options.py
- tests/test_opening_breakout_v2_option_acquisition.py
- docs/OPENING_BREAKOUT_V2_OPTION_ACQUISITION.md
- scripts/audit_opening_breakout_v2_required_options.py
- scripts/build_opening_breakout_v2_option_manifest.py
- tests/test_opening_breakout_v2_required_options.py
- tests/test_historical_nifty_expiry.py
- backtest/historical_nifty_expiry.py

## Next stage

The next task is to connect the verified real option candles to the Opening
Breakout V2 signal/fill integration and perform an explicit no-lookahead review
before any full historical performance run.

Do not modify locked Resolver V2, KTMI, lifecycle, or strategy trigger
definitions while doing that work.
