# Notes for Claude (read first, every session)

## The owner
- Kunal Quant owner, about 10% coding knowledge, on Windows + VS Code + PowerShell.
- Explain step by step, in plain words. One small step at a time.
- Always say WHICH folder a command runs in, with the full path.
- Never ask the owner to paste or re-share the KTMI code: it is in this repo.

## Folders on the owner's PC
- `C:\Users\USER\Desktop\Kunal\kunal-quant-claude-version`: the working copy. Use this one.
  It has its own `.venv`. Activate: `.\.venv\Scripts\Activate.ps1` (prompt must show `(.venv)`).
- `C:\Users\USER\Desktop\Kunal\KunalQuant`: the original repo. Read-only for Claude.
  It holds the real price database `data\database\kunal_quant.db`; this working copy has none
  (that is why 5 tests skip here).
- Tests: `python -m pytest tests -q --ignore=tests/expiry_isolation_test.py`
- Before telling the owner to pull: verify from a FRESH CLONE of the pushed branch (tests + every
  dashboard page via AppTest). A local pass can hide files git ignored (2026-10-24: `data/` rule
  hid `dashboard/data/live.py`; now only `/data/` is ignored).
- PUT ATM+1 = one strike further OTM (below ATM), confirmed by the owner 2026-10-24.

## LOCKED: KTMI Uni Lite (the strategy indicator)
- `indicators/ktmi_uni_lite/`; read `LOCKED.md` there.
- `KTMI_Uni_Lite_FINAL.pine` must never be edited (SHA-256 test).
- Current trading rule = profile `UNI_LITE_CORE`:
  Long Speed crosses above +0.5 -> BUY CE; Short Speed crosses above +0.5 -> BUY PE.
  Arrow = cross above trigger AND speed > signal AND speed > 0 (Pine `ta.crossover`).
  Everything else silent until the owner says otherwise.
- Bearish signal = BUY PUT (long premium). Never short-sell options.

## Other locked things
- `backtest/option_trade_lifecycle.py`: byte-for-byte unchanged.
- `indicators/ktmi/` (KTMI Universal engine): do not change calculations.
- Real orders: `live_trading/`, OFF by default. Need BOTH `scripts/live_switch.py arm` (today only)
  AND `run_paper_session.py --live-orders`. Limit + buffer only, NEVER market (test-guarded).
  FYERS requires a whitelisted static IP for API orders (SEBI 2026). See docs/LIVE_ORDERS.md.
- KTMI checker for any past day: `python scripts\ktmi_check.py --date YYYY-MM-DD --timeframe 3`.

## Where things are
- Full specification from the owner: `docs/KUNAL_QUANT_MASTER_SPEC.md`.
- Project handover and roadmap: `docs/KUNAL_QUANT_PROJECT_HANDOVER.md`.
- Change log of Claude's work: `docs/CLAUDE_CHANGELOG.md` (append, newest first).
- Paper engine: `paper_trading/` (session.py is the composition root).
- Owner's paper settings (timeframe 1/3/5/10/15/30/60, LONG/SHORT/BOTH, entry start/end, force exit),
  per index: `scripts/paper_settings.py --index`, saved in `data/paper_trading/<INDEX>/strategy_settings.json`.
  Owner prefers 3 or 5 minutes. Entry start 09:30. Entries only after the signal candle closes.
- Order window (owner rule): 5 strikes per side (1 ITM, ATM, 3 OTM); CALL/PUT dropdowns; ATM and
  ATM+1 checkboxes override dropdowns, both = two trades. `strategies/strike_ladder.py`.
- Indexes: NIFTY, BANKNIFTY, SENSEX (`strategies/index_profiles.py`). One runner process trades all
  (`--index` to choose), one shared FYERS socket; per-index folders data/paper_trading/<INDEX>.
- Trading day: see docs/MONDAY_GUIDE.md. `python scripts\run_paper_session.py` (window 1) +
  `cd dashboard; streamlit run app.py` (window 2, page "Live Paper Trading").
  Daily FYERS login first: `python fyers_auth.py` in the folder holding `.env` (likely KunalQuant).
- Research (2026-10-24): `docs/OPENING_SCALP_AND_DATA.md`. Data sweep `scripts/sweep_market_data.py`,
  KTMI accuracy `scripts/ktmi_accuracy.py`, Opening Scalp `strategies/opening_scalp.py` (OFF, not wired live),
  backtest `scripts/opening_scalp_backtest.py`; both take `--source kq-db` (5-year NIFTY). Dashboard page
  "Research Backtest". Results live in data/research (local only).
- "Trade in" (2026-10-24): per-index `trading_enabled` in strategy_settings.json; dashboard box on
  Live Paper Trading; runner still watches all indexes started with `--index`.
- Chart page `dashboard/pages/7_Chart.py` (docs/CHART_GUIDE.md): `dashboard/static/kq_chart.js` + `kq_indicators.js`;
  data `dashboard/data/chart.py`; runner saves futures volume / daily / OI (`paper_trading/chart_feeds.py`).
  OWNER RULE: index has no volume -> always use nearest FUTURES volume on the spot chart.
  Owner's tools: horizontal, vertical, rectangle, path, measure, volume profile (no trend line / fib).
  OWNER STYLE: no titles on the chart (lines only); bar values in WHITE INSIDE the bars, never outside.
  Exception (owner 2026-10-25): Smart Money titles ON by default, every title group styleable
  (size, placement, colour) and boxes have opacity settings. Volume profile titles: "Show titles" switch
  (default off). KTMI signals = arrows only, no text. OI values white inside bars, no titles.
- TSL / trade management (2026-10-25): `docs/TSL_AND_TRADE_MANAGEMENT.md`. Settings per index in
  `trade_management.json` (dashboard form), nothing hard-coded, snapshot per trade (new trades only).
  Owner answers: after 2R -> breakeven then TSL; exit on candle CLOSE; TSL candles = strategy TF; TSL chart
  OPTION (default) or SPOT dropdown. Methods: Chandelier everget 9x1.5 (default), Supertrend 5x1 / 7x1.5,
  PSAR 0.02/0.02/0.2 and 0.04/0.04/0.1, point trail 10/15. No Donchian / rolling-swing; KAMA not a TSL.
  Compare: live "TSL comparison" tab, `scripts/tsl_lab.py`, `scripts/tsl_check.py`.
- HFT Gap-Open: research only, OFF. PUT mirrored (Open=High, break low, stop setup high, PE ladder ATM..-250).
  Audit `docs/HFT_GAP_OPEN_AUDIT.md`.
- Gap Reversal (2026-10-25): `docs/GAP_REVERSAL_STRATEGY.md`. Gap >= 3% (setting) -> reversal setup in first 10x5m /
  16x3m candles; 10 setups (sheet `docs/reversal_setups.png`, owner approved "build with all 10"), LONG/SHORT separate,
  strength % (rejection/absorption/location/confirmation), stop = day's high/low, RR 1.5/2/2.5/3, entry BREAK or CLOSE
  (owner: both switchable). Universe ALL F&O stocks (+ indexes). Owner plan: scanner + paper first, later cash MIS,
  then maybe CE/PE. OFF by default. `scripts/run_gap_reversal.py`, `scripts/gap_reversal_backtest.py`, page "Gap Reversal".
  Daily trade cap (owner 2026-10-25): max_trades_per_day 5 (+ per side), order = entry time then strength (`daily_cap`).
  Earliest entry `entry_from` default 09:15 (owner tried 09:40, set back); a stock trades the qualifying setup that ENTERS first (`first_entry`).
- Exit plan, EVERY strategy (owner 2026-10-25): `strategies/exit_plan.py`. "Reward 1:[box]": number = whole trade
  out at 1:number; EMPTY = no target, TSL (owner's presets) exits on candle CLOSE beyond it. KTMI: `exit_target_rr` in
  trade_management.json (empty default keeps partial 2R + TSL). Gap Reversal: per side target_rr/tsl_method.
  Form widget `dashboard/exit_inputs.py`. A new strategy must use ExitPlan.
- Deploy (owner 2026-10-25): single / several / all strategies. `strategies/registry.py` (KTMI_UNI_LITE, GAP_REVERSAL
  = PAPER; OPENING_SCALP, HFT_GAP_OPEN = RESEARCH, not deployable). Saved in data/strategies.json (Gap Reversal =
  its "Strategy ON"). One command `python scripts\run_strategies.py`; page "Strategies". run_paper_session exits if
  KTMI not deployed. A new live strategy = add it to the registry + launcher.
- Open High Low (owner 2026-10-25): `docs/OPEN_HIGH_LOW_STRATEGY.md`, `strategies/open_high_low.py`. F&O stocks;
  LONG open=low, SHORT open=high on spot OR future (owner: one is enough = EITHER default, BOTH = stricter switch);
  11 strikes (ATM, 5 ITM, 5 OTM) calls + puts: LONG = calls open=low + puts open=high (SHORT opposite); NO minimum,
  every match counts: matches = spot + fut + calls + puts (/24); liquidity: futures value, ATM bid-ask spread LESS THAN 2% of
  the mid price (owner; dropdown 0.3-5%; avoid e.g. bid 15 / ask 20); top 5 by matches then liquidity. Scan at the close of the first 5-min candle (09:20); entry when the NEXT candle
  crosses its high (LONG) / low (SHORT), owner 25 Oct (`breakout`; cancelled if price passes the open first). OFF by default. Instrument STOCK / FUTURE / OPTION (buy CE / PE).
  `scripts/run_open_high_low.py` (--scan-only), page "Open High Low", registry OPEN_HIGH_LOW (deploy = its enabled).
  Backtest spot-only (no free stock F&O history). Shared post-entry engine `strategies/trade_sim.py` (Gap Reversal too).
- Reward box is a TEXT input (`dashboard/exit_inputs.py`): a Streamlit number box cannot be emptied once filled.
- Time Machine (owner 2026-10-25): `docs/TIME_MACHINE.md`, `strategies/time_machine.py` (bootstrap of the stock's own
  5-min candles by time of day, run through trade_sim with the real exit plan). OFF the chart: a "time machine" column +
  a closed box on Gap Reversal / Open High Low (owner: no lines on the chart, just %). Information only, NEVER a filter:
  check (`scripts/time_machine_check.py`) showed target chances rank right but cautious; win chance did not pick winners.
  On demand: `scripts/time_machine.py`. Live programs fetch 90 d of 5-min per symbol (`--no-odds` off).
- OWNER RULE: when the owner says "we are done for the day", give ALL commands to run on their PC in order,
  step by step (folder for each), with what each one should show, plus everything still pending from their side.
