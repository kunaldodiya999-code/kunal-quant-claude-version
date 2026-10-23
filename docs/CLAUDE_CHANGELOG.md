# Claude change log

Short, append-only record of what Claude changed, so every AI and the owner can see the state.
Newest entry first. Test counts are real runs; "needs local DB" errors/skips are the 5 candle-database tests.

## claude/switchable-exits (on top of claude/live-equity-loss-cap)
- New `paper_trading/exit_manager.py`: exit rules as checkboxes. Tick any of the six trailing-stop
  methods (default: Chandelier ATR 9 x1.5 on the option premium). All six keep running in the shadow
  lab for every trade, so switching takes effect on the next candle with no warm-up. Also checkboxes:
  3R partial target (default on) and KAMA exit (default off). Choices persist in `exit_rules.json`,
  every change and trailing exit is logged in `exit_events.csv`.
- Rules: effective stop = tighter of initial stop and every ticked trailing stop; stop fills at the
  stop or the open if it gapped; highest stop wins when several hit; stop beats target in one candle;
  PSAR flips exit at the candle close; a method that already stopped out in shadow is "spent" and
  cannot drive the live trade. Trailing exits are journaled as STOP_LOSS (locked enum unchanged).
- Session now feeds completed option candles to the exit manager and supplies live option prices
  (freshness-checked) to the loss cap. `catch_up` rebuilds trailing state after a restart.
- `PaperTradingEngine.force_close` now accepts a timestamp equal to the last processed candle.
- Tests: 16 new. Suite 401 passed, 5 need local DB. Deliberate-break checks catch looser-stop-wins,
  lowest-stop-fills, spent methods, and ignored checkboxes.
- Limits: trailing methods only see candles from entry, so Chandelier has no stop for 9 candles.
  Nothing yet calls `close_due_positions` (forced 15:10 exit) on a timer; the runner will.

## claude/live-equity-loss-cap (on top of claude/kill-switch-segments)
- New `paper_trading/account.py`: live net liquidation value
  `equity = starting capital + realised + unrealised mark-to-market - costs`.
  Starting capital 100,000 by default; each day's opening balance is the previous close
  (starting capital + realised of earlier days - their costs).
- New `paper_trading/costs.py`: option costs, brokerage Rs 20/order, STT 0.15% sell side, NSE
  options exchange 0.03553% both sides, SEBI Rs 10/crore, stamp 0.003% buy side, GST 18%.
  Defaults taken from published Oct 2026 rates; verify against your broker's contract note.
- Daily loss cap now watches live equity, so open drawdowns count. Amount, percent of the
  day's opening equity, or both (stricter wins). Off by default. Trips: new entries stop for
  the IST day. With the cap on, entries are blocked if an open position has no live price.
- Equity is now force-exited at 15:10 like F&O. Commodity and currency never are.
- Coordinator accepts `marks_provider`; session builds `PaperAccount` (`PaperSessionConfig.starting_capital`, `cost_model`).
- Tests: 16 new/updated account and loss-cap tests, deliberate-break checks catch 6 money-logic faults. Suite 385 passed, 5 need local DB.
- Limits: exit costs of still-open positions are not estimated; unrealised P&L of a position carried
  past midnight is not in the next opening balance; nothing yet feeds live marks (the runner will).

## claude/kill-switch-segments (on top of claude/session-controls-1022-1233)
Owner rules applied to `paper_trading/controls.py` (replaces the first controls design):
- Kill switch has ONE action: stop NEW entries for 12 hours (`kill_hours`, configurable) in chosen
  segments: NSE & BSE F&O, Equity, Currency, Commodity, any mix, or all. Open positions are untouched.
  No resume and no flatten option; a kill can only be extended. Persists in `controls_state.json`
  (deleting that file by hand is the only override). Unreadable file fails closed.
- Entry window per segment. F&O default 09:30 to 15:00, forced exit 15:10 IST, all editable.
  Commodity and Currency: no forced exit, no entry cutoff set by controls. Equity: F&O entry window,
  no forced exit (owner did not specify; confirm).
- Daily loss limit OFF by default. Enter a rupee amount, a percent of `capital`, or both (stricter wins).
- Coordinator takes `segment` (default F&O). `close_due_positions` only touches segments that have a forced-exit time.
- Tests: 24 in tests/test_paper_controls.py; deliberate-break checks catch kill shortening,
  commodity force-exit, wrong loss-limit rule and segment-blind kills. Suite 368 passed, 5 need local DB.
- Still open: nothing calls `close_due_positions` on a timer; loss limit is gross realised only.

## claude/session-controls-1022-1233 (superseded by the entry above) (on top of claude/paper-restart-recovery)
- Added `paper_trading/controls.py`: entry window, daily realised-loss cap, forced exit, kill switch.
  Defaults 09:45 / 15:00 / 15:10 IST are CANDIDATES from the handover, not approved values.
- Kill switch persists in `controls_state.json` and fails closed if the file is unreadable.
  `HaltMode.BLOCK_ENTRIES` keeps managing open positions; `HaltMode.FLATTEN` closes them.
- Added `PaperTradingEngine.force_close` (reuses the existing END_OF_DATA reason; locked lifecycle untouched).
- Coordinator takes optional `controls`; session builds them from `PaperSessionConfig`.
- Tests: 10 new. Suite (TZ=Asia/Kolkata): 354 passed, 5 need local DB.
- Limits: daily loss is realised gross P&L only (no costs, no mark-to-market). Nothing calls
  `close_due_positions` on a timer yet: the runner must supply prices and call it.
- Added `scripts/apply_claude_patch.ps1` (apply patch on a new branch, test, push if green).

## claude/paper-restart-recovery
- Added `paper_trading/recovery.py`: rebuild open positions and seen signals from the journal.
- Tests: 11 new. Suite: 344 passed, 5 need local DB.
