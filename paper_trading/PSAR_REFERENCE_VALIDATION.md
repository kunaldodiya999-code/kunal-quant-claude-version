# PSAR Reference Validation — 2026-10-19

## Scope

This is a research-only audit of `TslShadowLab._psar`. It does not change the production paper lifecycle or submit orders.

## External reference checked

TradingView's Pine Script v6 reference documents built-ins and exposes the `ta.sar()` function, but the public reference page is not an executable oracle for arbitrary OHLC sequences. The Supertrend reference is explicit about its recurrence; the PSAR implementation here has **not** been shown to match TradingView's internal initialization and reversal semantics.

Reference: https://www.tradingview.com/pine-script-reference/v6/

## What the existing tests prove

`tests/test_tsl_shadow_psar_reference.py` contains four deterministic, hand-calculated tests for this project's current recurrence:
- two-bar initialization;
- bullish projection, two-bar clamp, and acceleration-factor increase;
- bullish-to-bearish reversal;
- bearish projection, clamp, and extreme-point update.

These tests are useful regression tests, but they are not independent TradingView output fixtures and must not be described as TradingView parity.

## Audit findings / remaining parity questions

The current implementation initializes direction from the second candle's close versus the first candle's close and initializes SAR/EP from the two-bar extrema. Subsequent bars project SAR, clamp it to prior lows/highs, and then test for reversal. TradingView's exact initialization and ordering must be verified against exported chart values or a Pine script that plots `ta.sar(start, inc, max)` over a fixed OHLC fixture.

The shadow candidate currently treats a bearish PSAR state as an exit signal for a long option. It should only be evaluated as an experimental exit rule after the plotted PSAR series has been compared bar-for-bar with the intended reference.

## Required independent test procedure

1. In TradingView, create a temporary Pine v6 indicator that plots `ta.sar(0.02, 0.02, 0.20)` and `ta.sar(0.04, 0.04, 0.10)`.
2. Use a fixed, exported OHLC series with at least one bullish continuation, one bearish continuation, and reversals in both directions. Include the full warm-up history.
3. Export or record each candle's timestamp, OHLC, and both PSAR values. Preserve full decimal precision where available.
4. Feed exactly those candles in chronological order to `TslShadowLab._psar`; compare every bar after initialization using an explicit numeric tolerance.
5. If any mismatch occurs, locate the first divergent bar and check initialization, extreme point, acceleration-factor increment/cap, two-bar clamping, and reversal assignment order. Change implementation only after the mismatch is reproducible.
6. Keep this test fixture separate from the recurrence tests, and label its provenance (TradingView export, symbol, timeframe, date range, parameters).

## Status

**Not yet TradingView-validated.** No production logic was changed by this audit. Do not rank PSAR against other trailing candidates using this implementation as if parity had been established.
