"""Kunal FYERS Terminal: login with FYERS, then chart + option chain + the BBP_NM strategy (paper by default).

Start (folder C:\\Users\\USER\\Desktop\\Kunal\\kunal-fyers-terminal, venv active):   streamlit run app.py
"""

from __future__ import annotations

from datetime import datetime

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from terminal.candles import IST
from terminal.chart import chart_html
from terminal.engine import Terminal
from terminal.fyers import (INDEXES, data_dir, Fyers, auth_code_from, credentials, exchange_code, login_url, save_token,
                            saved_token, write_env)
from terminal.settings import TIMEFRAMES, SettingsStore

st.set_page_config(page_title="Kunal FYERS Terminal", layout="wide", initial_sidebar_state="collapsed")
st.markdown("""<style>
.block-container { padding-top: 3.2rem; padding-bottom: 0.5rem; max-width: 100%; }
div[data-testid="stMetricValue"] { font-size: 1.35rem; }
.chain { width: 100%; border-collapse: collapse; font-size: 13px; }
.chain th { color: #787b86; font-weight: 500; padding: 3px 6px; border-bottom: 1px solid #2a2e39; }
.chain td { padding: 3px 6px; text-align: center; border-bottom: 1px solid #1e222d; }
.chain td.c { color: #26a69a; } .chain td.p { color: #ef5350; } .chain td.k { color: #d1d4dc; font-weight: 600; }
.chain tr.atm td { background: rgba(41,98,255,0.18); }
.pos { border: 1px solid #2a2e39; border-radius: 6px; padding: 8px 10px; margin: 6px 0; }
</style>""", unsafe_allow_html=True)

store = SettingsStore()


# ------------------------------------------------------------------ login
def login_page() -> None:
    st.title("Kunal FYERS Terminal")
    st.subheader("Log in with FYERS (once every trading day)")
    creds = credentials()
    with st.expander("Step 1 - your FYERS app details (only the first time)", expanded=not creds["client_id"]):
        st.markdown("From **myapi.fyers.in > Dashboard > your app**: the **App ID** (looks like `ABCD1234-100`), "
                    "the **Secret ID**, and the **Redirect URL** you typed when you made the app. "
                    "They are saved in the file `.env` in this folder (never uploaded to GitHub).")
        cid = st.text_input("App ID", value=creds["client_id"])
        secret = st.text_input("Secret ID", value=creds["secret_key"], type="password")
        redirect = st.text_input("Redirect URL", value=creds["redirect_uri"])
        if st.button("Save app details"):
            write_env({"FYERS_CLIENT_ID": cid.strip(), "FYERS_SECRET_KEY": secret.strip(),
                       "FYERS_REDIRECT_URI": redirect.strip()})
            st.success("Saved.")
            st.rerun()
    if not (creds["client_id"] and creds["secret_key"]):
        st.info("Fill Step 1 first.")
        return
    st.markdown("**Step 2** - click, log in to FYERS (mobile number, PIN, OTP) and allow the app.")
    try:
        st.link_button("Open FYERS login", login_url(creds), type="primary")
    except Exception as exc:  # fyers_apiv3 missing or bad details
        st.error(f"Could not make the login link: {exc}")
        return
    st.markdown("**Step 3** - after the login the browser opens your Redirect URL. The page itself may say "
                "*'This site can't be reached'*: that is fine. Copy the **whole address** from the address bar "
                "(it contains `auth_code=`) and paste it here.")
    pasted = st.text_input("Paste the whole address here")
    if st.button("Authorize", type="primary", disabled=not pasted):
        try:
            token = exchange_code(creds, auth_code_from(pasted))
            name = Fyers(creds["client_id"], token).profile().get("name", "")
            save_token(token)
            st.success(f"Logged in{' as ' + name if name else ''}.")
            st.rerun()
        except Exception as exc:
            st.error(f"Login failed: {exc}")


@st.cache_resource(show_spinner=False)
def terminal_for(client_id: str, token: str) -> Terminal:
    term = Terminal(Fyers(client_id, token))
    term.start()
    return term


token = saved_token()
creds = credentials()
if not token or not creds["client_id"]:
    login_page()
    st.stop()

term = terminal_for(creds["client_id"], token)


# ------------------------------------------------------------------ settings helpers
def save(**changes) -> None:
    try:
        store.update(**changes)
    except ValueError as exc:
        st.session_state["settings_error"] = str(exc)
    else:
        st.session_state.pop("settings_error", None)


def bind(field: str, key: str, cast=lambda v: v) -> None:
    save(**{field: cast(st.session_state[key])})


s = store.load()

# ------------------------------------------------------------------ top bar
top = st.columns([2.6, 2.2, 3.2, 1])
labels = {k: v.label for k, v in INDEXES.items()}
top[0].radio("Index", list(INDEXES), index=list(INDEXES).index(s.index), format_func=labels.get, horizontal=True,
             key="w_index", on_change=bind, args=("index", "w_index"))
top[1].radio("Timeframe", TIMEFRAMES, index=TIMEFRAMES.index(s.timeframe), format_func=lambda m: f"{m} min",
             horizontal=True, key="w_tf", on_change=bind, args=("timeframe", "w_tf"))


@st.fragment(run_every=2)
def status_line() -> None:
    snap = term.snapshot()
    mode = "REAL ORDERS ON" if store.load().real_orders else "PAPER (no real orders)"
    d = snap["direction"]
    sign = "-" if d is None else ("ABOVE 0 (calls)" if d > 0 else "BELOW 0 (puts)")
    text = (f"**{snap['status'].upper()}** · {mode} · {datetime.now(IST):%H:%M:%S} · "
            f"Direction (last finished candle) {sign}")
    st.markdown(text)
    if snap["error"]:
        st.error(snap["error"])


with top[2]:
    status_line()
if top[3].button("Log out"):
    term.stop()
    (data_dir() / "token.json").unlink(missing_ok=True)
    terminal_for.clear()
    st.rerun()

if st.session_state.get("settings_error"):
    st.error(st.session_state["settings_error"])

left, right = st.columns([3.3, 1.25])
with left:
    if hasattr(st, "iframe"):
        st.iframe(chart_html(), height=740)
    else:                                    # older Streamlit
        components.html(chart_html(), height=740, scrolling=False)

with right:
    @st.fragment(run_every=2)
    def funds_box() -> None:
        snap = term.snapshot()
        a, b = st.columns(2)
        a.metric("Funds available", "-" if snap["funds"] is None else f"Rs {snap['funds']:,.0f}")
        b.metric("Funds utilized", f"{snap['utilized_pct']:.1f} %")
    funds_box()
    st.number_input("Funds to utilize per new entry (Rs)", min_value=0.0, step=1000.0, value=float(s.funds_per_entry),
                    key="w_funds", on_change=bind, args=("funds_per_entry", "w_funds"))

    @st.fragment(run_every=2)
    def chain_box() -> None:
        snap = term.snapshot()
        spot = snap["spot"]
        st.markdown(f"**Option chain** · {INDEXES[store.load().index].label} "
                    f"{'' if spot is None else f'{spot:,.2f}'} · nearest expiry")
        f = lambda v: "-" if v is None else f"{v:,.2f}"
        rows = "".join(f"<tr class='{'atm' if r['atm'] else ''}'><td class='c'>{f(r['call_ltp'])}</td>"
                       f"<td class='k'>{r['strike']:g}</td><td class='p'>{f(r['put_ltp'])}</td></tr>"
                       for r in snap["chain"])
        st.markdown(f"<table class='chain'><tr><th>CALL</th><th>STRIKE</th><th>PUT</th></tr>{rows}</table>",
                    unsafe_allow_html=True)
    chain_box()

    st.markdown("**Trade option**")
    c1, c2 = st.columns(2)
    c1.checkbox("Call", value=s.call_on, key="w_call", on_change=bind, args=("call_on", "w_call"))
    c2.checkbox("Put", value=s.put_on, key="w_put", on_change=bind, args=("put_on", "w_put"))

    st.markdown("**Premium select**")
    modes = {"RANGE": "Price range", "PER_LOT": "Per lot amount"}
    st.radio("Mode", list(modes), index=list(modes).index(s.strike_mode), format_func=modes.get, horizontal=True,
             key="w_mode", on_change=bind, args=("strike_mode", "w_mode"), label_visibility="collapsed")
    if store.load().strike_mode == "RANGE":
        r1, r2, r3 = st.columns([5, 1, 5])
        r1.number_input("From", min_value=0.0, step=5.0, value=float(s.premium_low), key="w_lo",
                        on_change=bind, args=("premium_low", "w_lo"), label_visibility="collapsed")
        r2.markdown("<div style='text-align:center;padding-top:6px'>-</div>", unsafe_allow_html=True)
        r3.number_input("To", min_value=0.0, step=5.0, value=float(s.premium_high), key="w_hi",
                        on_change=bind, args=("premium_high", "w_hi"), label_visibility="collapsed")
        st.caption("Two strikes inside the range: the LOWER price is bought.")
    else:
        st.number_input("Per lot amount (Rs)", min_value=0.0, step=500.0, value=float(s.per_lot_amount),
                        key="w_perlot", on_change=bind, args=("per_lot_amount", "w_perlot"))
        st.caption("Buys the price nearest to amount / lot size, never above it (Rs 6,500 / 65 = Rs 100).")

    @st.fragment(run_every=2)
    def position_box() -> None:
        snap = term.snapshot()
        p = snap["position"]
        if not p:
            st.caption("No open trade.")
            return
        pnl = snap["position_pnl"]
        color = "#26a69a" if (pnl or 0) >= 0 else "#ef5350"
        st.markdown(f"<div class='pos'><b>{p['side']}</b> {p['symbol']} · {p['lots']} lot(s) = {p['qty']}<br>"
                    f"Entry {p['entry_price']:g} at {p['entry_time']} · Stop {p['stop']:g} · "
                    f"Now {'-' if snap['position_ltp'] is None else snap['position_ltp']}<br>"
                    f"<span style='color:{color}'>P&L Rs {'-' if pnl is None else f'{pnl:,.2f}'}</span> · "
                    f"{p['mode']}</div>", unsafe_allow_html=True)
        if st.button("Exit now (limit, price - buffer)"):
            term.exit_now()
    position_box()

# ------------------------------------------------------------------ below the chart
tab1, tab2, tab3 = st.tabs(["Today's trades", "What happened", "Settings"])
with tab1:
    @st.fragment(run_every=5)
    def trades_box() -> None:
        rows = term.trades_today()
        if not rows:
            st.caption("No closed trades today.")
            return
        df = pd.DataFrame(rows)
        df["pnl"] = df["pnl"].astype(float)
        st.metric("Today's P&L", f"Rs {df['pnl'].sum():,.2f}", f"{len(df)} trade(s)")
        st.dataframe(df, hide_index=True, width="stretch")
    trades_box()
with tab2:
    @st.fragment(run_every=3)
    def events_box() -> None:
        st.code("\n".join(term.snapshot()["events"]) or "Nothing yet.", language=None)
    events_box()
with tab3:
    a, b, c, d = st.columns(4)
    a.text_input("New entries from", value=s.entry_start, key="w_start", on_change=bind,
                 args=("entry_start", "w_start"))
    b.text_input("No new entries from", value=s.entry_end, key="w_end", on_change=bind, args=("entry_end", "w_end"))
    c.text_input("Close everything at", value=s.force_exit, key="w_fx", on_change=bind, args=("force_exit", "w_fx"))
    d.number_input("Limit buffer (Rs)", min_value=0.0, max_value=10.0, step=0.5, value=float(s.buffer),
                   key="w_buf", on_change=bind, args=("buffer", "w_buf"))
    st.number_input("BBP_NM lookback window", min_value=2, max_value=100, step=1, value=int(s.bbp_window),
                    key="w_win", on_change=bind, args=("bbp_window", "w_win", int))
    st.toggle("Real orders (needs today's arm: python arm_real_orders.py)", value=s.real_orders, key="w_real",
              on_change=bind, args=("real_orders", "w_real"))
    st.caption("Real orders are LIMIT orders only (buy price + buffer, sell price - buffer), never market. "
               "FYERS needs your whitelisted static IP for API orders. While today is not armed, every trade is "
               "a paper trade even with this switch ON.")
