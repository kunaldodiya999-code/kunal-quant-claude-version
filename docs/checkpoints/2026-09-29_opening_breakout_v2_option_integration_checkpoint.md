# Opening Breakout V2 — Real Option Integration Boundary

## Status
Experimental / research-only.

## Completed
The bridge now connects:
1. Opening Breakout V2 signal event
2. existing Option Contract Resolver V2
3. existing stored FYERS 1-minute option candles
4. historical marketable-limit fill engine
5. V2 risk sizing
6. V2 SL/TP helpers
7. canonical instrument lot-size metadata

Resolver V2 itself is unchanged.

## Historical timing
- Underlying price is the latest completed underlying candle at or before the signal boundary.
- Option signal price is the latest completed option candle at or before the signal boundary.
- Entry search begins strictly after the signal timestamp.
- The entry candle is not processed for exits.
- Missing option history or missing lot-size metadata is surfaced explicitly.

## Test coverage
The dedicated integration test uses a deterministic resolver/loader fixture and verifies:
- resolver invocation
- option data access by resolved instrument ID
- entry fill
- quantity/lot sizing
- stop/target creation
- stop exit
- gross P&L

A second test verifies that missing lot-size metadata is rejected instead of invented.

## Not yet complete
- Full-session multi-day scan of real database data
- strike-selector modes beyond Resolver V2's ATM contract
- broker-realistic charges/cost model
- portfolio-level accounting
- integration with the locked V1 lifecycle for this new V2 strategy

## Next step
Run the new integration tests locally. Then build the real-data session runner that converts stored NIFTY candles into V2 signal events and feeds each accepted event through this bridge.
