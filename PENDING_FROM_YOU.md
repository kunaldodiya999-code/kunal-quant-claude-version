# Pending From You

_Updated 2026-09-28 after the handoff. Earlier items (diagnostics run, conftest question) are done or superseded._

## Waiting on you

1. **Send the finished output of the reference backtest** (`generate_no_lookahead_reference_backtest.py`). Nothing long-running or DB-writing happens before that.
2. **Check that output for `Accounting check: FAIL`.** If you see it, that is finding C1 in `docs/reviews/2026-09-28_reference_backtest_review.md`, and the results are invalid until `proposals/fixes/reference_backtest_keep_closed_trades.patch` is applied to the proposal script.

## Decisions only you can make

3. **C2 - SHORT side:** are SHORT signals meant to buy a put (long premium) or sell it? See the review.
4. **H1 - session:** keep 15:29 as the last candle, or use the date-aware calendar (15:39 from 2026-08-03)?
5. **GitHub token:** it is still in chat history. Delete it when this session ends and make a new one limited to `kunal-quant-claude-version` if we continue.
