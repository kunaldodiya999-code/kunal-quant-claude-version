# Dhan rolling options: one-year acquisition plan

## Purpose

Start KunalQuant's research dataset with one year of NIFTY rolling options at 5-minute resolution. The downloader is resumable and defaults to plan-only mode.

Official Dhan docs describe `/charts/rollingoption` as rolling ATM-relative historical data, up to 30 calendar days per request, up to five years, with OHLC, IV, volume, OI, strike, and spot. The endpoint does **not** provide historical Delta/Gamma/Theta/Vega fields in its documented response.

## Planned first pass

- Underlying: NIFTY, security ID 13
- Period: last 365 calendar days, ending today-exclusive (through yesterday)
- Interval: 5 minutes
- Expiry series: WEEK, expiryCode 1 (near rolling expiry per the endpoint-specific support mapping already investigated)
- Relative strikes: ATM-10 through ATM+10 (21 labels)
- Sides: CALL and PUT
- Chunks: 30 calendar days maximum; end date exclusive
- Requests: approximately 13 chunks x 21 labels x 2 sides = 546 requests (actual chunk count is printed by the planner; calendar span controls it)
- Delay: 0.30 seconds between requests by default, below the documented 5 data requests/second limit
- Persistence: raw response per request plus a JSON manifest under ignored `data/raw/`
- Resume: rerunning the exact same command skips completed response files and continues after interruption/token expiry
- Safety: no orders and no database writes

The full one-year run is not automatically started. The script requires `--execute`; without it, it only prints the plan and writes nothing.

## Commands

Plan only:

```powershell
python scripts/download_dhan_rolling_history.py --interval 5
```

Run one small 2-day smoke test first:

```powershell
python scripts/download_dhan_rolling_history.py --from-date 2026-10-08 --to-date 2026-10-10 --interval 5 --execute
```

Then run the offline normalizer/quality audit on the smoke-test run (this also writes a CSV of normalized rows):

```powershell
python scripts/audit_dhan_rolling_history.py --run-dir data/raw/dhan_rolling_history/nifty_2026-10-08_2026-10-10_5m_WEEK_code1
```

Review `quality_report.json` and `normalized_rolling_history.csv` before starting the year. If the smoke test looks structurally sound, start the year:

```powershell
python scripts/download_dhan_rolling_history.py --interval 5 --execute
```

If the token expires or the run is interrupted, renew/update the local token in `.env` without sharing it, then rerun the exact same command. Saved response files are revalidated before being skipped. Valid raw response files left behind before a manifest checkpoint are recovered without re-fetching.

## Important interpretation limits

1. These are ATM-relative rolling series, not fixed-expiry contract histories. Each observation includes the actual strike, so keep that field. The exact historical expiry identity is not returned by the inspected response; do not claim a row is a specific fixed-expiry contract without independent verification.
2. Dhan's endpoint provides IV and OI but not documented historical Greeks. If KunalQuant needs GEX/DEX, Greeks must be computed from a clearly specified model and inputs or sourced from another verified data source. Model-derived Greeks are not broker-provided historical Greeks.
3. ATM-relative requests overlap in actual strikes. Preserve the raw requests and provenance; deduplicate only in a separate derived layer with explicit conflict rules.
4. A completed API request is not proof of a complete session. After acquisition, run session, timestamp, OHLC, array-length, IV/OI coverage, and overlap consistency audits before using the dataset for backtesting.
5. One year is a sensible initial milestone. Extend to five years only after the smoke test and one-year quality audit pass.

## Official reference

Dhan expired-options API documentation: https://dhanhq.co/docs/v2/expired-options-data/
