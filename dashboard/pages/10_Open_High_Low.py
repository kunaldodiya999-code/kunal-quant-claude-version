"""Open High Low: F&O stocks where open = low (LONG) or open = high (SHORT) on spot AND futures, confirmed by the
option chain (11 strikes, calls and puts), checked for liquidity; the top 5 are paper-traded.

OFF by default; run it when you want it. Never places real orders. Guide: docs/OPEN_HIGH_LOW_STRATEGY.md
"""

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from data.open_high_low import COMMANDS, backtest, backtest_intervals, backtest_meta, status, store  # noqa: E402
from exit_inputs import reward_box, tsl_select  # noqa: E402
from paper_trading.tsl_methods import PRESETS  # noqa: E402
from strategies.exit_plan import TSL_LABELS, TSL_TRIGGERS  # noqa: E402
from strategies.open_high_low import CONFIRM, INSTRUMENTS  # noqa: E402
from theme import configure_page  # noqa: E402

FOLDER = "`C:\\Users\\USER\\Desktop\\Kunal\\kunal-quant-claude-version`"
configure_page("Open High Low")
st.title("Open High Low")
os_ = store()
s = os_.settings
st.caption(f"When the first {s.first_candle_minutes}-minute candle closes ({s.scan_at}): F&O stocks with OPEN = LOW "
           f"(LONG) or OPEN = HIGH (SHORT) on the stock or its future. Every match counts: stock, future and "
           f"{2 * s.strikes_each_side + 1} strikes of calls and puts (ATM, {s.strikes_each_side} ITM, "
           f"{s.strikes_each_side} OTM); the stock must be liquid. The {s.top_n} with the most matches are shortlisted; "
           "each is entered when the next candle crosses the first candle's HIGH (LONG) / LOW (SHORT). "
           "Research and paper only.")
if s.enabled:
    st.success(f"Strategy ON: the program paper-trades the top {s.top_n} ({s.instrument}).", icon="✅")
else:
    st.info("Strategy OFF (default): the program only shows the scan. Switch it on in Settings (or deploy it on the "
            "Strategies page).", icon="⏸️")

today_tab, settings_tab, backtest_tab = st.tabs(["Today", "Settings", "Backtest"])

with today_tab:
    live = status()
    if live is None:
        st.warning(f"No scan yet today. In VS Code, folder {FOLDER}, run:  `{COMMANDS['live']}`  "
                   f"(scan only, no trades: `{COMMANDS['scan']}`)")
    else:
        c1, c2, c3, c4 = st.columns(4)
        scan = live.get("scan") or []
        c1.metric("Open = high / low", len(scan))
        c2.metric("Pass every check", sum(1 for r in scan if r.get("passes")))
        c3.metric("Paper trades", len(live["trades"]))
        c4.metric("Paper P&L", f"₹{live['day_pnl']:,.0f}")
        st.caption(f"Scanned at {live.get('scanned_at') or '-'}; updated {live['updated_at']} IST. "
                   "matches = spot + future + calls + puts that agree (the more, the stronger; the top 5 have the most). calls / puts = how many of the 11 strikes show the same picture. Trades: WAITING = for the "
                   "breakout of the first candle; NO ENTRY = the next candle did not cross; CANCELLED = price went "
                   "past the open first.")
        if scan:
            st.markdown("**Scan (selected first)**")
            st.dataframe(pd.DataFrame(scan), hide_index=True, width="stretch", column_config={
                "match_count": None,
                "option_score": st.column_config.ProgressColumn("options agree %", min_value=0, max_value=100,
                                                                format="%.0f%%"),
                "fut_value_cr": st.column_config.NumberColumn("futures Rs cr", format="%.1f"),
                "liquidity": st.column_config.NumberColumn("liquidity", format="%.0f")})
        st.markdown("**Paper trades**")
        if live["trades"]:
            st.dataframe(pd.DataFrame(live["trades"]).drop(columns=["entry_epoch"], errors="ignore"),
                         hide_index=True, width="stretch")
        else:
            st.caption("None." if s.enabled else "None: the strategy is OFF (scan only).")

with settings_tab:
    with st.form("ohol_settings"):
        st.markdown("**Scan**")
        a1, a2, a3, a4, a5 = st.columns(5)
        enabled = a1.checkbox("Strategy ON (paper trades)", value=s.enabled, key="oh_enabled")
        first = a2.selectbox("First candle (minutes)", (1, 3, 5, 10, 15, 30),
                             index=(1, 3, 5, 10, 15, 30).index(s.first_candle_minutes), key="oh_first",
                             help="The scan is at its close (5 minutes = 09:20).")
        confirm = a3.selectbox("Spot and futures", CONFIRM, index=CONFIRM.index(s.confirm), key="oh_confirm",
                               format_func={"BOTH": "Both must agree", "EITHER": "One is enough"}.get)
        top_n = a4.number_input("Trade the top", 1, 50, int(s.top_n), 1, key="oh_top")
        exit_time = a5.text_input("Flat by (HH:MM)", s.exit_time, key="oh_exit")
        entry_candles = st.number_input("Entry: the next N candles may cross the first candle's high / low "
                                        "(1 = only the next candle)", 1, 20, int(s.entry_valid_candles), 1,
                                        key="oh_entry_candles")
        b1, b2, b3, b4, b5 = st.columns(5)
        tol = b1.number_input("Open = low/high within % (stock, future)", 0.0, 2.0, float(s.tolerance_pct), 0.01,
                              format="%.2f", key="oh_tol")
        otol = b2.number_input("Within % (options)", 0.0, 10.0, float(s.option_tolerance_pct), 0.1, key="oh_otol")
        each = b3.number_input("Strikes each side of ATM", 1, 10, int(s.strikes_each_side), 1, key="oh_each")
        min_opt = b4.number_input("Minimum options that must agree (0 = none)", 0, 42, int(s.min_option_matches), 1,
                                  key="oh_minopt")
        min_days = b5.number_input("Skip expiry closer than (days)", 0, 30, int(s.min_days_to_expiry), 1,
                                   key="oh_mindays")
        st.markdown("**Liquidity**")
        l1, l2, l3 = st.columns(3)
        fut_cr = l1.number_input("Futures traded since the open, at least (Rs crore)", 0.0, 10_000.0,
                                 float(s.min_fut_value_cr), 1.0, key="oh_futcr")
        spread_choices = (0.30, 0.50) if s.max_atm_spread_pct in (0.30, 0.50) else (0.30, 0.50, s.max_atm_spread_pct)
        spread = l2.selectbox("ATM CE / PE bid-ask spread, at most", spread_choices,
                              index=spread_choices.index(s.max_atm_spread_pct), format_func=lambda v: f"{v:.2f}%",
                              key="oh_spread", help="% of the option premium. With a tick of 0.05, a premium below "
                                                    "Rs 16.7 can never be within 0.30% (below Rs 10 for 0.50%).")
        opt_vol = l3.number_input("Total volume of the options, at least (0 = off)", 0, 10**9,
                                  int(s.min_option_volume), 1000, key="oh_optvol")
        st.markdown("**Trade**")
        t1, t2, t3, t4 = st.columns(4)
        instrument = t1.selectbox("Trade in", INSTRUMENTS, index=INSTRUMENTS.index(s.instrument), key="oh_instr",
                                  format_func={"STOCK": "Stock (intraday)", "FUTURE": "Future",
                                               "OPTION": "Option: buy ATM CE (long) / PE (short)"}.get)
        cap = t2.number_input("Stock: Rs per trade", 1000.0, 1e8, float(s.capital_per_trade), 5000.0, key="oh_cap")
        lots = t3.number_input("Future / option: lots", 1, 100, int(s.lots), 1, key="oh_lots")
        tf = t4.selectbox("TSL candles (minutes)", (1, 3, 5, 10, 15), index=(1, 3, 5, 10, 15).index(s.timeframe),
                          key="oh_tf")
        with st.expander("TSL numbers (both sides)"):
            tsl_params = {}
            for key, (_kind, defaults) in PRESETS.items():
                st.caption(TSL_LABELS[key])
                pcols = st.columns(len(defaults))
                values = {}
                for col, (name, default) in zip(pcols, s.long.method_params[key].items()):
                    wkey = f"oh_p_{key}_{name}"
                    if isinstance(default, bool):
                        values[name] = col.checkbox(name.replace("_", " "), value=default, key=wkey)
                    elif isinstance(PRESETS[key][1][name], int):
                        values[name] = int(col.number_input(name.replace("_", " "), 1, 500, int(default), 1, key=wkey))
                    else:
                        values[name] = float(col.number_input(name.replace("_", " "), 0.0, 10_000.0, float(default),
                                                              format="%.3f", key=wkey))
                tsl_params[key] = values
        st.caption("Exit: Reward 1:[box] = whole trade out at that target; EMPTY box = the TSL takes you out (candle "
                   "close beyond it). The stop is always the day's low (LONG) / high (SHORT) plus the buffer.")
        sides = {}
        cols = st.columns(2)
        for col, side, title in ((cols[0], "long", "LONG: open = low"), (cols[1], "short", "SHORT: open = high")):
            cfg = s.side(side.upper())
            with col:
                st.markdown(f"**{title}**")
                on = st.checkbox(f"{side.upper()} side on", value=cfg.enabled, key=f"oh_{side}_on")
                e1, e2, e3, e4 = st.columns(4)
                buf = e1.number_input("Stop buffer %", 0.0, 5.0, float(cfg.sl_buffer_pct), 0.05, key=f"oh_{side}_buf")
                rr = reward_box(e2, cfg.target_rr, key=f"oh_{side}_rr")
                tsl = tsl_select(e3, cfg.tsl_method, key=f"oh_{side}_tsl")
                trig = e4.selectbox("TSL exit when", TSL_TRIGGERS, index=TSL_TRIGGERS.index(cfg.tsl_trigger),
                                    format_func={"CLOSE": "Candle CLOSES beyond", "TOUCH": "Price TOUCHES"}.get,
                                    key=f"oh_{side}_trig")
                sides[side] = {"enabled": on, "sl_buffer_pct": buf, "target_rr": rr, "tsl_method": tsl,
                               "tsl_trigger": trig, "method_params": tsl_params}
        if st.form_submit_button("Save Open High Low settings"):
            try:
                os_.update(enabled=enabled, first_candle_minutes=int(first), entry_valid_candles=int(entry_candles),
                           confirm=confirm, top_n=int(top_n),
                           exit_time=exit_time.strip(), tolerance_pct=float(tol), option_tolerance_pct=float(otol),
                           strikes_each_side=int(each), min_option_matches=int(min_opt),
                           min_days_to_expiry=int(min_days), min_fut_value_cr=float(fut_cr),
                           max_atm_spread_pct=float(spread), min_option_volume=int(opt_vol), instrument=instrument,
                           capital_per_trade=float(cap), lots=int(lots), timeframe=int(tf), long=sides["long"],
                           short=sides["short"])
                st.success("Saved. The program uses it from its next start.")
            except ValueError as exc:
                st.error(f"Not saved: {exc}")

with backtest_tab:
    intervals = backtest_intervals()
    if not intervals:
        st.warning(f"No backtest yet. In VS Code, folder {FOLDER}, run:  `{COMMANDS['backtest']}`")
    else:
        q1, q2 = st.columns(2)
        interval = q1.radio("Data", intervals, horizontal=True, key="oh_bt_interval",
                            format_func={"1m": "1-minute (~29 days)", "5m": "5-minute (~60 days)"}.get)
        side = q2.radio("Side", ("BOTH", "LONG", "SHORT"), horizontal=True, key="oh_bt_side")
        meta = backtest_meta(interval) or {}
        st.info("Spot candles only: free history has no stock-futures or stock-option candles, so the futures and "
                "option checks are NOT in this test. Instead of the option score, candidates are ranked by "
                "liquidity (rupees traded the day before). The live program saves the full scan every day.")
        st.caption(f"{meta.get('stocks', '?')} stocks, {meta.get('first_day', '?')} to {meta.get('last_day', '?')}, "
                   f"first candle to {(meta.get('settings') or {}).get('scan_at', '?')}, top "
                   f"{(meta.get('settings') or {}).get('top_n', '?')}, Rs {float(meta.get('capital_per_trade', 50000)):,.0f}"
                   " per entry, net = after estimated charges.")
        summary = backtest("summary", interval)
        rows = summary[summary["side"] == side]
        st.dataframe(rows[["exit_plan", "trades", "win_rate_pct", "avg_win_r", "avg_loss_r", "expectancy_r",
                           "gross_pnl", "charges", "net_pnl", "max_drawdown"]], hide_index=True, width="stretch",
                     column_config={"exit_plan": "exit plan", "win_rate_pct": "win %", "expectancy_r": "avg R / trade",
                                    "net_pnl": st.column_config.NumberColumn("net Rs", format="%.0f"),
                                    "gross_pnl": st.column_config.NumberColumn("gross Rs", format="%.0f"),
                                    "max_drawdown": st.column_config.NumberColumn("worst drawdown Rs", format="%.0f")})
        study = backtest("top_n", interval)
        if study is not None:
            st.markdown("**Other 'trade the top N' choices** (both sides, net Rs)")
            piv = study.pivot_table(index="exit_plan", columns="top_n", values="net_pnl", aggfunc="sum")
            piv.columns = [f"top {c}" for c in piv.columns]
            st.dataframe(piv.round(0), width="stretch")
        trades = backtest("trades", interval)
        if trades is not None:
            with st.expander("Every trade"):
                st.dataframe(trades, hide_index=True, width="stretch")
