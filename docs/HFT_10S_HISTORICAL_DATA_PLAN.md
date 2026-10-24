
# Kunal Quant — 10-Second HFT Historical Data Plan

## Status

Designed — not yet bulk downloaded.

This plan is intentionally isolated from the locked KTMI V6, KTMI Universal V1 FINAL,
Strategy A/B triggers, Option Trade Management V1, Option Contract Resolver V2, and
the existing lifecycle/accounting modules.

## User-approved 10-second option universe

For every historical NIFTY option-expiry period, the HFT option universe is:

- CE: ATM, ATM+50, ATM+100, ATM+150, ATM+200, ATM+250
- PE: ATM, ATM+50, ATM+100, ATM+150, ATM+200, ATM+250

Therefore the instantaneous target universe is:

6 CE + 6 PE = 12 option contracts.

The same strike ladder is used for PE exactly as specified by the user.

## Important implementation rule

The downloader must not select one fixed ATM strike for an entire expiry.

ATM moves as NIFTY moves. The historical planner therefore uses the NIFTY
underlying path to build the required strike envelope for each expiry/session.

For each historical trading period:

1. Read the canonical NIFTY 1-minute data.
2. Determine the 50-point ATM strike for each relevant underlying observation.
3. Generate the six approved strike levels:
   ATM + each value in (0, 50, 100, 150, 200, 250).
4. Apply those strikes independently to CE and PE.
5. Resolve the actual FYERS contract symbol for the applicable historical expiry.
6. Deduplicate contracts across the period.
7. Download only those option contracts at 10-second resolution.

This avoids downloading the entire historical option chain while preserving
the contracts that the HFT strategy could actually need.

## NIFTY and NIFTY Futures

The HFT dataset also requires:

- NIFTY index at 10 seconds.
- NIFTY futures at 10 seconds.

Futures must be stored using their actual historical contracts. We will not
silently create a continuous/synthetic futures series and present it as broker
data.

A later HFT research layer can construct a continuous analytical series if
needed, but the raw historical contract data remains the source of truth.

## Maximum available history

The acquisition target is the maximum genuine historical 10-second data that
FYERS will return, not a hard-coded five-year window.

FYERS currently documents 10-second chart intervals. Its current public notice
states that API V3 intraday historical data is available up to five years, while
daily data can extend to 25 years. The public material does not establish a
separate retention guarantee specifically for 10-second expired options/futures.

Therefore the acquisition workflow must measure the actual 10-second retention
through FYERS before bulk downloading.

### Required capability probe

The probe must test:

1. NIFTY index at 10 seconds.
2. A historical NIFTY futures contract at 10 seconds.
3. A historical NIFTY CE at 10 seconds.
4. A historical NIFTY PE at 10 seconds.
5. Expired-contract access through the FYERS F&O historical endpoint.
6. The oldest date that actually returns non-empty 10-second candles.
7. Request-window behavior and returned candle counts.

The result becomes a machine-readable acquisition boundary. We do not assume
that the 1-minute retention limit is identical to the 10-second retention limit.

## Storage

The existing canonical candles table already stores resolution and source,
so 10-second candles can coexist with the existing 1-minute data without
changing the candle model.

10-second HFT records will use:

- resolution = "10S"
- source = "FYERS_HFT_HISTORY"

The existing 1-minute FYERS historical dataset remains untouched.

Raw FYERS responses remain under the existing raw historical-data hierarchy.

## Download sequence

The bulk process will be:

1. Authenticate through the existing FYERS client.
2. Run the 10-second capability probe.
3. Determine the maximum valid historical date range.
4. Ensure the required historical NIFTY 1-minute base exists.
5. Build the ATM/strike contract manifest.
6. Resolve/verify historical option contracts.
7. Resolve/verify historical NIFTY futures contracts.
8. Download NIFTY 10-second candles.
9. Download required NIFTY futures 10-second candles.
10. Download only the 12-contract-equivalent targeted option universe.
11. Resume completed chunks instead of duplicating downloads.
12. Validate coverage, gaps, duplicates and unexpected contracts.
13. Produce a final acquisition manifest before HFT strategy development.

## No-lookahead requirement

The contract-selection manifest is a data-coverage manifest, not a trading
signal. It may use the complete historical underlying path to ensure that all
contracts that fall inside the approved ATM ladder are downloaded.

The eventual HFT backtest must still use only information available at each
historical timestamp when deciding what contract to trade or monitor.

## HFT strategy isolation

The 10-second dataset does not activate the HFT strategy.

The future strategy will be independently switchable in:

- Backtest
- Paper
- Live

The existing strategies continue using their existing data paths.

## Current FYERS API observations

FYERS currently documents 10-second chart intervals. FYERS also states that
historical candle timestamps represent the start of the candle interval, and
complete candle data is available only after the interval has completed.

These timing rules must be reflected in the future 10-second backtest engine.

## Bulk-download gate

Do not start the full historical 10-second download until the capability
probe has produced a successful report.

The first executable milestone is therefore:

probe -> verify -> manifest -> small sample -> bulk acquisition

not:

blind bulk download.
