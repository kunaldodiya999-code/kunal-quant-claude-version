# Opening Breakout V2 Option Acquisition Manifest Checkpoint

## Status
Completed.

## Purpose
Added a read-only manifest builder for the corrected Opening Breakout V2 BOTH-direction required-option audit.

## Files
- `scripts/build_opening_breakout_v2_option_manifest.py`
- `tests/test_opening_breakout_v2_option_manifest.py`

## Behavior
- Reuses the existing corrected CALL/CE and PUT/PE signal mapping.
- Reuses the existing OptionContractResolver only for required-contract derivation.
- Reuses the existing read-only coverage audit.
- Groups repeated contract-days into unique expiry/strike/type contracts.
- Separates complete dates from missing dates.
- Records unregistered dates separately.
- Produces JSON for the later targeted acquisition step.
- Makes no FYERS calls.
- Makes no database changes.
- Does not modify Resolver V2, strategy logic, lifecycle, execution, or existing downloader behavior.

## Next step
Run the manifest builder locally, inspect its summary and JSON, then implement/execute targeted FYERS acquisition only for the missing contract-days.
