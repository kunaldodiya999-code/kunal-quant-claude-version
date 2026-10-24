# Opening Breakout V2 — Signal Engine Checkpoint — 2026-09-29

Status: **Experimental / disabled by default**

## Completed

Added `backtest/opening_breakout_v2_signal_engine.py`.

It provides a no-lookahead historical signal boundary:

1. Candle 0 is the completed opening/setup candle.
2. OPEN=LOW / OPEN=HIGH produces candidate alerts.
3. Candidate direction is filtered by market bias and instrument.
4. Selected confirmation filters are ANDed.
5. Confirmation is evaluated only on later completed candles.
6. The first qualifying later candle produces one signal per supplied series.
7. Multiple series can be scanned together and signals are timestamp ordered.
8. Multiple selected timeframes resolve to the configured 1-minute calculation timeframe.

The engine is intentionally independent of:
- FYERS
- broker adapters
- the locked Option Contract Resolver V2
- locked lifecycle modules
- economic cost models

## Important execution boundary

This milestone does **not** simulate an order fill or P&L.

That is deliberate. The next layer must define conservative historical marketable-limit
fill behavior, fill timeout, slippage rejection, SL/TP precedence and trailing
behavior before performance results are generated.

## Tests

Added:
`tests/test_opening_breakout_v2_signal_engine.py`

Coverage includes:
- no same-opening-candle trigger
- later-candle breakout
- AND confirmation filters
- DMI PUT condition
- market-bias rejection
- multi-timeframe -> 1M rule
- independent CE/PE opening alerts

V2 remains disabled by default.
