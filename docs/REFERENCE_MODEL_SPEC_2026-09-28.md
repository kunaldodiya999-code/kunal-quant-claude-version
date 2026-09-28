# Kunal Quant — Reference Model Specification — 2026-09-28

This is a pre-patch behavioral specification. It is not production code.

## 1. Indicator state

For a selected backtest window, calculate KTMI and KAMA using sufficient preceding complete 3M history so recursive/rolling state is not reset at the sample boundary.

Only bars inside the selected window are eligible to generate trades.

Do not change KTMI calculation formulas.

## 2. 3M timing

A 3M bar timestamp is the bucket start.

A bar at T contains source minutes T, T+60, T+120 and becomes fully knowable at T+180.

The event availability time is therefore:

`signal_available = bar.timestamp + 180 seconds`

The event's strategy values must correspond to that completed 3M bar.

## 3. Option entry

For an accepted signal, identify the first 1-minute option candle with:

`candle.timestamp > signal_available`

Entry price remains the candle close under the current execution convention.

The entry candle is not processed as an exit-management candle.

No same-candle lookahead is allowed.

## 4. Option candle processing time

A 1-minute option candle starting at C becomes fully knowable at C+60 seconds.

Management decisions that use that candle's OHLC are evaluated no earlier than its completion time.

Exit timestamps may continue to use the candle start for compatibility with existing models, but reports should distinguish decision-ready time from display timestamp.

## 5. KAMA alignment

At an option-candle processing-ready time, use the latest underlying 3M bar whose completion time is <= that processing-ready time.

Do not use a forming 3M bar.

## 6. Position lifecycle

Process events chronologically.

Before evaluating a new signal, advance all active trades only up to the current event's information boundary.

Only positions that are actually active at that boundary participate in Position Lifecycle V1.

One position per strategy is enforced according to the existing lifecycle configuration.

Different strategies may hold independent positions.

## 7. Session boundary

Do not invent underlying bars after the last available raw NIFTY 1-minute timestamp.

For the currently available 2026 underlying dataset, normal NIFTY data ends at 15:29.

Option management after 15:29 should be used only where an underlying KAMA/reference value is legally available and the chosen session policy permits it.

The date-aware exchange calendar may be used for instrument/session eligibility, but missing underlying observations must remain missing.

## 8. Option direction semantics

The strategy is options-buying:

- Momentum positive trigger => BUY CE.
- Momentum negative trigger => BUY PE.
- Long Speed positive trigger => BUY CE.
- Short Speed positive trigger => BUY PE.

For BUY CE and BUY PE, the option position is a long-premium position.

Therefore:
- stop is below entry premium;
- target is above entry premium;
- P&L is (exit - entry) * quantity for both CE and PE buys.

The word SHORT refers to the bearish signal direction, not to short-selling the option.

## 9. Trigger configuration

The following are independent parameters:

- momentum_long_trigger
- momentum_short_trigger
- long_speed_trigger
- short_speed_trigger

Each signal source can be enabled or disabled independently.

The defaults may retain the current test values:
- +0.50
- -0.50
- +0.50
- +0.50

but these are experiment inputs, not locked permanent constants.

## 10. Allocation

Keep the existing V1 allocation rule for the reference experiment:
- allocation ₹15,000
- lot size appropriate to the test date

Allocation rejection is a non-executable event and must be counted in event accounting.

Historical lot size must become date-aware before the full 5-year run.

## 11. No invented economics

Do not add brokerage, taxes, slippage, spread, or mark-to-market assumptions unless explicitly specified and independently parameterized.

The current reference output is gross P&L.

## 12. Reference backtest acceptance criteria

A reference run is not accepted as a valid baseline unless:
- every KTMI event is accounted for exactly once;
- no same-strategy overlap exists;
- no event uses future bars;
- no KAMA calculation uses a forming 3M bar;
- entry occurs only after the completed 3M signal bar is known;
- session behavior is explicit;
- BUY PE and BUY CE semantics are correct;
- indicator state is warm-started from historical context;
- report ledger retains every closed trade;
- canonical KunalQuant remains unchanged during proposal validation.
