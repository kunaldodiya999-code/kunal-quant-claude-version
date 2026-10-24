# Opening Breakout V2 Checkpoint — 2026-09-29

Status: **Experimental / disabled by default**

## Added

- `config/opening_breakout_1m_v2.py`
- `research/opening_breakout_1m_v2.py`
- `execution/opening_breakout_v2_execution.py`
- `execution/opening_breakout_chart.py`
- `tests/test_opening_breakout_1m_v2.py`
- `tests/test_opening_breakout_v2_execution.py`
- `docs/OPENING_BREAKOUT_1M_V2.md`

## Functional coverage

- capital allocation 0-100%
- 5s/10s/20s/30s/1m/3m/5m selection
- multi-timeframe -> 1m calculation rule
- UP/DOWN/NEUTRAL bias
- CALL/PUT/FUTURES/SPOT
- independent OPEN=LOW / OPEN=HIGH alerts
- absolute tolerance
- AND-combined breakout confirmations
- KTMI threshold gating
- DMI 14/14 with +DI/-DI/ADX defaults of 25
- lot-value, price-range and ATM-distance strike selection
- point/candle/VWAP/value SL model
- point/value/RR TP model
- points and RR trailing
- capital and risk constrained lot sizing
- entry buffer, slippage, fill timeout and time windows
- force-exit time
- option BUY-side marketable-limit mapping
- chart SL/TP override state
- filter-off chart seed levels

## Important boundary

The interactive dashboard drag/drop implementation and broker adapter are not
yet wired to this new V2 layer. The backend model is intentionally broker/UI
neutral so the same rules can be reused in Backtest, Paper and Live.

V2 remains disabled by default.
