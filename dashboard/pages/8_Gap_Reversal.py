"""Gap Reversal: big opening gaps (stocks and indexes) that reverse in the first candles.

Tabs: Today (live scanner), Settings (SHORT and LONG separately), Backtest, Chart (any marked setup with
its reversal strength). The strategy is OFF by default: the scanner still marks setups, paper trades start
only when it is switched ON. Never places real orders. Guide: docs/GAP_REVERSAL_STRATEGY.md
"""

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from chart_component import show_chart  # noqa: E402
from data.chart import ChartData, chart_payload  # noqa: E402
from data.gap_reversal import (  # noqa: E402
    COMMANDS, backtest, backtest_meta, live_minutes, research_minutes, status, store,
)
from strategies.gap_reversal import ENTRY_MODES, LONG_NAMES, PATTERNS, RR_CHOICES, SHORT_NAMES  # noqa: E402
from theme import configure_page  # noqa: E402

configure_page("Gap Reversal")
st.title("Gap Reversal")
gs = store()
s = gs.settings
st.caption(f"Gap of {s.gap_pct}% or more at the open, reversal setup in the first {s.window_5m} candles of 5 min "
           f"(or {s.window_3m} of 3 min). Gap up = SHORT setups, stop at the day's high; gap down = LONG setups, "
           "stop at the day's low. Research and paper only.")
if s.enabled:
    st.success("Strategy ON: the scanner paper-trades qualifying setups.", icon="✅")
else:
    st.info("Strategy OFF (default): the scanner only marks setups. Switch it on in Settings.", icon="⏸️")

today_tab, settings_tab, backtest_tab, chart_tab = st.tabs(["Today", "Settings", "Backtest", "Chart"])

# --------------------------------------------------------------------------- today
with today_tab:
    live = status()
    if live is None:
        st.warning("The scanner is not running. In VS Code, folder "
                   "`C:\\Users\\USER\\Desktop\\Kunal\\kunal-quant-claude-version`, run:  " f"`{COMMANDS['live']}`")
    else:
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Gap symbols", len(live["gaps"]))
        c2.metric("Setups marked", len(live["candidates"]))
        c3.metric("Paper trades", len(live["trades"]))
        c4.metric("Paper P&L", f"₹{live['day_pnl']:,.0f}")
        st.caption(f"Updated {live['updated_at']} IST")
        st.markdown("**Gaps today**")
        st.dataframe(pd.DataFrame(live["gaps"]), hide_index=True, width="stretch")
        st.markdown("**Reversal setups (strongest first)**")
        if live["candidates"]:
            frame = pd.DataFrame(live["candidates"]).drop(columns=["bar_time"], errors="ignore")
            st.dataframe(frame, hide_index=True, width="stretch",
                         column_config={"strength": st.column_config.ProgressColumn("strength %", min_value=0,
                                                                                    max_value=100, format="%.0f%%")})
        else:
            st.caption("No setup yet.")
        st.markdown("**Paper trades**")
        if live["trades"]:
            st.dataframe(pd.DataFrame(live["trades"]), hide_index=True, width="stretch")
        else:
            st.caption("None yet." if s.enabled else "None: the strategy is OFF.")

# --------------------------------------------------------------------------- settings
with settings_tab:
    with st.form("gap_reversal_settings"):
        st.markdown("**General**")
        g1, g2, g3, g4 = st.columns(4)
        enabled = g1.checkbox("Strategy ON (paper trades)", value=s.enabled, key="gr_enabled")
        gap_pct = g2.number_input("Gap at the open (%)", 0.5, 20.0, float(s.gap_pct), 0.5, key="gr_gap")
        timeframe = g3.selectbox("Candles", (3, 5), index=(3, 5).index(s.timeframe) if s.timeframe in (3, 5) else 1,
                                 format_func=lambda m: f"{m} minutes", key="gr_tf")
        include_idx = g4.checkbox("Also scan NIFTY, BANK NIFTY, SENSEX", value=s.include_indexes, key="gr_idx")
        h1, h2, h3, h4, h5 = st.columns(5)
        window_5m = h1.number_input("Setup window, 5-min candles", 1, 75, int(s.window_5m), key="gr_w5")
        window_3m = h2.number_input("Setup window, 3-min candles", 1, 125, int(s.window_3m), key="gr_w3")
        exit_time = h3.text_input("Flat by (HH:MM)", s.exit_time, key="gr_exit")
        capital = h4.number_input("Paper capital (₹)", 1000.0, 1e9, float(s.capital), 10000.0, key="gr_cap")
        alloc = h5.number_input("Per trade (% of capital)", 1.0, 100.0, float(s.allocation_pct), 1.0, key="gr_alloc")
        with st.expander("Setup rules (numbers)"):
            r1, r2, r3, r4, r5, r6 = st.columns(6)
            doji = r1.number_input("Doji body <= % of range", 1.0, 50.0, float(s.doji_body_pct), 1.0, key="gr_doji")
            wick = r2.number_input("Pin bar wick >= x body", 1.0, 10.0, float(s.wick_ratio), 0.5, key="gr_wick")
            zone = r3.number_input("At the extreme within %", 0.05, 5.0, float(s.top_zone_pct), 0.05, key="gr_zone")
            climax = r4.number_input("Climax volume >= x average", 1.0, 10.0, float(s.climax_volume_mult), 0.5,
                                     key="gr_climax")
            tweezer = r5.number_input("Tweezer tolerance %", 0.01, 2.0, float(s.tweezer_tol_pct), 0.05, key="gr_tw")
            dtop = r6.number_input("Double top tolerance %", 0.05, 3.0, float(s.double_top_tol_pct), 0.05, key="gr_dt")
        with st.expander("Reversal strength % (weights)"):
            w1, w2, w3, w4, w5 = st.columns(5)
            w_rej = w1.number_input("Rejection", 0.0, 100.0, float(s.w_rejection), 5.0, key="gr_wrej")
            w_abs = w2.number_input("Buyer/seller absorption", 0.0, 100.0, float(s.w_absorption), 5.0, key="gr_wabs")
            w_loc = w3.number_input("Location (extreme, VWAP)", 0.0, 100.0, float(s.w_location), 5.0, key="gr_wloc")
            w_conf = w4.number_input("Confirmation", 0.0, 100.0, float(s.w_confirmation), 5.0, key="gr_wconf")
            stretch = w5.number_input("VWAP stretch for full score (%)", 0.1, 10.0, float(s.stretch_full_pct), 0.1,
                                      key="gr_stretch")
        sides = {}
        cols = st.columns(2)
        for col, side, names, title in ((cols[0], "short", SHORT_NAMES, "SHORT after a gap UP"),
                                        (cols[1], "long", LONG_NAMES, "LONG after a gap DOWN")):
            cfg = s.side(side.upper())
            with col:
                st.markdown(f"**{title}**")
                on = st.checkbox(f"{side.upper()} side on", value=cfg.enabled, key=f"gr_{side}_on")
                a1, a2 = st.columns(2)
                min_strength = a1.number_input("Minimum strength %", 0.0, 100.0, float(cfg.min_strength), 5.0,
                                               key=f"gr_{side}_min")
                entry = a2.selectbox("Entry", ENTRY_MODES, index=ENTRY_MODES.index(cfg.entry_mode),
                                     format_func={"BREAK": "Price breaks the setup candle",
                                                  "CLOSE": "A candle closes beyond it"}.get, key=f"gr_{side}_entry")
                b1, b2, b3, b4 = st.columns(4)
                valid = b1.number_input("Entry within (candles)", 1, 20, int(cfg.entry_valid_bars), key=f"gr_{side}_valid")
                rr_value = float(cfg.target_rr)
                rr = b2.selectbox("Target", RR_CHOICES, index=RR_CHOICES.index(rr_value) if rr_value in RR_CHOICES else 1,
                                  format_func=lambda r: f"1:{r}", key=f"gr_{side}_rr")
                buffer = b3.number_input("Stop buffer %", 0.0, 5.0, float(cfg.sl_buffer_pct), 0.05, key=f"gr_{side}_buf")
                max_risk = b4.number_input("Max stop distance % (0 = any)", 0.0, 20.0, float(cfg.max_risk_pct), 0.5,
                                           key=f"gr_{side}_maxrisk")
                patterns = {p: st.checkbox(names[p], value=cfg.patterns[p], key=f"gr_{side}_{p}") for p in PATTERNS}
                sides[side] = {"enabled": on, "min_strength": min_strength, "entry_mode": entry,
                               "entry_valid_bars": int(valid), "target_rr": float(rr), "sl_buffer_pct": buffer,
                               "max_risk_pct": max_risk, "patterns": patterns}
        if st.form_submit_button("Save Gap Reversal settings"):
            try:
                gs.update(enabled=enabled, gap_pct=float(gap_pct), timeframe=int(timeframe), include_indexes=include_idx,
                          window_5m=int(window_5m), window_3m=int(window_3m), exit_time=exit_time.strip(),
                          capital=float(capital), allocation_pct=float(alloc), doji_body_pct=doji, wick_ratio=wick,
                          top_zone_pct=zone, climax_volume_mult=climax, tweezer_tol_pct=tweezer, double_top_tol_pct=dtop,
                          w_rejection=w_rej, w_absorption=w_abs, w_location=w_loc, w_confirmation=w_conf,
                          stretch_full_pct=stretch, short=sides["short"], long=sides["long"])
                st.success("Saved. The scanner uses it from its next start; the backtest from its next run.")
            except ValueError as exc:
                st.error(f"Not saved: {exc}")

# --------------------------------------------------------------------------- backtest
with backtest_tab:
    summary = backtest("summary")
    if summary is None:
        st.warning("No backtest yet. In VS Code, folder `C:\\Users\\USER\\Desktop\\Kunal\\kunal-quant-claude-version`, "
                   f"run:  `{COMMANDS['backtest']}`")
    else:
        meta = backtest_meta() or {}
        st.caption(f"Source {meta.get('source', '?')}, {meta.get('symbols', '?')} symbols, generated "
                   f"{meta.get('generated_at', '?')}. Results in R (1 R = the risk to the stop). First qualifying setup "
                   "per symbol and day; stop first if a candle touches stop and target.")
        st.dataframe(summary[summary["group"] == "ALL"], hide_index=True, width="stretch")
        with st.expander("By setup and by strength (break entry, 1:2)"):
            st.dataframe(summary[summary["group"] != "ALL"], hide_index=True, width="stretch")
        trades = backtest("trades")
        if trades is not None:
            with st.expander("Every trade"):
                st.dataframe(trades, hide_index=True, width="stretch")

# --------------------------------------------------------------------------- chart
with chart_tab:
    choices = []
    live = status()
    for c in (live or {}).get("candidates", []):
        choices.append(("today", c["symbol"], None, c))
    marked = backtest("candidates")
    if marked is not None:
        for _, row in marked.sort_values("strength", ascending=False).iterrows():
            choices.append(("backtest", row["symbol"], row["day"], row.to_dict()))
    if not choices:
        st.caption("No marked setups yet (run the scanner or the backtest).")
    else:
        labels = [f"{'Today' if src == 'today' else day} {sym} {c['side']} {c['time']} - {c['strength']:.0f}% "
                  f"({c['setups']})" for src, sym, day, c in choices]
        pick = st.selectbox("Setup", range(len(choices)), format_func=lambda i: labels[i], key="gr_chart_pick")
        src, sym, day, cand = choices[pick]
        if src == "today":
            minutes = live_minutes(sym)
            same = [c for c in live["candidates"] if c["symbol"] == sym]
            marks = [{"time": c["bar_time"], "side": c["side"], "text": f"{c['strength']:.0f}%"} for c in same]
        else:
            minutes = research_minutes(sym, day)
            from datetime import datetime
            from zoneinfo import ZoneInfo
            same = marked[(marked["symbol"] == sym) & (marked["day"] == day)]
            marks = [{"time": int(datetime.fromisoformat(f"{day} {r['time']}").replace(tzinfo=ZoneInfo('Asia/Kolkata'))
                                  .timestamp()), "side": r["side"], "text": f"{r['strength']:.0f}%"}
                     for _, r in same.iterrows()]
        if not minutes:
            st.caption("No candles saved for this setup.")
        else:
            data = ChartData(minutes, minutes, [], None, "stock volume")
            payload = chart_payload(data, index=sym.replace("NSE:", "").replace("-EQ", ""), show_days=1,
                                    timeframe=s.timeframe, marks=marks)
            st.caption("Yellow arrows = reversal setups with their strength %. Same chart tools and indicators as the "
                       "Chart page.")
            show_chart(payload, height=640)
