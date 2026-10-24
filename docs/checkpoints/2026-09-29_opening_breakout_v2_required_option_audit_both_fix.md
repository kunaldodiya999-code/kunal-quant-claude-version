# Opening Breakout V2 Required-Option Audit — BOTH Direction Fix

Date: 2026-09-29

## Completed

Corrected `scripts/audit_opening_breakout_v2_required_options.py` so `--instrument BOTH` evaluates the two option directions independently:

- CALL / LONG -> `CANDLE_HIGH` -> CE
- PUT / SHORT -> `CANDLE_LOW` -> PE

The audit remains read-only:
- no FYERS calls
- no database writes
- existing Option Contract Resolver V2 unchanged
- existing Opening Breakout V2 strategy logic unchanged

Added a dedicated unit test for the direction-to-trigger mapping.

## Why

The previous BOTH audit selected `CANDLE_HIGH` for both CALL and PUT. Since the Opening Breakout V2 signal engine treats `CANDLE_HIGH` as a LONG trigger and `CANDLE_LOW` as a SHORT trigger, that could omit the PE/PUT side from the required-contract audit.

## Current status

The previously supplied audit result is not yet considered the final CE+PE coverage requirement because it was generated before this correction.

## Next step

Run the corrected audit over the same historical range and verify the resulting CE and PE contract-day counts before any targeted FYERS acquisition.
