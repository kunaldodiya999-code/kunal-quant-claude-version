# Proposals

Code here is written against the canonical repo's real interfaces
(`OptionContractResolver`, `database.schema`) and tested against a
synthetic database, but has **not** been applied to
`kunaldodiya999-code/KunalQuant` and has **not** been run against real
data. Nothing here is a claim about the actual 198 unresolved / 16
no-entry-candle events from the 2026-09-24 checkpoint.

## `unresolved_event_classifier.py`

Adds a classification layer on top of what
`scripts/diagnose_option_data_coverage.py` already does in the canonical
repo, without touching `strategies/option_contract_resolver.py` (locked).
It distinguishes:

- `EXPIRY_NOT_FOUND` — resolver's `find_nearest_expiry()` failed
- `CONTRACT_NOT_FOUND` — resolver's `resolve()` failed after finding an
  expiry
- `NO_ENTRY_CANDLE` — contract resolved, but no option candle within 1h of
  the signal (the existing script already computes this, just never
  labeled it)
- `UNKNOWN` — anything that doesn't match the two known resolver error
  patterns

This only covers 3 of the brief's 9 categories (section 40), because
those are the only ones the resolver + this diagnostic can currently see.
`NO_OPTION_DATA`, `DATA_GAP`, `INVALID_SYMBOL`, `INSUFFICIENT_HISTORY`,
and `PARSER_FAILURE` would need signal from the acquisition/parsing layer
that this call site doesn't have.

## `test_classifier.py`

Builds a tiny synthetic database with `database.schema.initialize_database`
(the real schema code, so it can't drift from the actual table structure)
and 4 hand-crafted cases, one per reachable classification. Run:

```
KUNAL_QUANT_REPO=/path/to/KunalQuant python3 proposals/test_classifier.py
```

Result as of 2026-09-27: **4/4 synthetic cases pass.**

## `diagnose_option_data_coverage_v2.py`

A complete drop-in replacement for `scripts/diagnose_option_data_coverage.py`
that wires in `unresolved_event_classifier.py` and prints a per-category
breakdown instead of one "unresolved" pile. Same read-only guarantee as
the original. Syntax-checked (`py_compile`), but **not run end-to-end** —
`load_complete_3m_bars()` and the KTMI pipeline need the real database
this environment doesn't have. The part that changed behaviour (the
classifier) is the part that's actually tested, in `test_classifier.py`.

To try it against the real 198/16 events: drop this file and
`unresolved_event_classifier.py` into the canonical repo's `scripts/`
directory (or point `PYTHONPATH` at both) and run it in place of the v1
script.

## `fixes/`

Two real test-suite bugs found while running `tests/` on 2026-09-27, with
fixes and verification for each — see `fixes/README.md`. Neither has been
applied to the canonical repo.
