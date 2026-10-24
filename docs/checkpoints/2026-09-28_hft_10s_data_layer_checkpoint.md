# HFT 10s Data Layer Checkpoint — 2026-09-28

Status: DATA PIPELINE IMPLEMENTED; BULK ACQUISITION NOT STARTED.

## Confirmed
- FYERS 10s capability probe succeeded for NIFTY index, NIFTY futures, and NIFTY option on 2026-08-21.
- Canonical HFT configuration uses resolution 10 and source FYERS_HFT_HISTORY.
- Requested option ladder is exactly ATM through ATM+250 in 50-point steps for both CE and PE.
- NIFTY 1m history is the source for dynamic historical ATM states.
- Actual registered NIFTY futures contracts are selected by trade date.
- Raw 10s broker responses are stored separately from canonical candles.
- Downloader is dry-run by default; bulk acquisition requires --run.
- Coverage validator checks every manifest symbol/date pair.

## Files
- config/hft_data.py
- docs/HFT_10S_HISTORICAL_DATA_PLAN.md
- docs/HFT_10S_PIPELINE.md
- scripts/probe_fyers_10s_capability.py
- scripts/discover_fyers_10s_retention.py
- scripts/build_hft_10s_manifest.py
- scripts/download_hft_10s_data.py
- scripts/validate_hft_10s_coverage.py
- tests/test_hft_10s_layer.py

## Safety
No locked strategy, option resolver, lifecycle, accounting, or 1m/3m/5m production logic was changed.

## Next local sequence
1. git pull
2. run retention discovery
3. build a small manifest
4. dry-run downloader
5. acquire a small explicit sample with --run --limit
6. validate
7. inspect coverage/results
8. only then approve bulk acquisition
