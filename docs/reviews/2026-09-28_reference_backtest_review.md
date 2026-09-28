# Review — `generate_no_lookahead_reference_backtest.py` (commit 10a3664)

Static review plus small synthetic tests. No database access, no network,
no writes, nothing long-running. The reference script and the canonical
repo are untouched. Everything reproducible is in this repo:

| File | What it shows |
|---|---|
| `proposals/test_reference_backtest_regressions.py` | Reproduces finding C1 on the unmodified script; prints C2 |
| `proposals/fixes/reference_backtest_keep_closed_trades.patch` | The fix for C1 (dry-run applies cleanly; **not applied**) |
| `proposals/test_no_lookahead_invariants.py` | KAMA and KTMI events use no future bars |
| `proposals/session_calendar.py` + `test_session_calendar.py` | Date-aware session definition for finding H1 |

## What the review confirmed is correct

- **KAMA alignment.** `bisect_right(completions, ready) - 1` picks the latest
  3M bar whose completion is at or before the option candle's ready time.
  That matches the stated contract, and no forming bar is used.
- **Indicator layer has no lookahead.** Computing KAMA and the KTMI trigger
  events on `bars[:600]` gives values identical to the full 900-bar series
  for every bar below 600 (3 random seeds; signals occurred, so the test is
  not vacuous). Any whole-series normalisation would have broken this.
- **Entry mechanics.** Signal availability is bar start + 180 s. Entry is the
  first 1M candle strictly later, at its close. The entry candle is skipped
  as an exit candle. Stop-before-target ordering is in the locked lifecycle.

## C1 — CRITICAL: trades that close before the last event are never counted

Lines 237–241 rebuild `active` without the closed trades. `closed.append`
exists only once, at line 401, in the end-of-run loop. So any trade closed
by an earlier event's `advance_trade` is silently discarded from `closed`,
P&L, win rate, drawdown, exit reasons and the accounting check. The older
diagnostic (`diagnose_chronological_position_lifecycle.py`, lines 186–191)
collects closed trades inside the loop; this script lost that step (both
a987de8 and 10a3664).

Reproduced on the unmodified script: 2 events, trade #1 stopped out at
09:50, event #2 at 10:18. Expected closed=1/open=1. Got **closed=0/open=1,
accounted 1/2**. With the 6-line patch: closed=1/open=1, accounted 2/2.

**Symptom to look for in your running output:** `Accounting check: FAIL`,
or a closed-trade count far below the ~41 closed of the earlier
chronological diagnostic. Treat those results as invalid until patched.

## C2 — DECISION NEEDED (locked area, not touched): SHORT-side meaning

The strategy maps LONG → CE and SHORT → PE (Resolver V2), and
`option_trade_management.py:66-68` maps SHORT → `OptionTradeDirection.SHORT`.
That branch has stop = entry × 1.20, target below entry, P&L = entry − exit
(profit when the premium falls), i.e. the position is *sold* premium. Your
brief also says the system "attempts to buy complete option lots".

Real lifecycle code, synthetic candle: bearish signal, PE premium 100 → 125
(good for a bought put):

| Reading | Stop / target | Outcome |
|---|---|---|
| As coded (SHORT) | 120 / 40 | STOP_LOSS at 120, **−2,600** |
| Bought put (LONG) | 80 / 160 | gain of +3,250 on the same candle |

Section 22–23 of your brief do define stop/target rules for "SHORT option
positions", so this may be deliberate. But if SHORT signals are meant to
*buy* PEs, the whole SHORT side is inverted. Only you can say which is
intended. **Suggested check on real data later:** for SHORT trades, compare
option P&L sign against the underlying's move between entry and exit.

## H1 — HIGH: session is date-dependent (decision needed)

NSE moved the F&O close from 15:30 to 15:40 effective 2026-08-03. Your
option data shows 385 candles/day ending 15:39 from Aug 2026 (375 ending
15:29 in Nov 2024). The script hard-codes candle starts 09:15–15:29 and
`MARKET_CLOSE` 15:30, and the whole Aug–Sep 2026 sample falls after the
change. Consequences:

- the 13 "outside session" corrected signals may be tradable;
- stop/target/KAMA exits during 15:30–15:39 are invisible, so trades are
  carried overnight and exit at the next morning's price;
- `EXPECTED_1M_CANDLES = 375` style checks elsewhere will mislabel data.

Not verified: whether the NIFTY *index* 1M data also runs past 15:29. The
handoff fixed the session definition on purpose, so I only propose
`session_calendar.py`; adopting it is your call.

## H2 — HIGH before the 5-year run: lot size is a constant

`OptionTradeLifecycleConfig.lot_size = 65`. Fine for the recent sample; it
is not a historical lot size (brief section 6). Quantity, lots and P&L all
scale with it. Needs a per-date lot-size source before any older data.

## M — MEDIUM

- **M1 Drawdown and daily P&L use the wrong ordering/date.** `max_drawdown`
  runs over `closed` in list order (entry order in the end loop), not exit
  time. `daily_pnl` is keyed by *entry* date, not the date the P&L was
  realised (each partial exit has its own timestamp).
- **M2 Same-bar tie-break is implicit.** Events sort by `(index, timestamp)`,
  so A/B on one bar rely on input order. Add an explicit tie-break and a
  test (the handoff lists same-timestamp ordering).
- **M3 Timestamp labels.** Exits are recorded at the candle *start*, entry
  price is the candle *close*. Gating uses ready times correctly; holding
  times in reports are off by up to 60 s.
- **M4 Expiry registry.** Resolver takes the nearest *registered* expiry. Run
  the read-only `diagnose_instrument_registry.py` before the 5-year run to
  confirm no weekly expiries are missing (a hole makes it pick a far expiry).
- **M5 Overnight staleness.** The 15:27 bar completes at 15:30, so its KAMA
  decision cannot execute until the next morning (ties into H1).

## Low

Outside-session counts depend on check order (lifecycle rejection wins).
Candle cache does not assert strictly increasing timestamps (duplicate DB
rows would double-process a candle).

## Not verifiable here

Real-data behaviour; whether the index candles extend beyond 15:29; which
SHORT semantics you intend.

## Proposed next regression tests (once C1/C2/H1 are decided)

3M completion timing, entry timing, completed-bar KAMA, lifecycle state,
same-timestamp ordering, session boundaries (via `session_calendar.py`),
allocation rejection, plus "every event accounted exactly once".
