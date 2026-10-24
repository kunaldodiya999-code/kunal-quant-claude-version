# PSAR reference validation — 2026-10-25

`paper_trading/tsl_methods.psar` is a line-by-line port of TradingView's Pine reference
implementation of `ta.sar` (`pine_sar`: start at bar 1 from close vs previous close, project,
reverse on a pierce, increase the factor on a new extreme, clamp to the previous two bars).

Cross-check: on 300 random candles it matches the open-source `ta` library (bukosabino, 0.11.0,
`PSARIndicator`) to 0.0 difference from the 3rd candle on; the first two candles differ by design
(TradingView's own start rule). Hand-calculated cases: `tests/test_tsl_methods.py`.
Last gate: compare `scripts/tsl_check.py` output with TradingView's Data Window for one day.
