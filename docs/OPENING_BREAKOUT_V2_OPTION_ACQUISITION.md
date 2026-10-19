# Opening Breakout V2 — Targeted Option Acquisition

## Status

Experimental/research acquisition layer. It is not part of the locked resolver,
signal engine, lifecycle, or execution modules.

## Data flow

```
Opening Breakout V2 option manifest
        +
FYERS historical contract discovery
        |
        v
exact contract-day plan
        |
        v
existing HistoricalDownloader
        |
        v
FYERS expired_history, 1-minute
        |
        v
SQLite candles / FYERS_FNO_HISTORY
```

## Scope

The acquisition script consumes:

- `opening_breakout_v2_option_acquisition_manifest.json`
- `opening_breakout_v2_fyers_contract_discovery.json`

It downloads only `missing_dates` from the manifest. It does not derive a
new contract, call the locked Option Contract Resolver V2, rebuild Opening
Breakout signals, or download a continuous date range between the first and
last signal date.

Instrument registration reuses the existing targeted NIFTY option registration
helper, while candle downloading remains exclusively delegated to
`HistoricalDownloader`.

## Safety properties

- Exact discovered FYERS symbol is required.
- Missing discovery fails closed; no symbol is fabricated.
- Complete contract-days are skipped.
- Each missing trading date is requested separately.
- FYERS mode is `expired`.
- Candle resolution is `1`.
- Existing download-job/duplicate handling remains in force.
- `--dry-run` allows inspection before any FYERS or SQLite writes.

## First execution

Run the dry run first:

```powershell
python scripts/acquire_opening_breakout_v2_options.py --dry-run
```

For the current corrected October 2025 manifest, the expected plan is 12
contract-days. After reviewing it, run:

```powershell
python scripts/acquire_opening_breakout_v2_options.py
```

Then rebuild the read-only manifest to verify that the downloaded days are
now complete.
