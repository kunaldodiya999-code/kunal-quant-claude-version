# Checkpoint — Opening Breakout V2 Required Option Coverage Audit

Date: 2026-09-29

## Status

**Completed:** research-only required-option coverage audit.

## What was added

- `scripts/audit_opening_breakout_v2_required_options.py`
- `tests/test_opening_breakout_v2_required_options.py`

## Purpose

The audit converts real stored NIFTY 1-minute sessions into the exact option
contract-days required by the current Opening Breakout V2 signal definition.

For each qualifying signal it:

1. Uses the signal-time NIFTY close, matching the existing option integration.
2. Applies the existing Option Contract Resolver V2.
3. Identifies the exact expiry, strike and CE/PE contract.
4. Checks stored `FYERS_FNO_HISTORY` 1-minute coverage for that signal date.
5. Classifies each required contract-day as:
   - COMPLETE
   - PARTIAL
   - EMPTY
   - UNREGISTERED

## Important boundaries

- No FYERS API calls.
- No database writes.
- No changes to Resolver V2.
- No changes to Opening Breakout V2 strategy logic.
- No option-chain-wide download.
- This is an acquisition-planning/audit layer only.

## Next stage

Run the audit against the locally stored NIFTY history. Then use its exact
missing/partial contract-days as the input to targeted FYERS acquisition.

Only after the required option coverage is sufficient should the multi-day
Opening Breakout V2 economic backtest be run.

## Verification

The dedicated audit test covers COMPLETE, PARTIAL, EMPTY and UNREGISTERED
classification plus LONG→CE and SHORT→PE mapping.
