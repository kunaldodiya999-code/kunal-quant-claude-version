# Kunal Quant — Claude Session Start Checkpoint

Date: 2026-09-27

## Scope of this repo

This repo (`kunal-quant-claude-version`) is a separate working area for
Claude's contributions to the Kunal Quant project. The canonical repo,
`kunaldodiya999-code/KunalQuant`, is treated as read-only from here:
nothing in this checkpoint or repo modifies it.

## What was inspected

- Cloned `kunaldodiya999-code/KunalQuant` (read-only) and reviewed the full
  file tree, recent commit history, and the most recent checkpoint at
  `docs/checkpoints/2026-09-24_phase1_option_pipeline_checkpoint.md`.
- That checkpoint's own "Next investigation" step is: classify 198
  resolver-unresolved events and 16 no-entry-candle events from the latest
  `scripts/run_real_option_sample.py` run, then verify remaining option
  coverage gaps, before any further data acquisition or backtest expansion.
- Reviewed `scripts/diagnose_option_data_coverage.py` and
  `scripts/diagnose_option_candle_coverage.py`, which are the intended
  tools for that classification step.

## Test suite results (this environment)

Ran the full `tests/` suite here. This environment has no `.env`, no
`fyers_access_token.txt`, and no `data/` directory — all three are
correctly gitignored in the canonical repo and were not provided.

- **76 passed** — these do not depend on the local database or FYERS
  credentials, so they're a genuine, verified confirmation that the locked
  KTMI math, resolver, and lifecycle logic import and run correctly in a
  clean environment.
- **5 errors**, all in `tests/ktmi_fyers_validation_test.py`
  (`test_calculation_matrix`, `test_deterministic_execution`,
  `test_short_inversion`, `test_display_scaling`, `test_signal_engine`):
  each needs a pytest fixture named `bars` that isn't defined anywhere in
  the tracked code — there is no `conftest.py` in the repo at all. Either
  a `conftest.py` exists locally and was never committed, or these five
  tests are currently broken in the working environment too. Worth
  checking directly rather than assuming either way.
- **1 collection error**, `tests/expiry_isolation_test.py`: it runs a
  `sqlite3` query against a `gex_snapshots` table directly at module import
  time (not inside a test function), which fails outright without the real
  database. This also means this one file's failure blocks collection of
  the whole suite if run as `pytest tests/` without excluding it.

## Gap noticed in the coverage diagnostics

`scripts/diagnose_option_data_coverage.py` currently buckets events into
just "resolver-unresolved" (any `LookupError`) vs. "resolved" vs.
"resolved with/without a candle in 1h." It doesn't yet distinguish *why*
something is unresolved along the lines the project brief specifies
(`CONTRACT_NOT_FOUND`, `EXPIRY_NOT_FOUND`, `NO_OPTION_DATA`,
`NO_ENTRY_CANDLE`, `DATA_GAP`, `INVALID_SYMBOL`, `INSUFFICIENT_HISTORY`,
`PARSER_FAILURE`, `UNKNOWN`). Flagging this rather than changing it here,
since Resolver V2 and the diagnostics are working, locked-adjacent
components.

## What's blocking the actual classification step

The 198/16 events can only be classified against the real stored option
data (`data/database/kunal_quant.db`, ~39,626 candles) and a live FYERS
token — neither exists in this environment, correctly so. This needs one
of:

1. Run `python scripts/diagnose_option_data_coverage.py` and
   `python scripts/diagnose_option_candle_coverage.py` locally and share
   the output here, or
2. Some other way to point this environment at that data, if desired.

## No requirements.txt existed

Added one in this repo (`requirements.txt`), reverse-engineered from the
actual third-party imports (`fyers_apiv3`, `python-dotenv`, `requests`).
Versions reflect what this environment resolved on 2026-09-27, not
necessarily what's pinned locally — worth reconciling.
