# Patches for canonical KunalQuant

Verified on 2026-10-24 against canonical commit `30e1b2f` (latest `main`).
Applied in order to a clean copy: **218 tests pass**. The only errors are the 5
`ktmi_fyers_validation_test.py` tests that need your local database, same as
before the patches.

| Patch | What it does |
|---|---|
| `0001-v2-put-is-long-premium.patch` | **Bug fix.** Opening Breakout V2 simulated a bought PUT as a *short* premium position: stop above entry, target below, P&L sign flipped. A winning PUT (premium 100 → 115) was booked as a ₹-5,460 stop-loss. Same bug in the economic-attribution audit. Now a PUT is managed like a CALL on its own premium; only the CE/PE choice follows the signal direction. 5 regression tests. |
| `0002-v2-indicators-and-backtest-runner.patch` | **Missing feature.** Real V2 runs passed an *empty* indicator provider, so the VWAP / Bollinger / KTMI / DMI triggers could never fire. Adds a causal indicator provider (`backtest/opening_breakout_v2_indicators.py`) and a fully configurable runner (`scripts/run_opening_breakout_v2_backtest.py`) that saves `trades.csv`, `equity_curve.csv`, `summary.json` and `config.json`. 12 tests, including an end-to-end run on a synthetic database. |

Nothing here places orders or contacts FYERS.

## How to apply (PowerShell, VS Code terminal)

```powershell
cd C:\Users\USER\Desktop\Kunal\KunalQuant
git pull origin main

cd .\kunal-quant-claude-version
git pull
cd ..

git apply --ignore-whitespace .\kunal-quant-claude-version\patches\0001-v2-put-is-long-premium.patch
git apply --ignore-whitespace .\kunal-quant-claude-version\patches\0002-v2-indicators-and-backtest-runner.patch

python -m pytest tests -q --ignore=tests/expiry_isolation_test.py
```

Expected last line: about `216 passed` with **0 failed** (with your
database present the 5 KTMI validation tests should also run).

If `git apply` says "patch does not apply", use the fallback instead: copy
everything inside `kunal-quant-claude-version\patches\files\` over the
KunalQuant folder (same sub-folders), then run the pytest line above.

```powershell
Copy-Item -Recurse -Force .\kunal-quant-claude-version\patches\files\* .
```

When the tests pass, commit them to canonical yourself:

```powershell
git add backtest scripts tests
git commit -m "Fix V2 PUT premium direction; add V2 indicator provider and backtest runner"
git push origin main
```
