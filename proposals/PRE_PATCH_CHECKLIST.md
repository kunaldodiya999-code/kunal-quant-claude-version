# Pre-Patch Checklist

Do not patch canonical KunalQuant until every item below is green.

## Backtest engine integrity

- [ ] Full-history indicator warmup is preserved.
- [ ] 3M event availability is bar start + 180 seconds.
- [ ] Option entry is first 1M candle strictly after signal availability.
- [ ] Entry candle is excluded from exit processing.
- [ ] Option candle OHLC is processed only after its minute completes.
- [ ] KAMA uses only a completed 3M bar.
- [ ] Position Lifecycle V1 is enforced chronologically.
- [ ] Same-strategy overlap count is zero.
- [ ] Every event is accounted for exactly once.
- [ ] Closed-trade ledger retains trades that close between event boundaries.
- [ ] Report ordering is based on actual exit time where appropriate.

## Data/session integrity

- [ ] Required contracts are present and metadata matches parsed symbols.
- [ ] Required option candle coverage is sufficient.
- [ ] No unresolved contracts in the final reference sample.
- [ ] No missing entry candles in the final reference sample.
- [ ] Session policy is date-aware and does not fabricate missing underlying data.
- [ ] Special sessions are handled explicitly.
- [x] Historical lot sizes are date-aware before the 5-year run -- proposals/nifty_lot_size.py, 11/11 tests pass. Only NIFTY is covered (confirmed sources); BankNifty/Sensex raise NotImplementedError rather than guess. One era boundary (2025-01-02, lot 75) is from a single community report, not a confirmed circular -- flagged in the module docstring for verification.

## Strategy semantics

- [ ] Momentum positive trigger -> BUY CE.
- [ ] Momentum negative trigger -> BUY PE.
- [ ] Long Speed positive trigger -> BUY CE.
- [ ] Short Speed positive trigger -> BUY PE.
- [ ] Trigger sources can be enabled/disabled independently.
- [ ] Trigger thresholds are independently parameterized.
- [ ] BUY CE and BUY PE both use long-premium option management.
- [ ] KTMI calculation itself remains unchanged.

## Validation

- [ ] Synthetic no-lookahead tests pass.
- [ ] Timestamp/session regression tests pass.
- [ ] Allocation rejection tests pass.
- [ ] Reference backtest accounting check passes.
- [ ] Bounded reference performance report regenerated after all integrity fixes.
- [ ] Canonical KunalQuant has no unapproved changes.
