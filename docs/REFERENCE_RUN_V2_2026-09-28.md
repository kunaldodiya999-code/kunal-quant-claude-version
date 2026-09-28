# Kunal Quant — Reference Backtest V2 Run — 2026-09-28

## Purpose

This records the first successful bounded run of the proposal-only no-lookahead reference model V2.

Canonical `KunalQuant` was not modified.

## Command

```powershell
cd C:\Users\USER\Desktop\Kunal\KunalQuant
$env:PYTHONUTF8="1"
$env:PYTHONPATH=(Get-Location).Path
python .\kunal-quant-claude-version\proposals\generate_reference_backtest_v2.py --json "$HOME\Desktop\reference_backtest_v2.json" | Tee-Object "$HOME\Desktop\reference_backtest_v2.txt"
```

## Model gates passed before the run

- V2 option-semantics checks: all passed.
- Configurable CE/PE triggers: verified.
- BUY PE is a long-premium position: verified.
- BUY PE KAMA uses bearish underlying direction: verified.
- BUY CE KAMA uses bullish underlying direction: verified.
- Full-history KTMI/KAMA warm-up is used by V2.
- 3M signal availability is delayed to bar completion.
- Option entry requires the first 1M candle strictly after signal availability.
- Position lifecycle is processed chronologically.
- Closed trades remain in the reference ledger.

## Bounded run

- Sample 3M bars: 2,500
- All complete 3M bars: 153,122
- KTMI events in window: 301
- Sample: 2026-08-21 09:15 IST -> 2026-09-23 15:27 IST

### Event accounting

| Category | Count |
| --- | ---: |
| Closed trades | 39 |
| Open trades | 2 |
| Lifecycle rejected | 214 |
| Allocation rejected | 44 |
| Unresolved | 0 |
| No entry candle | 2 |
| Outside session | 0 |
| Accounted events | 301 |
| Accounting check | PASS |

### Closed-trade performance

| Metric | Value |
| --- | ---: |
| Closed trades | 39 |
| Winners | 27 |
| Losers | 12 |
| Win rate | 69.23% |
| Gross profit | 33,569.25 |
| Gross loss | -5,112.25 |
| Net gross P&L | 28,457.00 |
| Profit factor | 6.5664 |
| Average trade P&L | 729.67 |
| Median trade P&L | 435.50 |
| Largest win | 3,337.75 |
| Largest loss | -747.50 |
| Max drawdown | 1,943.50 |

### Exit reasons

All 39 closed trades exited via `KAMA_EXIT` in this run.

- KAMA exits: 39
- KAMA exit P&L: 28,457.00
- Stop-loss exits: 0
- 3R target exits: 0

### Portfolio

- Max concurrent trades: 2

## Interpretation status

**Diagnostic only — not the final strategy baseline.**

The run demonstrates that the V2 model executes end-to-end under the current bounded dataset and satisfies its event-accounting check. The result must not be treated as proof of strategy performance because remaining pre-5-year validation items include historical instrument-registry coverage, date-aware NIFTY lot size, session/data-availability policy, and final no-lookahead/report regression coverage.

The large change versus earlier 239-trade / 41-trade diagnostics is expected to reflect the combined effect of full-history indicator warm-up, corrected timing, chronological lifecycle enforcement, and BUY-PE semantics. Earlier results remain non-baseline.

## Next required validation

1. Run the instrument registry diagnostic across the full planned historical range.
2. Validate historical expiry coverage and resolver behavior.
3. Implement/validate date-aware NIFTY lot sizes before the 5-year run.
4. Run the final proposal-side invariant/regression suite.
5. Re-run the bounded reference model and freeze its output as the pre-patch reference.
6. Only then prepare a canonical patch for explicit approval.
