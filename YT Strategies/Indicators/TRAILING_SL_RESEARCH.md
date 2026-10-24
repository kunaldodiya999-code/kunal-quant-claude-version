# Trailing SL Research Decision

## Primary candidate

**ATR-confirmed structural trailing**, derived from the supplied Structural Leg Profiler.

Why it wins:
1. Produces an explicit price level.
2. Adapts to volatility through ATR.
3. Uses only closed-bar information.
4. Ratchets only in the profitable direction.
5. Is independent of the locked V2 entry trigger.
6. Is explainable per stop update.

## Not primary trailing stops

- **SMC:** excellent context, but BOS/CHoCH/OB are event semantics rather than a continuous stop.
- **Log regression:** too slow for intraday option trailing.
- **Volume profile:** useful context, but can be static/session-dependent.
- **CVD/delta:** promising but historical bar proxies are weak without real bid/ask delta.
- **GEX:** valuable options regime/target context, not a robust stop by itself.
- **Oscillator/RSI divergence:** better as exit confirmation than sole protection.

## Planned variants

A. Baseline V2 stop/target.
B. Structure trail.
C. Structure + break-even after configurable R.
D. Structure + independent exit signal.

All variants must use identical historical contracts, fill rules, sizing and broker-cost assumptions. No production integration until the baseline comparison is complete.
