# Pending From You

_Updated 2026-09-28 after the latest engineering review._

## Decisions confirmed

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

## Engineering findings that must be resolved before a canonical patch

- Full-history indicator warm-up must be preserved.
- 3M signal availability must be based on completed 3M bars, not bucket-start timestamps.
- Option entry must respect the no-lookahead timing contract.
- KAMA must use completed underlying 3M bars only.
- Position Lifecycle V1 must be enforced chronologically.
- Closed trades must never be dropped from the reference ledger.
- Event accounting must equal total KTMI events exactly.
- Session behavior must be date-aware and must not fabricate missing underlying data.
- Historical NIFTY lot size must be date-aware before the 5-year run.
- Same-timestamp event ordering must be explicit and tested.

## Current data/session note

NSE's current equity-derivatives session is 09:15–15:40. The local raw NIFTY 1M dataset, however, has no normal 2026 candles after 15:29. Therefore the reference model must not fabricate post-15:29 NIFTY bars. Option data can be evaluated only where the underlying reference required by a rule is legitimately available.

## Current running work

A no-lookahead chronological reference implementation exists in the proposal repository. Claude's static review found a critical closed-trade ledger defect (C1) that must be fixed before its result is trusted.

The warm-up audit also proved that calculating KTMI/KAMA on only the 2,500-bar sample changes indicator state.

Do not use earlier 239-trade or 41-trade outputs as the final baseline.

## Next execution sequence

1. Finish the proposal/reference-model corrections and tests.
2. Run the bounded reference model again.
3. Inspect the final accounting, timing, session and lifecycle invariants.
4. Only then move the validated behavior into canonical KunalQuant with explicit approval.

## GitHub token hygiene

If an old GitHub token remains in chat/history, revoke it after this session and create a new least-privilege token for the proposal repository if needed.
