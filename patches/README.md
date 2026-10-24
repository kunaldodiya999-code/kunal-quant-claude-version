# Patches 0001 and 0002 (Opening Breakout V2)

**Already applied in this repo** on branch `claude/affectionate-bardeen-3k5sls`
(commit `756d8f0`). You do not need to apply anything by hand.

| Patch | What it does |
|---|---|
| `0001-v2-put-is-long-premium.patch` | Fixes bought PUTs being simulated as short premium. |
| `0002-v2-indicators-and-backtest-runner.patch` | Real VWAP/BB/KTMI/DMI values plus `scripts/run_opening_breakout_v2_backtest.py`. |

The `.patch` files and `files/` folder are kept only so the same change can be
copied into the original `KunalQuant` repo later, if you ever approve that.
Do not commit anything in the `KunalQuant` folder for now.
