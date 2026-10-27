"""Live Paper Trading: NIFTY, BANK NIFTY and SENSEX status, order window, settings, journals.

Start the trading program first (separate window):
    python scripts\\run_paper_session.py
This page reads its live status files and saves your settings. It never places orders.
"""

import sys
from datetime import time as dtime
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from data.live import (  # noqa: E402
    INDEX_KEYS, STALE_AFTER_SECONDS, journal, live_dir, load_status, manual_stops, paper_dir, set_manual_stop,
    set_trading_indexes, settings_store, status_age_seconds, strike_options, summary_rows, trade_store,
    trading_indexes,
)
from paper_trading.trade_management import (  # noqa: E402
    AFTER_PARTIAL, ALLOCATION_BASES, LABELS, ONE_LOT_AT_TARGET, TSL_MODES, TSL_SOURCES, TSL_TIMEFRAMES, TSL_TRIGGERS,
)
from paper_trading.tsl_methods import PRESETS  # noqa: E402
from exit_inputs import reward_box  # noqa: E402
from paper_trading.sizing import AllocationSetting, AllocationStore  # noqa: E402
from strategies.index_profiles import INDEX_PROFILES  # noqa: E402
from theme import configure_page  # noqa: E402

configure_page("Live Paper Trading")
st.title("Live Paper Trading")
st.success("PAPER MODE: real FYERS prices, simulated trades.", icon="🧪")

TIMEFRAMES = (1, 3, 5, 10, 15, 30, 60)
DIRECTIONS = {"BOTH": "Both (calls and puts)", "LONG": "Long only (BUY CALL)", "SHORT": "Short only (BUY PUT)"}


@st.fragment(run_every=3)
def overview() -> None:
    st.subheader("All indexes")
    rows = summary_rows()
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    if not any(r["Running"] == "Yes" for r in rows):
        st.warning(
            "The trading program is not running (no fresh status). In VS Code, folder "
            "`C:\\Users\\USER\\Desktop\\Kunal\\kunal-quant-claude-version`, run:  "
            "`python scripts\\run_paper_session.py`",
            icon="⏸️",
        )
    if any(r["Orders"] == "LIVE" for r in rows):
        st.error("LIVE ORDERS ARE ON: paper trades are also being sent to FYERS with real money.", icon="🚨")
    elif any(r["Orders"] == "DRY_RUN" for r in rows):
        st.info("Broker orders: DRY RUN. Orders that would be sent are listed in the 'Broker orders' tab; "
                "nothing is sent to FYERS.", icon="🛡️")


overview()

# ---------------------------------------------------------------------- trade in
st.subheader("Trade in")
st.caption("Choose one, several or all indexes. Each chosen index takes entries on its own KTMI Uni Lite "
           "signals. Indexes not chosen are still watched (prices, KTMI, chart) but take no new trades. "
           "Applies to the next signal; open trades are always managed to their exit.")
with st.form("trade_in"):
    chosen_now = trading_indexes()
    all_box = st.checkbox("All indexes", value=len(chosen_now) == len(INDEX_KEYS), key="trade_in_all")
    picked = st.multiselect("Indexes to trade", INDEX_KEYS, default=chosen_now,
                            format_func=lambda k: INDEX_PROFILES[k].label, key="trade_in_pick")
    if st.form_submit_button("Save trade-in choice"):
        chosen = list(INDEX_KEYS) if all_box else picked
        set_trading_indexes(chosen)
        if chosen:
            st.success("Trading in: " + ", ".join(INDEX_PROFILES[k].label for k in chosen))
        else:
            st.warning("No index chosen: the program watches but takes no new trades.")

st.markdown("---")
index = st.radio("Index", INDEX_KEYS, format_func=lambda k: INDEX_PROFILES[k].label, horizontal=True, key="index")
label = INDEX_PROFILES[index].label


@st.fragment(run_every=3)
def live_panel(index: str) -> None:
    status = load_status(index)
    age = status_age_seconds(status)
    if status is not None and (age is None or age > STALE_AFTER_SECONDS):
        st.caption(f"{label}: last update is old ({status.get('updated_at')}); the program may have stopped.")
    feed = (status or {}).get("feed") or {}
    account = (status or {}).get("account") or {}
    ladders = (status or {}).get("ladders") or {}
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("FYERS feed", "Connected" if feed.get("connected") else "Not connected")
    c2.metric(f"{label} spot", f"{status['spot']:,.2f}" if status and status.get("spot") else "-")
    c3.metric("ATM strike", ladders.get("atm", "-"))
    c4.metric("Equity (paper)", f"₹{account['equity']:,.0f}" if account else "-")
    c5.metric("Day P&L", f"₹{account['day_pnl']:,.0f}" if account else "-")
    if status:
        contracts = status.get("contracts") or {}
        st.caption(
            f"Updated {status.get('updated_at')} IST · spot time {status.get('spot_time') or '-'} · "
            f"expiry {contracts.get('nearest_expiry', '-')} · lot size {contracts.get('lot_size', '-')}"
            + (f" · feed message: {feed['last_error']}" if feed.get("last_error") else "")
        )
    st.subheader(f"Open paper positions: {label}")
    positions = (status or {}).get("positions") or []
    if positions:
        st.dataframe(pd.DataFrame(positions), hide_index=True, width="stretch")
    else:
        st.caption("No open paper positions.")


live_panel(index)

store = settings_store(index)
current = store.settings
status = load_status(index)

# ------------------------------------------------------------------ order window
st.markdown("---")
st.subheader(f"Order window: which {label} strike to buy")
st.caption(f"5 strikes from the live {label} spot: 1 ITM, ATM, 3 OTM. Changes apply to the next signal.")
with st.form(f"order_window_{index}"):
    left, right = st.columns(2)
    call_opts, put_opts = strike_options(status, "call"), strike_options(status, "put")
    with left:
        call_choice = st.selectbox(
            "CALL strike (Long Speed signal)", [c for c, _ in call_opts],
            index=[c for c, _ in call_opts].index(current.call_strike),
            format_func=dict(call_opts).get, key=f"call_strike_{index}",
        )
    with right:
        put_choice = st.selectbox(
            "PUT strike (Short Speed signal)", [c for c, _ in put_opts],
            index=[c for c, _ in put_opts].index(current.put_strike),
            format_func=dict(put_opts).get, key=f"put_strike_{index}",
        )
    b1, b2 = st.columns(2)
    use_atm = b1.checkbox("ATM strike (calls and puts)", value=current.use_atm, key=f"use_atm_{index}")
    use_plus1 = b2.checkbox("ATM+1 strike (calls and puts)", value=current.use_atm_plus_1,
                            key=f"use_atm_plus_1_{index}")
    st.caption(
        "Ticked boxes override the dropdowns. ATM only = enter ATM. ATM+1 only = one strike out of the money "
        "(CALL: one strike above ATM, PUT: one strike below ATM). Both ticked = two trades per signal."
    )
    a1, a2 = st.columns(2)
    auto = a1.checkbox("AUTO: ATM or ATM+1, whichever buys MORE lots", value=current.strike_mode == "AUTO_ATM_ATM1",
                       key=f"strike_auto_{index}",
                       help="Never beyond ATM+1. Equal lots: ATM. Overrides the dropdowns and the boxes above.")
    lot_cap = a2.number_input("Max cost of 1 lot (Rs, 0 = no cap)", 0.0, 1e7, float(current.max_lot_cost), 500.0,
                              key=f"max_lot_cost_{index}",
                              help="Owner rule for NIFTY: Rs 8,000. A strike whose 1 lot costs more is not bought.")
    st.caption("Example: Rs 15,000 free, cap Rs 8,000: ATM at 135 (Rs 8,775 a lot) is skipped, ATM+1 at 115 "
               "(Rs 7,475 a lot) buys 2 lots. Live orders: the money = the real FYERS available balance.")
    if st.form_submit_button("Save order window"):
        store.update(call_strike=call_choice, put_strike=put_choice, use_atm=use_atm, use_atm_plus_1=use_plus1,
                     strike_mode="AUTO_ATM_ATM1" if auto else "MANUAL", max_lot_cost=float(lot_cap))
        st.success(f"Saved for {label}. Applies to the next signal.")

# ---------------------------------------------------------------------- settings
st.markdown("---")
st.subheader(f"Strategy settings: {label} (KTMI Uni Lite core)")
with st.form(f"strategy_settings_{index}"):
    c1, c2 = st.columns(2)
    timeframe = c1.selectbox("Timeframe (minutes)", TIMEFRAMES, index=TIMEFRAMES.index(current.timeframe_minutes),
                             key=f"timeframe_{index}")
    direction = c2.radio("Trade direction", list(DIRECTIONS), index=list(DIRECTIONS).index(current.trade_direction),
                         format_func=DIRECTIONS.get, horizontal=True, key=f"direction_{index}")
    t1, t2, t3 = st.columns(3)
    start = t1.time_input("New trades from", dtime.fromisoformat(current.entry_start), step=60, key=f"start_{index}")
    end = t2.time_input("No new trades from", dtime.fromisoformat(current.entry_end), step=60, key=f"end_{index}")
    force = t3.time_input("Force exit at", dtime.fromisoformat(current.force_exit), step=60, key=f"force_{index}")
    st.caption("Entries happen only after the signal candle has closed. "
               "A timeframe change applies when the trading program is restarted; the rest apply to the next signal.")
    if st.form_submit_button("Save settings"):
        try:
            store.update(timeframe_minutes=int(timeframe), trade_direction=direction,
                         entry_start=start.strftime("%H:%M"), entry_end=end.strftime("%H:%M"),
                         force_exit=force.strftime("%H:%M"))
            st.success(f"Saved for {label}.")
        except ValueError as exc:
            st.error(f"Not saved: {exc}")

# ------------------------------------------------------------ trade management / TSL
st.markdown("---")
st.subheader(f"Trade management and trailing stop (TSL): {label}")
st.caption("Changes apply to NEW trades only; every open trade keeps the settings it was opened with. "
           "Defaults = your requirements brief. Nothing here places orders.")
tm_store = trade_store(index)
tm = tm_store.settings
TF_TEXT = {"STRATEGY": f"Same as strategy ({current.timeframe_minutes} min)", **{t: f"{t} min" for t in TSL_TIMEFRAMES[1:]}}
with st.form(f"trade_management_{index}"):
    st.markdown("**Exit: target or trailing stop**")
    a0, a1, a2, a3 = st.columns(4)
    reward = reward_box(a0, tm.exit_target_rr, key=f"tm_reward_{index}")
    initial_sl = a1.number_input("Initial stop-loss (% of option premium)", 1.0, 99.0, float(tm.initial_sl_pct), 1.0,
                                 key=f"tm_sl_{index}")
    tsl_on = a2.checkbox("TSL on", value=tm.tsl_enabled, key=f"tm_tsl_on_{index}")
    mode = a3.selectbox("TSL mode", TSL_MODES, index=TSL_MODES.index(tm.tsl_mode), format_func=LABELS.get,
                        key=f"tm_mode_{index}")
    b1, b2, b3, b4 = st.columns(4)
    method = b1.selectbox("TSL method", list(PRESETS), index=list(PRESETS).index(tm.tsl_method), format_func=LABELS.get,
                          key=f"tm_method_{index}")
    source = b2.selectbox("Calculate TSL on", TSL_SOURCES, index=TSL_SOURCES.index(tm.tsl_source),
                          format_func=LABELS.get, key=f"tm_source_{index}")
    tsl_tf = b3.selectbox("TSL candles", TSL_TIMEFRAMES, index=TSL_TIMEFRAMES.index(tm.tsl_timeframe),
                          format_func=TF_TEXT.get, key=f"tm_tf_{index}")
    trigger = b4.selectbox("Exit when", TSL_TRIGGERS, index=TSL_TRIGGERS.index(tm.tsl_trigger), format_func=LABELS.get,
                           key=f"tm_trigger_{index}")
    with st.expander("Numbers of every TSL method (change any value)"):
        params = {}
        for key, (_kind, defaults) in PRESETS.items():
            st.caption(LABELS[key])
            cols = st.columns(len(defaults))
            values = {}
            for col, (name, default) in zip(cols, tm.method_params[key].items()):
                widget_key = f"tm_p_{index}_{key}_{name}"
                if isinstance(default, bool):
                    values[name] = col.checkbox(name.replace("_", " "), value=default, key=widget_key)
                elif isinstance(PRESETS[key][1][name], int):
                    values[name] = int(col.number_input(name.replace("_", " "), 1, 500, int(default), 1, key=widget_key))
                else:
                    values[name] = float(col.number_input(name.replace("_", " "), 0.0, 10_000.0, float(default),
                                                          format="%.3f", key=widget_key))
            params[key] = values
    st.caption("Reward box filled: the whole trade closes at 1:box (partial booking is then not used). Empty: partial "
               "booking (if on) and the TSL take the trade out.")
    st.markdown("**Partial profit booking (only with an empty reward box)**")
    c1, c2, c3, c4, c5 = st.columns(5)
    partial_on = c1.checkbox("Partial booking on", value=tm.partial_enabled, key=f"tm_partial_{index}")
    partial_r = c2.number_input("At R", 0.5, 20.0, float(tm.partial_r), 0.5, key=f"tm_r_{index}")
    partial_pct = c3.number_input("Book % of lots", 1.0, 99.0, float(tm.partial_pct), 5.0, key=f"tm_pct_{index}")
    one_lot = c4.selectbox("One-lot trade at the target", ONE_LOT_AT_TARGET,
                           index=ONE_LOT_AT_TARGET.index(tm.one_lot_at_target), format_func=LABELS.get,
                           key=f"tm_onelot_{index}")
    after = c5.selectbox("After the partial", AFTER_PARTIAL, index=AFTER_PARTIAL.index(tm.after_partial),
                         format_func=LABELS.get, key=f"tm_after_{index}")
    st.markdown("**Session and capital**")
    alloc_store = AllocationStore(AllocationSetting.from_percent(20.0), journal_dir=paper_dir(index))
    alloc_now = alloc_store.setting
    d0, d1, d2, d3, d4 = st.columns(5)
    alloc_pct = d0.number_input("Allocation per trade (%)", 1.0, 100.0,
                                float(alloc_now.value) if alloc_now.mode == "PERCENT" else 20.0, 1.0,
                                key=f"tm_alloc_{index}",
                                help="Default 20%. Starting capital 1,00,000 (paper account).")
    forced = d1.checkbox(f"Forced exit at {current.force_exit}", value=tm.forced_exit_enabled, key=f"tm_forced_{index}")
    basis = d2.selectbox("Allocation % taken from", ALLOCATION_BASES, index=ALLOCATION_BASES.index(tm.allocation_basis),
                         format_func=LABELS.get, key=f"tm_basis_{index}")
    loss_on = d3.checkbox("Daily-loss cutoff", value=tm.daily_loss_cutoff_enabled, key=f"tm_loss_on_{index}")
    loss_pct = d4.number_input("Cutoff (% of day's opening equity)", 0.5, 100.0, float(tm.daily_loss_cutoff_pct), 0.5,
                               key=f"tm_loss_pct_{index}")
    st.caption(f"New trades from {current.entry_start}, no new trades from {current.entry_end} "
               "(Strategy settings above). Daily-loss cutoff applies from the next signal.")
    if st.form_submit_button("Save trade management"):
        try:
            tm_store.update(exit_target_rr=reward, initial_sl_pct=float(initial_sl), tsl_enabled=tsl_on, tsl_mode=mode, tsl_method=method,
                            tsl_source=source, tsl_timeframe=tsl_tf, tsl_trigger=trigger, method_params=params,
                            partial_enabled=partial_on, partial_r=float(partial_r), partial_pct=float(partial_pct),
                            one_lot_at_target=one_lot, after_partial=after, forced_exit_enabled=forced,
                            allocation_basis=basis, daily_loss_cutoff_enabled=loss_on, daily_loss_cutoff_pct=float(loss_pct))
            alloc_store.set(AllocationSetting.from_percent(float(alloc_pct)))
            st.success(f"Saved for {label}. Applies to the next trade.")
        except ValueError as exc:
            st.error(f"Not saved: {exc}")

open_positions = [p for p in ((status or {}).get("positions") or []) if p.get("trade_id")]
if open_positions:
    st.markdown("**Open trades: trailing stop**")
    st.dataframe(pd.DataFrame([{k: p.get(k) for k in ("slot", "symbol", "side", "entry", "tsl", "tsl_chart",
                                                         "tsl_timeframe", "tsl_trigger", "tsl_stop")}
                               for p in open_positions]), hide_index=True, width="stretch")
    saved_manual = manual_stops(index)
    with st.form(f"manual_stop_{index}"):
        st.caption("Manual stop (used when the trade's TSL mode is Manual). Option chart: option price; "
                   "spot chart: index level. 0 = remove.")
        manual_values = {}
        for p in open_positions:
            manual_values[p["trade_id"]] = st.number_input(
                f"{p['slot']} {p['symbol']} ({p.get('tsl_chart', 'OPTION')} chart)", min_value=0.0,
                value=float(saved_manual.get(p["trade_id"], 0.0)), step=0.5, key=f"manual_{p['trade_id']}")
        if st.form_submit_button("Save manual stops"):
            for trade_id, value in manual_values.items():
                set_manual_stop(index, trade_id, value if value > 0 else None)
            st.success("Saved. The trading program uses it from its next candle.")

# ----------------------------------------------------------------------- journal
st.markdown("---")
st.subheader(f"Today: {label}")
tabs = st.tabs(["Signals", "Trades", "Rejected signals", "KTMI values per candle", "Broker orders", "TSL comparison"])
sources = (("signals.csv", paper_dir(index)), ("trade_events.csv", paper_dir(index)),
           ("rejections.csv", paper_dir(index)), ("ktmi_bars.csv", paper_dir(index)),
           ("live_orders.csv", live_dir(index)), ("tsl_shadow_summary.csv", paper_dir(index) / "tsl_shadow"))
for tab, (name, folder) in zip(tabs, sources):
    with tab:
        frame = journal(name, folder)
        if frame.empty:
            st.caption("Nothing yet today.")
        else:
            st.dataframe(frame, hide_index=True, width="stretch")
