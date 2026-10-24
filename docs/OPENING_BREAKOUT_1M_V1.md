# Opening Breakout 1-Minute Strategy V1

Status: **Experimental / research-only**. Default disabled.

This is a separate strategy family from the existing HFT 10S Gap-Open V1.

## Architecture

- `config/opening_breakout_1m.py`: strategy defaults only.
- `research/opening_breakout_1m_v1.py`: pure signal/SL/TP/order-price logic.
- `execution/opening_breakout_state.py`: broker-neutral order state machine.
- Existing `risk/risk_engine.py`: position sizing remains reusable; it is not duplicated.

## Current semantics

- `MARKET_BIAS` constrains the **trade direction**: UP permits LONG, DOWN permits SHORT, NEUTRAL permits either.
- `TRADE_INSTRUMENT` is an explicit instrument override and does not get auto-rewritten by bias.
- OH/OL filters are contract-candle filters and can be independently enabled; both false bypass both.
- `1_MIN_HIGH` creates a LONG breakout; `1_MIN_LOW` creates a SHORT breakout.
- Marketable-limit buffers, slippage guard, fill timeout and square-off cutoff are configuration, not broker behavior.
- RR target requires a valid stop distance.
- The state machine is broker-neutral and does not place orders.

## Deliberate non-decisions

- VWAP calculation/source is not implemented here.
- Risk sizing is not duplicated; the existing risk engine should be wired in during the next integration milestone.
- FYERS live/paper order adapter is not added yet.
- No existing locked module is changed.
- No partial-target allocation is hard-coded.

## Important trading-behavior note

A SHORT breakout means a short position in the selected contract. If the intended design is instead to **buy a PUT** on a bearish underlying breakout, that is a different execution mapping and must be made explicit before integration.
