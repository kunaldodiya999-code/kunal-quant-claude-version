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
- `NO_OPTION_DATA` — contract resolved, but that instrument has zero
  candles stored at all
- `DATA_GAP` — contract resolved, candles exist for that instrument
  elsewhere, just not within 1h of this specific signal
- `UNKNOWN` — a resolver LookupError that matches neither known message
  pattern

That's **5 of the brief's 9 categories** (section 40). `INVALID_SYMBOL`,
`INSUFFICIENT_HISTORY`, and `PARSER_FAILURE` remain out of reach from
this call site — they live in the acquisition/parsing layer
(`downloader/`, `instruments/expired_contract_registry.py`), not in
anything visible once a contract is already resolved and stored.

## `test_classifier.py`

Builds a tiny synthetic database with `database.schema.initialize_database`
(the real schema code, so it can't drift from the actual table structure)
and 5 hand-crafted cases, one per reachable classification. Run:

```
KUNAL_QUANT_REPO=/path/to/KunalQuant python3 proposals/test_classifier.py
```

Result as of 2026-09-27: **5/5 synthetic cases pass.**

## `diagnose_option_data_coverage_v2.py`

A complete drop-in replacement for `scripts/diagnose_option_data_coverage.py`
that wires in the classifier above and prints a per-category breakdown
instead of one "unresolved" pile. Same read-only guarantee as the
original. Syntax-checked (`py_compile`), but **not run end-to-end** —
`load_complete_3m_bars()` and the KTMI pipeline need the real database
this environment doesn't have. The part that changed behaviour (the
classifier) is the part that's actually tested.

To try it against the real 198/16 events: drop this file and
`unresolved_event_classifier.py` into the canonical repo's `scripts/`
directory (or point `PYTHONPATH` at both) and run it in place of the v1
script.

## `fixes/`

Two real test-suite bugs found while running `tests/` on 2026-09-27, with
fixes and verification for each — see `fixes/README.md`. Neither has been
applied to the canonical repo.

## `diagnose_required_contract_gaps.py`

Read-only real-data audit for the current `CONTRACT_NOT_FOUND` events. It reconstructs the unique required `(expiry, strike, CE/PE)` contracts, checks local instrument coverage, and queries FYERS only for missing expiries. It never registers instruments or downloads candles.

Run from the KunalQuant checkout with that checkout on `PYTHONPATH`:

```powershell
python .\kunal-quant-claude-version\proposals\diagnose_required_contract_gaps.py --json "$HOME\Desktop\contract_gap_audit.json"
```

## `diagnose_option_session_semantics.py`

Read-only audit of daily option-candle counts and first/last timestamps. This was added because the real diagnostic shows recent FYERS option samples with 385 candles through 15:39 while older data shows 375 through 15:29. It intentionally does not change the quality engine.

Run:

```powershell
python .\kunal-quant-claude-version\proposals\diagnose_option_session_semantics.py
```