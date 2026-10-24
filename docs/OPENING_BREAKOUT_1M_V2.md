# Opening Breakout 1-Minute Strategy V2

Status: experimental / research-only / disabled by default.

V2 is separate from the existing V1 and does not modify locked KTMI,
Option Contract Resolver V2, Option Trade Management V1, or the reusable
risk engine.

## Configuration

File: `config/opening_breakout_1m_v2.py`

### Capital allocation

`CAPITAL_ALLOCATION_PERCENT` is 0-100 and caps notional exposure.

- 100 = up to 100% of available capital.
- 50 = up to 50%.

This is separate from Risk Per Trade.

### Timeframes

Supported: 5s, 10s, 20s, 30s, 1m, 3m, 5m.

If multiple timeframes are selected, the common candle/VWAP/BB calculation
timeframe is 1 minute. If one timeframe is selected, that timeframe is used.

### Bias and instrument

Bias: UP / DOWN / NEUTRAL.

Instrument: CALL / PUT / FUTURES / SPOT.

For CALL/PUT, the entry is a BUY of the option contract. For FUTURES/SPOT,
LONG maps to BUY and SHORT maps to SELL.

SPOT is intended for cash-market symbols and the eventual broker adapter must
route these orders to NSE.

## Opening candle filters

OPEN=LOW produces a bullish/CALL-side candidate.

OPEN=HIGH produces a bearish/PUT-side candidate.

If both are enabled, they are independent OR candidates. They are not ANDed on
the same candle because that would normally require an almost zero-range
candle. If both are OFF, this stage is bypassed.

Tolerance is an absolute price-point distance:

`abs(Open - Low) <= tolerance`

or

`abs(Open - High) <= tolerance`

Therefore Open=100, Low=99 and tolerance=1 passes. Tolerance=0.99 does not.

## Confirmation triggers

Available:

- Candle High
- Candle Low
- Above VWAP
- Below VWAP
- Close above Upper BB
- Close below Lower BB
- KTMI
- DMI

Multiple selected triggers are AND conditions.

Candle High/Low requires current price to cross/touch the completed setup
candle's level; merely having a high/low is not an entry.

VWAP/BB use the selected calculation timeframe, or 1 minute when multiple
timeframes are selected.

## KTMI

Defaults requested by the user:

- CALL buying speed >= 0.5
- PUT selling speed >= 0.5
- CALL momentum speed >= 0.5
- PUT momentum speed <= -0.5

The UI should enable these fields only when KTMI is selected.

## DMI

Defaults from the supplied TradingView screenshot:

- DI Length 14
- ADX Smoothing 14
- CALL +DI >= 25
- PUT -DI >= 25
- ADX >= 25

The UI should enable DMI fields only when DMI is selected.

+DI + ADX selected means both conditions must pass for CALL.
-DI + ADX selected means both must pass for PUT.

## Strike selector

Implemented modes:

1. LOT_VALUE: choose the contract whose LTP*lot_size is closest to the
   configured target, e.g. ₹10,000.
2. PRICE_RANGE: only contracts whose LTP is inside the configured range.
3. ATM_DISTANCE: choose by strike distance from ATM, e.g. ATM, ATM+50,
   ATM+100.

The existing locked Option Contract Resolver V2 should remain the resolver used
during integration.

## SL / TP

SL:

- OFF
- CUSTOM_POINTS
- CANDLE_1_HIGH
- CANDLE_1_LOW
- VWAP
- VALUE

VALUE is a whole-position loss cap, not a per-lot cap.

TP:

- OFF
- CUSTOM_POINTS
- VALUE
- RR_RATIO

RR presets to expose in UI: 1:1.5, 1:2, 1:3, 1:4, 1:5.

## Trailing SL

POINTS mode:

- profit trigger
- trail distance
- optional trail-to-cost

Example: entry 100, planned SL 80, trigger 40, trail distance 20 -> stop
moves to 100 when the 40-point profit threshold is reached.

RR_STEPS mode is configurable. Default:

- 2R -> 0R (cost)
- 3R -> 1R

Trailing is monotonic and cannot loosen an existing protective stop.

## Execution and risk

Entry buffer: +1 / +1.5 / +2.

Max slippage default: 2 points.

Fill timeout options: 5s, 10s, 20s, 30s, 1m, 3m, 5m.

Entry window default: 09:15 to 15:10.

Force exit default: 15:15.

### Requested position-sizing example

Capital ₹100,000; allocation 100%; risk ₹10,000; entry ₹100; SL ₹80;
lot size 65.

Risk per unit = ₹20.

Theoretical quantity = 10,000 / 20 = 500.

Complete lots = 7.

Quantity = 455.

Actual planned risk = 455 * 20 = ₹9,100.

Notional = 455 * 100 = ₹45,500.

The final quantity is limited by both risk budget and capital allocation.

## Chart trade tool

File: `execution/opening_breakout_chart.py`.

The model exposes Entry, SL and TP lines plus draggable SL/TP overrides.
Manual values always override filter-derived values.

When strategy SL/TP is OFF, configurable chart seed distances can populate
initial draggable protection lines.

The actual dashboard chart adapter is intentionally separate. It must bind
drag events to `override_sl(price)` and `override_tp(price)`, then submit
the resulting effective level to the broker order manager.

## Completed in this milestone

- V2 configuration schema
- timeframe selection rule
- bias and instrument model
- independent OH/OL candidate logic
- tolerance logic
- AND-combined confirmation filters
- KTMI/DMI gating
- strike selection
- SL/TP model
- whole-position risk cap
- capital allocation cap
- risk-first lot sizing
- point and RR trailing
- execution window
- option BUY-side marketable-limit correction
- chart SL/TP override state
- dedicated tests

## Next integration milestone

1. Wire V2 into the historical event/backtest runner.
2. Reuse the existing locked option resolver.
3. Add conservative historical fill simulation.
4. Add the actual dashboard chart adapter and draggable lines.
5. Add FYERS paper/live adapter only after backtest validation.

V2 remains disabled by default.
