# Opening Breakout V2 — Real Data Stage 1 Checkpoint

## Status

Experimental/research backtest pipeline.

## Completed in this stage

- Updated the bounded real-data sample runner so OH/OL filters are disabled for the integration smoke test.
- Added setup-candle diagnostics and signal diagnostics.
- Preserved the V2 strategy engine, Resolver V2, historical fill engine, and sizing logic.
- Added a read-only historical database coverage audit:
  - NIFTY 1-minute coverage
  - FYERS NIFTY option instrument inventory
  - option candle population by contract and expiry
  - candle sources/resolutions
  - empty option contracts

## Next gate

Run the August 21 real-data sample and the coverage audit locally.

The sample is only an integration validation. It is not a performance result and does not add lifecycle, broker costs, or portfolio accounting.

## Commands

    git pull origin main

    python scripts/run_opening_breakout_v2_real_sample.py --from "2026-08-21 09:15:00" --to "2026-08-21 15:30:00"

    python scripts/audit_historical_data_coverage.py

After these results are reviewed, build the multi-day backtest runner against the existing modules and only download missing option data required by resolved contracts.
