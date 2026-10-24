"""Live Paper Trading: status, order window, settings and today's journal.

Start the trading program first (separate window):
    python scripts\\run_paper_session.py
This page reads its live status file and saves your settings. It never places orders.
"""

import sys
from datetime import time as dtime
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from data.live import (  # noqa: E402
    STALE_AFTER_SECONDS, journal, live_dir, load_status, settings_store, status_age_seconds, strike_options,
)
from theme import configure_page  # noqa: E402

configure_page("Live Paper Trading")
st.title("Live Paper Trading")
st.success("PAPER MODE: real FYERS prices, simulated trades. No real orders are sent.", icon="🧪")

TIMEFRAMES = (1, 3, 5, 10, 15, 30, 60)
DIRECTIONS = {"BOTH": "Both (calls and puts)", "LONG": "Long only (BUY CALL)", "SHORT": "Short only (BUY PUT)"}


@st.fragment(run_every=3)
def live_panel() -> None:
    status = load_status()
    age = status_age_seconds(status)
    if status is None or age is None or age > STALE_AFTER_SECONDS:
        st.warning(
            "The trading program is not running (no fresh status). In VS Code, folder "
            "`C:\\Users\\USER\\Desktop\\Kunal\\kunal-quant-claude-version`, run:  "
            "`python scripts\\run_paper_session.py`",
            icon="⏸️",
        )
    if status and status.get("orders_mode") == "LIVE":
        st.error("LIVE ORDERS ARE ON: paper trades are also being sent to FYERS with real money.", icon="🚨")
    elif status:
        st.info("Broker orders: DRY RUN. Orders that would be sent are listed in the 'Broker orders' tab; "
                "nothing is sent to FYERS.", icon="🛡️")
    feed = (status or {}).get("feed") or {}
    account = (status or {}).get("account") or {}
    ladders = (status or {}).get("ladders") or {}
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("FYERS feed", "Connected" if feed.get("connected") else "Not connected")
    c2.metric("NIFTY spot", f"{status['spot']:,.2f}" if status and status.get("spot") else "-")
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
    st.subheader("Open paper positions")
    positions = (status or {}).get("positions") or []
    if positions:
        st.dataframe(pd.DataFrame(positions), hide_index=True, width="stretch")
    else:
        st.caption("No open paper positions.")


live_panel()

store = settings_store()
current = store.settings
status = load_status()

# ------------------------------------------------------------------ order window
st.markdown("---")
st.subheader("Order window: which strike to buy")
st.caption("5 strikes from the live NIFTY spot: 1 ITM, ATM, 3 OTM. Changes apply to the next signal.")
with st.form("order_window"):
    left, right = st.columns(2)
    call_opts, put_opts = strike_options(status, "call"), strike_options(status, "put")
    with left:
        call_choice = st.selectbox(
            "CALL strike (Long Speed signal)", [c for c, _ in call_opts],
            index=[c for c, _ in call_opts].index(current.call_strike),
            format_func=dict(call_opts).get, key="call_strike",
        )
    with right:
        put_choice = st.selectbox(
            "PUT strike (Short Speed signal)", [c for c, _ in put_opts],
            index=[c for c, _ in put_opts].index(current.put_strike),
            format_func=dict(put_opts).get, key="put_strike",
        )
    b1, b2 = st.columns(2)
    use_atm = b1.checkbox("ATM strike (calls and puts)", value=current.use_atm, key="use_atm")
    use_plus1 = b2.checkbox("ATM+1 strike (calls and puts)", value=current.use_atm_plus_1, key="use_atm_plus_1")
    st.caption(
        "Ticked boxes override the dropdowns. ATM only = enter ATM. ATM+1 only = one strike out of the money "
        "(CALL: one strike above ATM, PUT: one strike below ATM). Both ticked = two trades per signal."
    )
    if st.form_submit_button("Save order window"):
        store.update(call_strike=call_choice, put_strike=put_choice, use_atm=use_atm, use_atm_plus_1=use_plus1)
        st.success("Saved. Applies to the next signal.")

# ---------------------------------------------------------------------- settings
st.markdown("---")
st.subheader("Strategy settings (KTMI Uni Lite core)")
with st.form("strategy_settings"):
    c1, c2 = st.columns(2)
    timeframe = c1.selectbox("Timeframe (minutes)", TIMEFRAMES, index=TIMEFRAMES.index(current.timeframe_minutes),
                             key="timeframe")
    direction = c2.radio("Trade direction", list(DIRECTIONS), index=list(DIRECTIONS).index(current.trade_direction),
                         format_func=DIRECTIONS.get, horizontal=True, key="direction")
    t1, t2, t3 = st.columns(3)
    start = t1.time_input("New trades from", dtime.fromisoformat(current.entry_start), step=60, key="start")
    end = t2.time_input("No new trades from", dtime.fromisoformat(current.entry_end), step=60, key="end")
    force = t3.time_input("Force exit at", dtime.fromisoformat(current.force_exit), step=60, key="force")
    st.caption("Entries happen only after the signal candle has closed. "
               "A timeframe change applies when the trading program is restarted; the rest apply to the next signal.")
    if st.form_submit_button("Save settings"):
        try:
            store.update(timeframe_minutes=int(timeframe), trade_direction=direction,
                         entry_start=start.strftime("%H:%M"), entry_end=end.strftime("%H:%M"),
                         force_exit=force.strftime("%H:%M"))
            st.success("Saved.")
        except ValueError as exc:
            st.error(f"Not saved: {exc}")

# ----------------------------------------------------------------------- journal
st.markdown("---")
st.subheader("Today")
tabs = st.tabs(["Signals", "Trades", "Rejected signals", "KTMI values per candle", "Broker orders"])
sources = (("signals.csv", None), ("trade_events.csv", None), ("rejections.csv", None),
           ("ktmi_bars.csv", None), ("live_orders.csv", "live_trading"))
for tab, (name, folder) in zip(tabs, sources):
    with tab:
        frame = journal(name, folder=live_dir() if folder else None)
        if frame.empty:
            st.caption("Nothing yet today.")
        else:
            st.dataframe(frame, hide_index=True, width="stretch")
