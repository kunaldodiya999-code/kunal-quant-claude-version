# Canonical Repo Audit — kunaldodiya999-code/KunalQuant

Date: 2026-09-28. Read-only clone, no writes. Covers everything pushed to
canonical since the last checkpoint I'd reviewed (`fcf826b`, 2026-09-25)
through `382ff3d` — 91 commits, mostly a new HFT 10-second data pipeline
and two new strategies (HFT Gap-Open V1, Opening Breakout V1/V2).

## Why this audit happened

None of this went through the proposal-repo-first review process the
project has otherwise followed — it landed directly in canonical. Worth
being direct about that as a process point. On substance, though, here's
what was actually found:

## What's reassuring

- **Zero diff on every locked file** — `indicators/ktmi/`,
  `strategies/option_contract_resolver.py`,
  `backtest/option_trade_lifecycle.py`,
  `backtest/option_trade_management.py` are byte-identical to `fcf826b`.
- **No order-placement code anywhere.** Searched broadly
  (`place_order`, `modify_order`, `cancel_order`, `.order(`,
  `order_type`, broker-submit patterns) across the whole repo: nothing.
  The new `execution/` module is explicitly, by its own docstring,
  "broker-neutral order intents... deliberately does not call FYERS" —
  an intent layer, not a live connection.
- **HFT Gap-Open V1 is documented Experimental, Default: DISABLED**
  (`docs/HFT_GAP_OPEN_STRATEGY_V1.md`) — the project's own "don't
  silently promote research to production" rule was followed here.
- **Tests: 141 passed** (up from 76), **same 5 pre-existing errors**
  (the `bars`-fixture bug in `ktmi_fyers_validation_test.py`, already
  reviewed and fixed in `proposals/fixes/` — unrelated to the new work,
  not made worse by it).
- **`download_hft_10s_data.py` defaults to dry-run** (`dry_run=not
  args.run`) — needs an explicit `--run` flag to actually hit the
  database, which is the right default.

## Not reassuring / worth your attention

- **No `requirements.txt` or `conftest.py` still.** Flagged in the
  first-session checkpoint, still true after 91 more commits.
- **`tests/expiry_isolation_test.py`** is still the non-test script that
  crashes `pytest tests/` on a naive run (must `--ignore` it) — the fix
  proposed earlier (rename out of pytest's discovery pattern) hasn't
  been applied.
- **Scope has grown well beyond the original KTMI-options brief** — an
  entirely new HFT data pipeline (10-second resolution) and two new
  strategies. Not unsafe by itself, but worth confirming this is the
  direction you actually want, since it's a lot of surface area added
  outside the review loop.

## Not checked in this pass

Line-by-line correctness of the new HFT/Opening-Breakout logic itself —
only its test status, locked-file isolation, and absence of live-order
code. A real logic review (same depth as the reference-backtest review)
would need to be scoped separately given the size (39+ new files).
