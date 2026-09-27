# Pending From You

Running list — updated as things develop. Nothing here has been done yet
because it needs your local machine, your real data, or a decision only
you can make.

## Needs your local machine / real database

1. **Run the diagnostics, share the output.** Either the two original
   scripts or `proposals/diagnose_option_data_coverage_v2.py` (recommended
   — same inputs, adds the classification breakdown):
   ```
   python scripts/diagnose_option_data_coverage.py
   python scripts/diagnose_option_candle_coverage.py
   ```
   This is the one thing that turns everything in `proposals/` from
   "tested against synthetic data" into a real answer on the actual 198
   unresolved / 16 no-entry-candle events.

2. **Confirm the `bars` fixture question.** `tests/ktmi_fyers_validation_test.py`
   has no `conftest.py` anywhere in the repo providing a `bars` fixture.
   Either you have one locally that never got committed, or those 5 tests
   are broken in your normal environment too. Worth checking either way —
   see `proposals/fixes/README.md`.

## Decisions needed from you (no local machine required, just a call)

3. **Review the two test-suite fixes** in `proposals/fixes/` and decide
   whether to apply them to the canonical repo yourself, or have me do it
   once you're comfortable with what changed.

4. **Review the v2 diagnostic** and the classifier — decide whether the
   approach (reading the resolver's existing error messages, rather than
   changing the resolver itself) is the right one before it goes anywhere
   near the canonical repo.

5. **GitHub token scope**, from earlier: the current fine-grained token
   grants Read+Write to both `KunalQuant` and `kunal-quant-claude-version`
   together (one token, one permission level, applied to both repos you
   selected). I'm self-restricting to never write to `KunalQuant`, but if
   you want that as a hard technical guarantee rather than my word, edit
   the token to drop `KunalQuant` from its repo list, and generate a
   second, separate Read-only token just for `KunalQuant`. No rush.

## Possible next steps once you're back (not started, no decision needed yet)

- Extending the classifier past 5 of the brief's 9 categories —
  `INVALID_SYMBOL` and `PARSER_FAILURE` likely need signal from
  `downloader/chain_quality.py`'s `OptionChainQualityEngine` (already
  classifies contracts as COMPLETE/PARTIAL/EMPTY/FAILED using
  `download_jobs`), which hasn't been wired in yet.
