# Kunal Quant — Current Engineering State — 2026-09-28

## Repository boundary

- Canonical repository: `kunaldodiya999-code/KunalQuant`
- Proposal/research repository: `kunaldodiya999-code/kunal-quant-claude-version`
- Canonical production code is **not to be modified** until the reference model is validated and the user explicitly approves a patch.

## Completed investigations

### Data and option contract integrity

- FYERS authentication and historical acquisition are working.
- NIFTY 1-minute historical acquisition for the planned 5-year window is complete.
- 3M/5M derived pipelines exist.
- Required option-contract discovery and acquisition are working.
- Required-contract metadata mismatches were found and repaired in the local database with a backup.
- 49 required contracts for the bounded sample were verified.
- Previously zero-candle required option contracts were audited against FYERS and 385 candles for the target sample date were acquired.
- Bounded sample currently has 0 unresolved contracts and 0 missing option entry candles.

### Position lifecycle integrity

The current event runner was found to simulate a whole trade before advancing to the next KTMI event. This produced future-aware lifecycle state.

Observed current path on the bounded 20-trading-day sample:
- 300 KTMI events
- 249 accepted trades
- 239 closed
- 10 open
- 51 allocation rejected
- 564 same-strategy overlaps

Correct chronological stateful diagnostic:
- 41 closed
- 2 open
- 43 allocation rejected
- 214 lifecycle rejected
- 0 unresolved
- 0 no-entry-candle
- 0 same-strategy overlaps
- closed gross P&L -18,930.60

The 41-trade figure is a diagnostic result only, not yet the final reference result.

### Timestamp / lookahead integrity

Derived 3M bars are timestamped at bucket start.

Example:
- 09:15 bar contains 09:15, 09:16, 09:17.
- It is fully known at 09:18.

Current event timing was therefore 180 seconds early.

Bounded diagnostic:
- 300/300 events had an early option entry.
- Average signal-to-corrected-entry delay: 240 seconds under the current candle-close convention.
- 300/300 current option entries were mapped to a still-forming 3M KAMA bar.
- Corrected KAMA alignment had 0 forming-bar references.

### Indicator warm-up integrity

The bounded loader uses only the last 20 trading days before calculating KTMI and KAMA.

Full available complete 3M history: 153,122 bars.
Bounded sample: 2,500 bars.

Comparison at the sample boundary:
- Full-history KTMI events in sample: 304.
- Slice-only KTMI events: 300.
- KAMA full-history value at sample start: 24,216.2028818374.
- Slice-only KAMA at sample start: 15.3634665079.
- Absolute difference: 24,200.8394153294.

This proves that a final backtest cannot calculate recursive indicators from the 20-day slice alone. It must preserve adequate historical indicator state.

## Session boundary investigation

Official NSE equity-derivatives hours are 09:15–15:40 for the current session.

However, the locally stored raw FYERS NIFTY 1M dataset has no normal post-15:29 candles in the 2026 sample. The only raw dates found with candles after 15:29 were special-session dates:
- 2021-11-04
- 2022-10-24
- 2023-11-12
- 2024-11-01

Thus the current underlying dataset cannot generate new normal-session NIFTY 3M/5M bars after 15:27 for the 2026 sample.

Option data may extend to 15:39, but post-15:29 option management requires an underlying-data/session decision. Do not invent NIFTY 3M bars after the last available underlying candle.

## User-locked SHORT semantics

The user clarified the intended option behavior:

- Momentum Speed crosses above a configurable positive trigger -> BUY CE.
- Momentum Speed crosses below a configurable negative trigger -> BUY PE.
- Long Speed crosses above a configurable positive trigger -> BUY CE.
- Short Speed crosses above a configurable positive trigger -> BUY PE.

Therefore a SHORT/bearish signal means **BUY PE / long option premium**, not short-sell PE.

This is a semantic specification to be implemented in the proposal/reference layer first. It is not yet a canonical patch.

## User-locked parameterization requirement

The trigger levels are not permanently fixed at 0.50 / -0.50.

The backtest must expose independent configurable inputs for:
- Momentum CE trigger
- Momentum PE trigger
- Long Speed CE trigger
- Short Speed PE trigger

Each signal source should be independently enabled/disabled.

The same infrastructure should support controlled parameter sweeps without changing KTMI calculation logic.

## Current reference-model status

A proposal-only no-lookahead chronological reference backtest was created, but review found an accounting defect (C1): trades that close between event boundaries can be removed from active state without being retained in the closed-trade ledger.

A dry-run patch exists:
`proposals/fixes/reference_backtest_keep_closed_trades.patch`

The reference result must be regenerated after this defect is fixed.

Additional proposal-side review notes exist in:
- `docs/reviews/2026-09-28_reference_backtest_review.md`
- `PENDING_FROM_YOU.md`

## Remaining pre-patch work

1. Fix the proposal/reference report's closed-trade ledger bug.
2. Preserve full-history KTMI/KAMA state while restricting trading events to the selected test window.
3. Lock date-aware session behavior using the actual data coverage; do not extrapolate missing underlying bars.
4. Validate event/accounting invariants and no-lookahead invariants.
5. Implement the user's BUY-PE semantics and configurable trigger sources/thresholds in proposal code only.
6. Produce a final controlled reference result on the bounded sample.
7. Only after that prepare a production patch for explicit approval.
