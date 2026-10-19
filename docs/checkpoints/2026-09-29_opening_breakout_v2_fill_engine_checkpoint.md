# Opening Breakout V2 — Historical Fill Engine Checkpoint

## Status
Experimental / research-only.

## Completed
Added `backtest/opening_breakout_v2_fill_engine.py`.

The engine currently provides:
- historical OHLC bar validation
- no-lookahead entry search
- marketable-limit entry fill simulation
- fill timeout
- explicit max-slippage rejection
- conservative stop/target precedence
- marketable-limit exit modelling
- force-exit handling
- configurable trailing-stop hook
- trade-level gross P&L calculation

## No-lookahead rules
1. The signal/trigger candle cannot fill the entry.
2. Entry search starts strictly after the trigger timestamp.
3. Entry fills require the historical bar to prove the limit was reachable.
4. If stop and target are both touched in one bar, stop wins.
5. Force exit is only evaluated after entry is filled.

## Intentionally not implemented yet
- FYERS calls
- live/paper order placement
- option contract discovery/resolution changes
- broker-specific fill semantics
- brokerage/STT/GST/charges/slippage cost model
- portfolio-level P&L
- reuse/integration of the locked lifecycle/accounting modules
- chart UI integration

## Validation
Dedicated tests were added in:
`tests/test_opening_breakout_v2_fill_engine.py`

The user should pull this checkpoint and run the dedicated test plus the existing Opening Breakout suite before the next integration stage.

## Next step
Integrate the signal engine with the fill engine using real historical option candles, while preserving the existing Option Contract Resolver V2 and locked lifecycle/accounting behaviour.
