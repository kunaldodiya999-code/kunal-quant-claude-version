# NIFTY Option Bulk Acquisition and Repair

## Controlled acquisition of empty contracts

The original empty-contract downloader remains available:

```powershell
python scripts\acquire_nifty_option_candles.py
```

It defaults to five empty contracts per run.

## Repair empty and partially populated contracts

The new repair runner selects NIFTY CE/PE contracts with fewer than 3,000 stored
1-minute candles, including contracts that already contain some candles. It
uses the existing `HistoricalDownloader`, stores broker candles in the
existing SQLite schema, and checkpoints every processed contract to CSV.

**Start with a dry run** (no API calls and no DB writes):

```powershell
python scripts\repair_nifty_option_candles.py
```

Then run a small controlled batch after reviewing the candidate list:

```powershell
python scripts\repair_nifty_option_candles.py --execute --limit 2
```

Useful controls:

```powershell
# Target selected symbols only
python scripts\repair_nifty_option_candles.py --symbols NSE:NIFTY24N2123250CE NSE:NIFTY24N2123250PE

# Adjust threshold, history window, chunk size, pause, and checkpoint
python scripts\repair_nifty_option_candles.py --min-candles 5000 --days-before 90 --chunk-days 15 --pause 1.5 --execute --limit 5
```

Defaults:
- 3,000-candle threshold
- 5 contracts per run
- 90 calendar days ending at expiry
- 15-day request chunks for repair
- 1.2-second pause after each chunk
- CSV checkpoint after each contract

The shorter chunks are deliberate: they avoid reusing an old 90-day job checkpoint
when repairing a contract that is already partially populated. Existing candles
are retained; duplicate timestamps are ignored by the existing database
constraint. No forward-fill or synthetic prices are generated.

## Research safety

A successful download is not proof that a contract is complete. After acquisition,
rerun the gap and option-chain completeness audits and inspect first/last timestamps,
paired CE/PE coverage, and OI quality before using a period for backtesting.
