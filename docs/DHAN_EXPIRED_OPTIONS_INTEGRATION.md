# Dhan Expired Options Integration — Stage 1

## Scope

This stage adds a read-only client for DhanHQ's `POST /charts/rollingoption`
endpoint and a one-request NIFTY smoke test. It does not place orders, alter
the SQLite schema, or import data into the production database.

Official endpoint documentation:
https://dhanhq.co/docs/v2/expired-options-data/

## Credentials

Add the following to the local, ignored `.env` file (never commit it):

```dotenv
DHAN_ACCESS_TOKEN=your_access_token_here
```

For `/charts/rollingoption`, the endpoint-specific expiry mapping is `1=near expiry`, `2=next expiry`, `3=far expiry`; code `0` currently returns DH-905. The rolling-options example documents the `access-token` header. A valid
token alone is not sufficient if Dhan Data APIs are not subscribed/enabled.
Dhan documents a 24-hour lifetime for web-generated access tokens.

## Smoke test

Use a known completed market date and a one-day interval. The end date is
exclusive. Example:

```powershell
python scripts/test_dhan_expired_options.py --from-date 2026-10-06 --to-date 2026-10-07 --expiry-flag WEEK --expiry-code 1 --strike ATM --option-type CALL
```

The script performs one request, prints row counts and response fields, and
stores the full response under the ignored `data/raw/dhan_smoke/` directory.
It does not write to `kunal_quant.db`.

## Important data-model constraint

Dhan's endpoint is **rolling strike-relative data** (ATM, ATM+1, ATM-1, etc.),
not a request for one fixed historical option contract. The actual strike can
change over time and is returned in the response arrays. Any future importer
must align timestamp, strike, option side, expiry selection, OHLC, IV, volume,
OI, and spot for each row before writing canonical candles. Do not map these
rows to existing fixed-strike instruments until this alignment is tested.

## Next gates

1. Confirm the API responds successfully and inspect the raw one-day payload.
2. Validate array lengths, timestamp timezone, strike progression, and data
   coverage against known FYERS candles.
3. Design a separate Dhan source adapter and idempotent import path.
4. Run unit tests and a tiny database dry-run before any bulk acquisition.
5. Only then plan 30-day chunked acquisition and coverage reporting.

No live order or order-execution integration is included in this stage.
