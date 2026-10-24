# Pending From You

_Updated 2026-10-24._

## Do this next

Work only in this folder: `C:\Users\USER\Desktop\Kunal\kunal-quant-claude-version`
(the one that has the `.venv`). Leave the `KunalQuant` folder alone.

Next steps are given one at a time in the chat.

## Decisions I need from you

1. **VWAP source.** NIFTY index has no volume, so `ABOVE_VWAP` /
   `BELOW_VWAP` can never fire, and the runner warns you when this happens.
   Options: (a) use NIFTY near-month futures volume (needs futures 1M data
   downloaded); (b) drop VWAP from V2 for now. I recommend (b) until the
   backtest is validated, then (a).
2. **Which strategy is primary?** The repos hold two tracks: KTMI options
   (reference backtest V2 below) and Opening Breakout V2 (where canonical
   work has been since 2026-09-29). I am treating **Opening Breakout V2 as
   primary**. Tell me if that is wrong.

## Earlier track: KTMI reference backtest (paused, kept for reference)

### Decisions confirmed

1. **SHORT signal semantics are BUY PE / long premium.**
   - Momentum Speed crosses below the configurable negative trigger -> BUY PE.
   - Short Speed crosses above the configurable positive trigger -> BUY PE.
   - No option short-selling is intended for these KTMI bearish signals.

2. **Trigger parameters must remain configurable.**
   - Momentum CE trigger
   - Momentum PE trigger
   - Long Speed CE trigger
   - Short Speed PE trigger
   - Each source independently enabled/disabled.
   - Current 0.50 / -0.50 values are test defaults, not permanent constants.

### Engineering findings that must be resolved before a canonical patch

- Full-history indicator warm-up must be preserved.
- 3M signal availability must be based on completed 3M bars, not bucket-start timestamps.
- Option entry must respect the no-lookahead timing contract.
- KAMA must use completed underlying 3M bars only.
- Position Lifecycle V1 must be enforced chronologically.
- Closed trades must never be dropped from the reference ledger.
- Event accounting must equal total KTMI events exactly.
- Session behavior must be date-aware and must not fabricate missing underlying data.
- ~~Historical NIFTY lot size must be date-aware before the 5-year run.~~
  Done: `proposals/nifty_lot_size.py`, 11/11 tests pass. NIFTY only
  (confirmed sources); one boundary (2025-01-02 -> lot 75) is from a
  single community report, not a confirmed circular -- verify before
  the 5-year run. BankNifty/Sensex raise `NotImplementedError` rather
  than guess.
- Same-timestamp event ordering must be explicit and tested.

### Current data/session note

NSE's current equity-derivatives session is 09:15–15:40. The local raw NIFTY 1M dataset, however, has no normal 2026 candles after 15:29. Therefore the reference model must not fabricate post-15:29 NIFTY bars. Option data can be evaluated only where the underlying reference required by a rule is legitimately available.

### Current running work (updated 2026-09-28, later same day)

The C1 closed-trade ledger defect is fixed in V2
(`generate_reference_backtest_v2.py`). The bounded run in
`docs/REFERENCE_RUN_V2_2026-09-28.md` passed its accounting check
(301/301 events) -- 39 closed, 2 open, 69.2% win rate, net P&L 28,457.

**But that run is not the baseline yet.** The same day's
`docs/HISTORICAL_MISSING_EXPIRY_AUDIT_2026-09-28.md` found the resolver
was missing 3 weekly expiries the bounded sample actually needed,
affecting 143 of the 300 events (FYERS has all 30 required contracts;
they just aren't registered locally yet). The V2 run above used the
resolver *before* that registration, so it will change again once fixed.

Do not use the 239-trade, 41-trade, OR the 39-trade V2 numbers as the
final baseline yet.

### Next execution sequence

1. Register the 30 missing-expiry contracts found in the audit and
   acquire their candles (scripts for this already exist in
   `proposals/`: `register_missing_expiry_contracts.py`,
   `acquire_missing_expiry_required_candles.py`).
2. Re-run `diagnose_instrument_registry.py` to confirm no more gaps in
   the sample window.
3. Re-run the bounded V2 reference model with the completed registry.
4. Inspect the final accounting, timing, session and lifecycle invariants.
5. Only then move the validated behavior into canonical KunalQuant with
   explicit approval.

### GitHub token hygiene

If an old GitHub token remains in chat/history, revoke it after this session and create a new least-privilege token for the proposal repository if needed.
