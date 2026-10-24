# Claude change log

Short, append-only record of what Claude changed, so every AI and the owner can see the state.
Newest entry first. Test counts are real runs; "needs local DB" errors/skips are the 5 candle-database tests.

## claude/affectionate-bardeen-3k5sls: Smart Money titles back, with style settings, 2026-10-25
- Owner wants SMC titles shown (OB, FVG, Premium/Discount, Strong/Weak ...) with settings: per title group
  (BOS/CHoCH, OB, FVG, zones, strong/weak, EQH/EQL, previous D/W/M levels) show on/off, size Tiny-Huge,
  placement (box: top/middle/bottom x left/center/right; line: Auto/above/below x left/center/right),
  text colour (same as element / white / custom). Box opacity for internal OB, swing OB, FVG, zones; OB border.
- Master switch renamed `titles` (default on) so old saved "off" choices do not hide them.

## claude/affectionate-bardeen-3k5sls: arrows only, title switches, full SMC / profile settings, 2026-10-25
- KTMI signals drawn as arrows only (no BUY CALL / BUY PUT text).
- Volume profile and Smart Money Concepts: "Show titles" switch (default off, owner style).
- Volume profile: TradingView style settings (VA up/down colours, opacity in/out of VA, POC / VA / high-low
  on/off with own colours, developing POC / VA colours). Old drawings get the new defaults.
- Smart Money Concepts: LuxAlgo setting groups (style, color candles, separate internal / swing / OB / FVG /
  zone colours, OB filter ATR or cumulative mean range, previous day / week / month high-low).
- Tests: indicator maths incl. previous-day levels (Node); browser check of the new dialogs.

## claude/affectionate-bardeen-3k5sls: cleaner chart text (owner request), 2026-10-25
- OI profile and volume profile values are written in white INSIDE the bars (only when they fit);
  strike labels outside the OI bars removed; max call/put OI = dotted line only, no title.
- No titles on the chart: removed POC/VAH/VAL/High/Low words, "OB", "FVG", "Swing OB", premium/discount
  and strong/weak words, the profile footer and the "KTMI Uni Lite" pane title. Lines and boxes stay.

## claude/affectionate-bardeen-3k5sls: TradingView-style chart, futures volume, indicators, 2026-10-24 (night)
- Runner saves per index: nearest-futures 1-minute candles WITH volume (warm-up history + live ticks via
  `vol_traded_today`), daily candles (+ futures daily volume), option-chain OI every minute
  (`paper_trading/chart_feeds.py`). Errors never stop trading.
- Chart (`dashboard/static/kq_chart.js`, `kq_indicators.js`): instant timeframes 1/3/5/10/15/30/60 min + 1D
  (KTMI per timeframe in Python, complete bars only), signals Both/Long/Short/Off, indicators menu with
  settings: futures volume, KTMI, VWAP (anchors, 1/2/3 SD or % bands), Bollinger (5 MA types), OI profile,
  Smart Money Concepts (BOS/CHoCH, OB, FVG, EQH/EQL, swing points, strong/weak, premium/discount).
  Tools per owner: horizontal, vertical, rectangle, path, measure, fixed-range volume profile
  (POC, VAH/VAL, high/low, up/down/total/delta, developing POC/VA). Trend line and fib removed.
- Live updates without reload: page writes `dashboard/static/live/*.json` every 10 s, chart polls
  (`enableStaticServing` in `.streamlit/config.toml`). Guide: `docs/CHART_GUIDE.md`.
- Checked in Chromium: all timeframes, indicators, settings dialogs, tools, persistence, live update.
  Indicator maths tested against Python (Node). Tests: 606 passed, 5 need local DB.

## claude/affectionate-bardeen-3k5sls: "Trade in" (one, several or all indexes) + Chart page with drawing tools, 2026-10-24
- `StrategySettings.trading_enabled` (default true) per index; coordinator rejects entries with the reason
  "Trading is switched off for this index"; refreshed per signal like Long/Short. Dashboard box "Trade in"
  (All indexes / pick), summary column; `paper_settings.py --trade ON|OFF`.
- Runner saves every 1-minute candle (warm-up + live) to `minute_candles.csv` per index
  (`paper_trading/minute_journal.py`, pipeline `minute_sink`), so the chart has the whole day.
- Dashboard page "Chart" (`dashboard/pages/7_Chart.py`): candles + locked KTMI Uni Lite (any timeframe) + arrows;
  tools trend line, horizontal, vertical, rectangle, path, fib retracement; select/drag/delete; saved in the
  browser per index. Library TradingView Lightweight Charts 4.2.3 stored in `dashboard/static` (npm shasum checked).
  Checked in Chromium: all six tools draw, drag moves, drawings survive reload, no page errors.
- Tests: 593 passed, 5 need local DB.

## claude/affectionate-bardeen-3k5sls: clean data sweep, KTMI accuracy, Opening Scalp (OFF), 2026-10-24
- Read the KunalQuant HFT plan/checkpoints (10s via NIFTY futures 5s, Gap-Open V1). Summary in
  `docs/OPENING_SCALP_AND_DATA.md` (the README for all of this).
- Data sweep `scripts/sweep_market_data.py` (Yahoo + FYERS: index, VIX, futures 1m/5s, option ladder) into
  `data/research/market_data.db`; clean-day rules `market_data/day_quality.py` (Yahoo dead tail cut).
  Yahoo: 17/18 clean 1m days, 37/39 5m, 486/490 60m per index.
- `scripts/ktmi_accuracy.py`: UNI_LITE_CORE on clean days, next-open entries. 17 days: direction ~40-51%,
  best PF 0.92-1.46. No proven edge on one month.
- `strategies/opening_scalp.py` (OFF, not wired live) + `scripts/opening_scalp_backtest.py` with walk-forward.
  Default ORB_CLOSE 10/50/stop<=20/BE20: 1m PF 4.0 (37 trades); 5m PF 1.28 (65, first half lost).
  Both scripts take `--source kq-db` for the 5-year KunalQuant NIFTY data.
- Dashboard page "Research Backtest" (`dashboard/pages/6_Research_Backtest.py`).
- Tests: 584 passed, 5 need local DB.

## claude/affectionate-bardeen-3k5sls: NIFTY + BANK NIFTY + SENSEX, Monday hardening, 2026-10-25
- `strategies/index_profiles.py` (checked against FYERS masters 2026-10-24): NIFTY gap 50 lot 65 weekly Tue;
  BANKNIFTY gap 100 lot 30 monthly; SENSEX (BSE_FO) gap 100 lot 20 weekly Thu. Lots/expiries read daily.
- Runner `--index` (default all three): one login, one shared FYERS socket (`paper_trading/shared_socket.py`
  routes ticks per index), per-index folders `data/paper_trading/<INDEX>`, `data/live_trading/<INDEX>`
  (switch file stays global), daily-cached NSE_FO/BSE_FO masters, old settings file carried over.
- Monday fixes found by reading the FYERS SDK: feed close used `close` (SDK: `close_connection`, could hang);
  SDK forgets subscriptions on reconnect -> hub re-subscribes everything; reconnect tries 5 -> 50;
  runner warns when an index has no price for > 60 s in market hours.
- `paper_settings.py --index`, `ktmi_check.py --index`; dashboard: all-index summary, index chooser,
  per-index order window/settings/journals. `docs/MONDAY_GUIDE.md`.
- Tests: 559 passed, 5 need local DB. Cost model still uses NSE exchange charges for SENSEX (approximate).

## claude/affectionate-bardeen-3k5sls: signal checker + broker orders (OFF), 2026-10-24 (night)
- Signal checker: session writes `ktmi_bars.csv` (every closed candle: OHLC, Long/Short speed+signal,
  arrows) via a `bar_sink` hook; `scripts/ktmi_check.py --date --timeframe` gives the same table for
  any past day (FYERS history or local DB). Test: live journal == checker on all 125 candles.
- `live_trading/`: limit+buffer order policy, FYERS gateway (fields per FYERS v3 docs), executor
  (re-price, entry cancel, exit left working + alert, NEVER market), mirror of paper opens/exits,
  one-day live switch (`scripts/live_switch.py`). Runner: DRY RUN by default; real orders need the
  switch armed today AND `--live-orders`. Dashboard: LIVE red banner, dry-run note, Broker orders tab.
- Found and fixed: float noise in tick rounding (0.1+0.2 rounded a BUY a tick too high).
- SEBI 2026: FYERS accepts API orders only from a whitelisted static IP -> see docs/LIVE_ORDERS.md.
- Tests: 27 new. Suite 549 passed, 5 need local DB. Market-order guard proven to fail when broken.

## claude/affectionate-bardeen-3k5sls: Monday live paper day, 2026-10-24 (evening)
- Order window: `strategies/strike_ladder.py` (1 ITM, ATM, 3 OTM per side; offset counts in the OTM
  direction, so ATM+1 = CALL one strike above ATM, PUT one strike below), call/put dropdowns and
  ATM / ATM+1 checkboxes in `strategy_settings.json`. Ticked boxes override the dropdowns; both ticked
  = two trades per signal via the new `PaperStrategyId.STRATEGY_A_2` slot. `StrikeLadderResolver`
  wraps the locked resolver (offset 0 = unchanged ATM path). Settings re-read every bar.
- Warm-up: `PaperMarketDataPipeline.seed_history` + `paper_trading/warmup.py` (FYERS 1m history,
  ~300 signal bars, closed minutes only).
- `scripts/run_paper_session.py`: login check, contracts + lot size + expiry from the FYERS symbol
  master into `data/database/paper_contracts.db` (original KunalQuant DB untouched), warm-up, live
  feed, 15:10 force exit, `live_status.json` every 2 s. Paper only, no order code.
- Dashboard `pages/0_Live_Paper_Trading.py` + `data/live.py`: status, positions, order window,
  settings, today's journals. Screenshot `docs/screenshots/live_paper_trading_page.png`.
- Tests: 37 new (strike 18, warm-up 9, runner 4, dashboard 6). Suite 522 passed, 5 need local DB.
- NOT done: real order placement (needs owner approval + limit/buffer exit adapter);
  BANKNIFTY/SENSEX; chart risk/reward box.

## claude/affectionate-bardeen-3k5sls: owner settings, 2026-10-24 (later)
- Timeframes 1, 3, 5, 10, 15, 30, 60 minutes (`market_data/resampling.py`, pipeline). Bars anchored at
  09:15 like TradingView; the day's last shorter bar (10m 15:25, 30m/60m 15:15) is kept and closes at 15:30.
  3m/5m output unchanged.
- Enter only after the signal candle closes: `PaperSignal.close_timestamp` (set by the pipeline);
  the coordinator rejects any decision before it.
- Long/Short/Both switch: `trade_direction` LONG (calls only) / SHORT (puts only) / BOTH. Switched-off
  signals are still journaled in `rejections.csv` with the reason.
- `paper_trading/strategy_settings.py` + `strategy_settings.json` (saved choice wins on restart):
  timeframe, direction, entry start (default 09:30), entry end (15:00), force exit (15:10).
  Owner command: `python scripts\paper_settings.py --timeframe 5 --direction BOTH --start 09:30 --end 15:00`.
- Tests: 29 new. Suite 485 passed (IST), 5 need local DB. Under TZ=UTC two pre-existing
  `test_dhan_client.py` session-quality tests fail on unchanged code too (timezone-dependent).

## claude/affectionate-bardeen-3k5sls (on top of claude/allocation-sizing), 2026-10-24
- KTMI Uni Lite saved and LOCKED in `indicators/ktmi_uni_lite/`: original Pine (SHA-256 test),
  compact Pine (139 vs 866 lines, same 32 inputs/plots/fills/arrows/alerts, test-compared),
  Python mirror (`config.py`, `signals.py`) checked against a line-by-line Pine transcription.
- Paper engine now uses Uni Lite: `PaperSessionConfig.signal_profile` default `UNI_LITE_CORE`
  (Long Speed crosses above +0.5 -> BUY CE, Short Speed crosses above +0.5 -> BUY PE, all else
  silent). Fixes 3 differences vs the chart: Long line on High (was Close), speed>signal and
  speed>0 required, TradingView crossover at the trigger. `LEGACY_UNIVERSAL` keeps the old path.
- Opening Breakout V2: bought PUTs were simulated as short premium (fixed); real VWAP/BB/KTMI/DMI
  values plus `scripts/run_opening_breakout_v2_backtest.py`.
- `CLAUDE.md` (session memory), `docs/KUNAL_QUANT_MASTER_SPEC.md`, `docs/AUDIT_2026-10-24.md`.
- Tests: 12 Uni Lite + 17 V2 new. Suite 456 passed, 5 need local DB.
- Open: no indicator warm-up at session start (audit section 8.1), next step.

## claude/allocation-sizing (on top of claude/switchable-exits)
- New `paper_trading/sizing.py`: budget -> whole lots. `lots = floor(budget / (premium x lot size))`,
  deployed = lots x cost per lot, budget is a hard ceiling (Decimal math: plain float division
  loses a lot in some exact cases, e.g. 402.50 at 16.10 x 25). Budget below one lot: no trade and a clear
  message with the shortfall. Percent presets 10..100 and a rupee box are two views of one setting
  (`AllocationSetting`): the last input used decides the mode, the other is derived. PERCENT follows the
  balance, AMOUNT stays fixed. Saved in `allocation.json`.
- Budget = chosen allocation capped by the balance and by cash not already deployed. Account snapshot now
  has `balance` (starting + realised - costs), `deployed` and `available_cash`.
- Initial stop default is now 30% below the premium paid (was 20%, the V1 value); the 3R target follows
  (entry + 3 x risk, i.e. 1.9 x entry). Both calls and bought puts have the stop BELOW entry. A stop above
  entry would only fit a short-sold option, which this engine never does.
- Refused entries are journaled in `rejections.csv` with the reason (duplicates are not repeated).
- New `paper_trading/overlays.py`: chart data per trade (entry marker LONG/SHORT, entry, initial stop,
  effective trailing stop, target, exit, R:R). The UI draws the box from this; nothing is drawn here.
- Tests: 26 new (sizing, two-way sync, engine sizing, overlays, rejection journal). Existing tests that
  assumed the 20% default now pin it explicitly. Suite 427 passed, 5 need local DB.
- Not done: the UI controls and the chart box themselves (next step), nothing yet calls the forced exit on a timer.

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
