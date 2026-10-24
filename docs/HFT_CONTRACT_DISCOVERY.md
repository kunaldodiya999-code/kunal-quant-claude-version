# HFT 10S Historical Contract Discovery

Status: experimental/research-only.

The HFT layer now discovers historical contracts from FYERS expiry and expired-contract APIs instead of relying on the local instrument table for weekly expiry resolution.

For every historical NIFTY trading day it targets:
- NIFTY index
- actual nearest eligible NIFTY futures contract
- current weekly NIFTY option expiry
- ATM, ATM+50, ATM+100, ATM+150, ATM+200, ATM+250
- CE and PE for each strike

This is 12 option contracts per trading day.

The expiry calendar is intentionally not hard-coded because NIFTY expiry schedules have changed historically. FYERS states that its symbol-master files contain derivative expiry dates and contract metadata. citeturn0search4

FYERS also states that expired option-chain data is not exposed in the normal Options Chain UI, so the historical-data API path is the appropriate discovery/acquisition path. citeturn0search0

The project uses FYERS 5S historical candles as the source and derives complete 10S candles locally.

Historical lot size is not invented. If the expired-contract response does not expose lot-size metadata, the registered instrument keeps lot_size=NULL. The eventual HFT backtest must refuse to size a trade until authoritative historical lot-size metadata is available.

Validation command:
python scripts/build_hft_10s_manifest.py --from 2026-08-21 --to 2026-08-21

Do not bulk-download until the one-day manifest shows:
- 12 option contract rows
- 1 futures row
- 1 index row
- missing_rows == 0

## Manifest gate

After building the manifest, run:

python scripts/validate_hft_manifest.py --manifest data/reports/hft_10s_manifest.csv

The validator requires exactly 12 option rows per trading day, one futures row, and one NIFTY index row. Bulk acquisition should not begin if the validator returns valid=false.

## One-command sample workflow

For a one-day gate:

python scripts/run_hft_10s_sample.py --from 2026-08-21 --to 2026-08-21

That builds and validates the manifest, then performs a downloader dry-run.
After the manifest is valid, use --run to fetch the real FYERS 5S data and derive 10S candles:

python scripts/run_hft_10s_sample.py --from 2026-08-21 --to 2026-08-21 --run

Do not increase the date range until this one-day sample is clean.
