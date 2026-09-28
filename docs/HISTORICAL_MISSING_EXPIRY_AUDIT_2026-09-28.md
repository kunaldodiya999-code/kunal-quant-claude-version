# Historical Missing Expiry Audit — 2026-09-28

## Scope

Local NIFTY underlying / KTMI data window audited:
- Start: 2026-08-01
- End: 2026-09-23

The historical expiry calendar was reconstructed independently of the local option resolver.

## Result

- KTMI events examined: 300
- Expected weekly expiries missing from local registry: 6
- Missing expected expiries with KTMI events requiring them: 3
- KTMI events affected by those missing expiries: 143
- Required exact option tuples on missing expiries: 30
- FYERS discovery: 30 / 30 found
- Not found at FYERS: 0
- FYERS API errors: 0

### Missing expiries discovered in the audit window

| Expiry | Required tuples | KTMI events affected |
|---|---:|---:|
| 2026-08-04 | 0 | 0 |
| 2026-08-11 | 0 | 0 |
| 2026-08-18 | 0 | 0 |
| 2026-08-25 | 7 | 34 |
| 2026-09-01 | 14 | 65 |
| 2026-09-08 | 9 | 44 |

The six dates are absent from the local registry, but only the final three are required by the current 300-event KTMI run.

## Contract discovery

FYERS returned every exact required contract for:
- 2026-08-25
- 2026-09-01
- 2026-09-08

There are no FYERS-side discovery gaps for the 30 contracts.

Examples:
- 2026-08-25: 24150 CE, 24150 PE, 24200 CE, 24200 PE, 24250 CE, 24250 PE, 24300 CE
- 2026-09-01: 24000–24350 required CE/PE combinations
- 2026-09-08: 23800–24000 required CE/PE combinations

## Baseline impact

This confirms that the earlier V2 bounded result cannot yet be frozen. The resolver was operating with incomplete weekly-expiry coverage, so 143 of the 300 events could not be assumed to use the true nearest weekly expiry.

No database changes were made by the audit.

## Next step

Register the 30 exact FYERS contracts required by the bounded sample, back up the database first, acquire their 1-minute expired-contract candles through their respective expiry dates, verify exact contract metadata and candle coverage, and then re-run the reference V2.
