# TSL Shadow Lab — calculation audit (2026-10-19)

Scope: research-only trailing-stop candidates in `paper_trading/tsl_shadow_lab.py`.
No production exits or broker order paths are changed by this audit.

## Change made

- Chandelier ATR(9) now uses the highest high of the most recent nine candles,
  rather than the highest high since the paper trade was registered. The latter
  unintentionally made the candidate a lifetime-high trail after an old price spike.
- The stop remains ratchet-only: it cannot move down for a long-option position.
- Focused regression tests cover the rolling lookback and ratchet behavior.

## Current validation status

- Wilder ATR uses an initial SMA seed followed by Wilder RMA; there is a unit test
  for the recurrence. Exact parity with TradingView still needs a larger exported
  candle fixture, including gaps and warm-up behavior.
- Supertrend is an in-house implementation and has not yet been proven bar-for-bar
  equivalent to TradingView's built-in `ta.supertrend`. Its final-band and reversal
  semantics need reference fixtures before candidate performance is compared.
- PSAR is a simplified state machine, not yet verified against TradingView's
  `ta.sar` initialization, extreme-point, acceleration-factor, and reversal rules.
  Do not label it TradingView-equivalent or rank it as such yet.
- The Kunal Quant structural candidate uses rolling-SMA true range by design. Its
  swing confirmation and stop ratchet still need hand-calculated reference cases
  against the isolated research implementation.
- Shadow P&L is gross only: commissions, taxes, spread, slippage, and realistic
  stop-gap fills are not comprehensively modeled.
- Shadow state is in memory only. A process restart can lose candidate indicator
  state for an open paper trade; persistence/recovery and session-end handling remain
  separate readiness items.
- Candidate summaries are written only once all six candidates have exited. If any
  candidate remains open, there is no final summary row yet.

## Next validation gates

1. Build small, hand-calculated OHLC fixtures for Supertrend, PSAR, and structural
   trailing; compare each candle's stop and reversal against a trusted reference.
2. Define and test warm-up, same-candle stop/reversal precedence, gap-through-stop
   fills, and session-end behavior.
3. Add cost-aware P&L and restart-safe candidate-state recovery before using shadow
   results to select a trailing method.

Until these gates pass, shadow outputs are exploratory and must not be used to claim
a winning trailing-stop configuration.
