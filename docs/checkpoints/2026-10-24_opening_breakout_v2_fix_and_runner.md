# Checkpoint 2026-10-24: Opening Breakout V2 fix, indicators and runner

## Where the project was

Since the last Claude checkpoint (2026-09-29) canonical work moved to the
**Opening Breakout 1M V2** strategy: signal engine, option integration,
conservative fill engine, historical lot size, multi-session runner, broker
cost model, portfolio equity, rejection diagnostics and economic attribution
(up to `de03dca`, 2026-10-01). Then a YT research pack (`9e4a06e`) and a
fixture fix (`30e1b2f`, 2026-10-10). Baseline: 201 tests pass, 5 need the
local DB.

## What review found

1. **PUT trades were simulated as short premium** (`option_integration`,
   `economic_attribution`). Every premium-side calculation used
   `event.direction`, which is `SHORT` for a PUT signal. Result: stop above
   entry, target below, P&L inverted. It was hidden because the real-data
   runner hard-codes `trade_instrument="CALL"`. This contradicts both the V2
   doc ("For CALL/PUT, the entry is a BUY") and the locked user semantics
   (bearish = BUY PE, long premium). Reproduced: a PE bought at 100 that rose
   to 115 was booked at ₹-5,460.
2. **Indicator triggers were dead in real runs.** `run_opening_breakout_v2_multi_session.py`
   passes `empty_indicator_provider`, so ABOVE/BELOW_VWAP, BB, KTMI and DMI
   always returned False. No VWAP/BB/DMI implementation existed anywhere.
3. **VWAP on NIFTY index has no meaning.** `NSE:NIFTY50-INDEX` has no
   volume. The new provider returns `None` rather than fabricating an
   equal-weight average, and the runner prints a warning. A real VWAP needs
   NIFTY futures volume (decision for you, see `PENDING_FROM_YOU.md`).
4. Minor, not changed: `run_opening_breakout_trade` always passes
   `trailing_mode="RR_STEPS"`, so POINTS trailing is unreachable in
   backtests; the strike-selector settings (LOT_VALUE / PRICE_RANGE /
   ATM_DISTANCE) are not used by the backtest, which always takes the
   locked resolver's ATM contract.

## What was delivered (`patches/`)

- `0001`: `premium_direction()` helper; PUT and CALL are long premium.
  Resolver still receives the signal direction, so it still picks the PE.
- `0002`: causal indicator provider (TradingView-equivalent BB and DMI/ADX,
  session VWAP, locked KTMI reused), `lot_size_loader` passthrough on the
  multi-session runner, and `scripts/run_opening_breakout_v2_backtest.py`.

Verification: patches applied in order to clean `30e1b2f` gave 218 passed,
with the same 5 DB-only errors. DMI/ADX is cross-checked against an
independent pandas implementation. Causality is checked by truncation (values
at T are identical with or without later candles).

## Not yet done

- Real-data run on your machine (this environment has no database).
- Futures-volume VWAP.
- Dashboard pages reading the runner's `summary.json` / `trades.csv`.
- Paper-trading adapter (only after a validated backtest).
