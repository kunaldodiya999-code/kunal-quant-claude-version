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
    INDEX_KEYS, STALE_AFTER_SECONDS, journal, live_dir, load_status, paper_dir, set_trading_indexes,
    settings_store, status_age_seconds, strike_options, summary_rows, trading_indexes,
)
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
    if st.form_submit_button("Save order window"):
        store.update(call_strike=call_choice, put_strike=put_choice, use_atm=use_atm, use_atm_plus_1=use_plus1)
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

# ----------------------------------------------------------------------- journal
st.markdown("---")
st.subheader(f"Today: {label}")
tabs = st.tabs(["Signals", "Trades", "Rejected signals", "KTMI values per candle", "Broker orders"])
sources = (("signals.csv", paper_dir(index)), ("trade_events.csv", paper_dir(index)),
           ("rejections.csv", paper_dir(index)), ("ktmi_bars.csv", paper_dir(index)),
           ("live_orders.csv", live_dir(index)))
for tab, (name, folder) in zip(tabs, sources):
    with tab:
        frame = journal(name, folder)
        if frame.empty:
            st.caption("Nothing yet today.")
        else:
            st.dataframe(frame, hide_index=True, width="stretch")
