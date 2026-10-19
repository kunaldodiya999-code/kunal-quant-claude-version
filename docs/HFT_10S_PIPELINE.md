# Kunal Quant — HFT 10-Second Historical Data Pipeline

Status: IMPLEMENTED DATA LAYER — bulk acquisition remains explicitly gated.

## Scope
- NIFTY index at 10 seconds.
- Actual NIFTY futures contracts at 10 seconds.
- Only the requested option ladder: ATM, ATM+50, ATM+100, ATM+150, ATM+200, ATM+250 for both CE and PE.
- No full option-chain download.
- Dynamic ATM is derived from the canonical NIFTY 1-minute history.
- 10-second strategy remains disabled by default.

## Pipeline
1. Empirically probe FYERS 10s availability.
2. Build a dynamic manifest from canonical 1m NIFTY candles.
3. Resolve real registered FYERS contracts from the instrument master.
4. Download only symbol/date pairs present in the manifest.
5. Store raw broker responses separately under data/raw/historical_hft_10s.
6. Store canonical candles with resolution="10S" and source="FYERS_HFT_HISTORY".
7. Validate every requested symbol/date pair.

## Important semantics
FYERS states that seconds intervals including 10s are supported, candle timestamps mark interval start, and complete candle data is available only after the interval completes. The manifest is therefore a coverage artifact, not a trading signal or permission to look ahead.

## Commands
```powershell
python scripts/discover_fyers_10s_retention.py
python scripts/build_hft_10s_manifest.py --from 2026-08-21 --to 2026-08-21
python scripts/download_hft_10s_data.py --manifest data/reports/hft_10s_manifest.csv
python scripts/download_hft_10s_data.py --manifest data/reports/hft_10s_manifest.csv --run --limit 5
python scripts/validate_hft_10s_coverage.py --manifest data/reports/hft_10s_manifest.csv
```

The downloader is dry-run by default. Bulk acquisition requires explicit `--run`.

## Retention
FYERS publicly describes intraday historical data as available up to 5 years, while its public documentation does not establish a separate universal retention guarantee specifically for 10-second expired options/futures. Therefore the project records empirical coverage instead of assuming five years. citeturn0search4turn0search0

## Backtest safety
- Do not use a future ATM state to select a contract.
- ATM/contract selection must use only information available at the relevant underlying timestamp.
- FYERS candle timestamps are interval starts.
- The completion of a 10-second candle is required before its close can be used.
