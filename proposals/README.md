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

## To actually try this against the real 198/16 events

In a local clone of `KunalQuant`, `diagnose_option_data_coverage.py`'s
`except LookupError:` block could be swapped for a call to
`classify_event(resolver, ...)` from this file, and the `unresolved`
bucket split into `EventClassification` groups instead of one pile. Happy
to write that patch as a diff once there's a way to test it against the
real database rather than synthetic data.
