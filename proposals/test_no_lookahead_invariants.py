"""
No-lookahead invariant tests for the indicator layer (synthetic data only,
no database, runs in a couple of seconds).

The invariant: an indicator/strategy value at bar i may depend only on bars
0..i. Equivalent, testable statement ("prefix invariance"): computing on
bars[:N] must give exactly the same values/events for every bar < N as
computing on the full series. Any whole-series statistic (global min/max
normalization, full-sample percentile, centered smoothing, reversed passes)
breaks this.

    KUNAL_QUANT_REPO=/path/to/KunalQuant python3 proposals/test_no_lookahead_invariants.py
"""

from __future__ import annotations

import math
import os
import random
import sys

REPO = os.environ.get("KUNAL_QUANT_REPO")
if not REPO:
    raise SystemExit("Set KUNAL_QUANT_REPO to a local KunalQuant clone first.")
sys.path.insert(0, REPO)

from backtest.ktmi_trigger_pipeline import run_ktmi_trigger_pipeline  # noqa: E402
from backtest.models import BacktestBar  # noqa: E402
from backtest.real_option_trade_runner import calculate_nifty_kama  # noqa: E402
from scripts.run_real_option_sample import build_ktmi_config  # noqa: E402


def synthetic_bars(n: int, seed: int) -> list[BacktestBar]:
    rng = random.Random(seed)
    price = 24000.0
    start = 1_780_000_000 - (1_780_000_000 % 180)
    bars = []
    for i in range(n):
        drift = 12 * math.sin(i / 40.0)          # slow waves so signals occur
        o = price
        c = o + drift + rng.uniform(-9, 9)
        h = max(o, c) + rng.uniform(0, 5)
        l = min(o, c) - rng.uniform(0, 5)
        bars.append(BacktestBar(timestamp=start + i * 180, open=o, high=h, low=l, close=c))
        price = c
    return bars


def main() -> None:
    failures = []

    def check(label, ok, extra=""):
        print(f"[{'PASS' if ok else 'FAIL'}] {label} {extra}")
        if not ok:
            failures.append(label)

    for seed in (1, 2, 3):
        full = synthetic_bars(900, seed)
        cut = 600
        prefix = full[:cut]

        # ---- KAMA ----------------------------------------------------
        k_full = calculate_nifty_kama(full)
        k_pref = calculate_nifty_kama(prefix)
        same = all(
            math.isclose(k_full[i].kama, k_pref[i].kama, rel_tol=0, abs_tol=1e-9)
            for i in range(cut)
        )
        check(f"seed {seed}: KAMA identical on prefix vs full series (bars 0..{cut - 1})", same)

        # ---- KTMI trigger events ---------------------------------------
        cfg = build_ktmi_config()
        e_full = run_ktmi_trigger_pipeline(full, cfg).events
        e_pref = run_ktmi_trigger_pipeline(prefix, cfg).events

        def key(e):
            return (e.index, e.strategy_id.value, e.direction.value)

        f_keys = sorted(key(e) for e in e_full if e.index < cut)
        p_keys = sorted(key(e) for e in e_pref)
        check(
            f"seed {seed}: KTMI events for bars <{cut} identical on prefix vs full",
            f_keys == p_keys,
            f"(full={len(f_keys)} prefix={len(p_keys)})",
        )
        check(f"seed {seed}: synthetic series actually produced signals (test is not vacuous)",
              len(f_keys) > 0)

    print()
    if failures:
        print(f"{len(failures)} FAILED")
        raise SystemExit(1)
    print("All no-lookahead invariants hold for the indicator layer (synthetic data).")


if __name__ == "__main__":
    main()
