"""Kunal Quant — UI prototype matching the first platform concept.

Run: streamlit run prototype_app.py (from the dashboard directory)

This is intentionally demo-only. It does not connect to brokers, store API
keys, generate AI responses, or submit orders. Keep it separate from app.py
so the validated backtest dashboard remains intact.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

st.set_page_config(page_title="Kunal Quant", page_icon="📈", layout="wide", initial_sidebar_state="expanded")

BG = "#0a0f1e"
PANEL = "#111a30"
PANEL2 = "#17233f"
LINE = "#243152"
TEXT = "#e6ebf7"
MUTED = "#8a97b8"
BLUE = "#4f7cff"
UP = "#26c281"
DOWN = "#ef5350"
AMBER = "#f5b942"

st.markdown(f"""
<style>
:root {{ color-scheme:dark; }}
.stApp {{ background:{BG}; color:{TEXT}; }}
[data-testid="stSidebar"] {{ background:{PANEL}; border-right:1px solid {LINE}; }}
[data-testid="stHeader"] {{ background:{PANEL}; }}
.block-container {{ padding-top:1rem; max-width:1500px; }}
div[data-testid="stMetric"] {{ background:{PANEL}; border:1px solid {LINE}; border-radius:10px; padding:14px; }}
div[data-testid="stMetricLabel"] {{ color:{MUTED}; }}
div[data-testid="stMetricValue"] {{ color:{TEXT}; }}
div[data-testid="stVerticalBlockBorderWrapper"] {{ border-color:{LINE}; }}
.stTabs [data-baseweb="tab-list"] {{ gap:8px; }}
.stTabs [data-baseweb="tab"] {{ background:{PANEL}; border-radius:7px; padding:8px 14px; }}
.stButton button {{ border-radius:7px; }}
.demo-note {{ background:{PANEL2}; border:1px solid {AMBER}; border-left:4px solid {AMBER}; padding:10px 13px; border-radius:6px; margin-bottom:14px; }}
.positive {{ color:{UP}; }} .negative {{ color:{DOWN}; }}
.small-muted {{ color:{MUTED}; font-size:0.85rem; }}
</style>
""", unsafe_allow_html=True)

if "halted" not in st.session_state:
    st.session_state.halted = False
if "page" not in st.session_state:
    st.session_state.page = "Dashboard"
if "chat" not in st.session_state:
    st.session_state.chat = [("assistant", "Describe a strategy, an indicator, or a question about your trades. Example: “Buy ATM calls when KTMI long crosses +0.5 after 9:45, trail with Chandelier.”")]

with st.sidebar:
    st.markdown("## Kunal :blue[Quant]")
    st.caption("Indian index options · UI prototype")
    st.markdown("---")
    pages = ["Dashboard", "Strategies", "Orders", "Portfolio", "AI research", "Settings"]
    for p in pages:
        if st.button(("●  " if st.session_state.page == p else "   ") + p, key="nav_" + p, use_container_width=True):
            st.session_state.page = p
            st.rerun()
    st.markdown("---")
    st.caption("Prototype navigation")
    st.caption("Broker connectivity: disabled")

top1, top2, top3, top4 = st.columns([2.8, 1, 1.2, 1.2])
with top1:
    st.markdown("# Kunal :blue[Quant]")
with top2:
    st.selectbox("Mode", ["Paper", "Broker test (locked)", "Live (locked)"], label_visibility="collapsed", key="mode")
with top3:
    st.caption("PAPER MODE ONLY")
with top4:
    if st.button("🛑 Kill switch", type="primary", use_container_width=True):
        st.session_state.halted = True
        st.rerun()

if st.session_state.halted:
    h1, h2 = st.columns([4, 1])
    h1.error("Trading halted: all strategies paused, no new orders. Sample positions remain open.")
    if h2.button("Resume prototype"):
        st.session_state.halted = False
        st.rerun()

st.markdown('<div class="demo-note"><b>Sample data only.</b> This prototype is not connected to any broker, AI provider, or order system. All displayed trades and P&L are illustrative.</div>', unsafe_allow_html=True)

def sample_candles(symbol: str, timeframe: str) -> pd.DataFrame:
    seed = 24550 if symbol == "NIFTY" else 53200
    rng = np.random.default_rng(seed + len(timeframe) * 7)
    n = 70
    close = seed + np.cumsum(rng.normal(0, seed * 0.00035, n))
    opn = np.r_[close[0], close[:-1]]
    high = np.maximum(opn, close) + rng.uniform(seed * .00008, seed * .0004, n)
    low = np.minimum(opn, close) - rng.uniform(seed * .00008, seed * .0004, n)
    times = pd.date_range("2026-10-21 09:15", periods=n, freq="min")
    return pd.DataFrame({"Time": times, "Open": opn, "High": high, "Low": low, "Close": close})

if st.session_state.page == "Dashboard":
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Paper equity", "₹1,00,000")
    c2.metric("Today’s net P&L", "+₹1,840", "+1.84%")
    c3.metric("Unrealised", "−₹320", "-₹320")
    c4.metric("Open positions", "1")
    chart_box = st.container(border=True)
    with chart_box:
        chart_head1, chart_head2, chart_head3 = st.columns([1, 1.4, 2])
        symbol = chart_head1.selectbox("Underlying", ["NIFTY", "BANKNIFTY"])
        timeframe = chart_head2.selectbox("Timeframe", ["1m", "3m", "5m", "15m"], index=1)
        chart_head3.caption("EMA 9 · Sample candles · Fills and stops are illustrative")
        df = sample_candles(symbol, timeframe)
        df["EMA 9"] = df["Close"].ewm(span=9, adjust=False).mean()
        fig = go.Figure()
        fig.add_trace(go.Candlestick(x=df["Time"], open=df["Open"], high=df["High"], low=df["Low"], close=df["Close"], name=symbol, increasing_line_color=UP, decreasing_line_color=DOWN))
        fig.add_trace(go.Scatter(x=df["Time"], y=df["EMA 9"], name="EMA 9", line=dict(color=AMBER, width=1.5)))
        fig.add_hline(y=float(df["Close"].iloc[-1]) * .998, line_dash="dash", line_color=DOWN, annotation_text="Illustrative trailing stop")
        fig.update_layout(height=360, margin=dict(l=8,r=8,t=10,b=8), paper_bgcolor=PANEL, plot_bgcolor=PANEL, font_color=TEXT, xaxis_rangeslider_visible=False, legend=dict(orientation="h", y=1.02), xaxis=dict(gridcolor=LINE), yaxis=dict(gridcolor=LINE))
        st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
        st.caption("Arrows show illustrative strategy fills. Stop and target lines will follow each open trade in the connected version.")
    left, right = st.columns(2)
    with left, st.container(border=True):
        st.subheader("Open positions")
        st.dataframe(pd.DataFrame([{"Contract":"NIFTY 24550 CE","Qty":65,"Entry":112.0,"LTP":107.1,"Stop (Chandelier)":98.4,"P&L":"−₹320"}]), hide_index=True, use_container_width=True)
    with right, st.container(border=True):
        st.subheader("Signal log: why a trade was or wasn’t taken")
        st.dataframe(pd.DataFrame([
            {"Time":"10:12","Signal":"KTMI A long","Result":"Entered NIFTY 24550 CE"},
            {"Time":"10:48","Signal":"KTMI B short","Result":"Rejected: quote older than 5 s"},
            {"Time":"11:03","Signal":"KTMI A long","Result":"Skipped: position already open"},
        ]), hide_index=True, use_container_width=True)

elif st.session_state.page == "Strategies":
    st.title("Strategies")
    with st.container(border=True):
        st.subheader("Build your own strategy with AI")
        st.write("Describe it in plain words. The AI writes draft rules for your review. In this prototype, no AI provider is connected and nothing is deployed.")
        if st.button("Open AI research"):
            st.session_state.page = "AI research"
            st.rerun()
    strategies = [
        ("KTMI A: momentum", "Buys ATM or one-strike-out calls and puts when momentum crosses its configured trigger.", "09:45–15:00", "Chandelier Exit (ATR 9, ×1.5)"),
        ("KTMI B: speed", "Long speed above or short speed below its trigger. Each source can be switched off.", "09:45–15:00", "Supertrend B (7, 1.5)"),
        ("Confluence", "Research strategy: enters only when momentum and speed agree on direction.", "09:45–15:00", "Parabolic SAR A"),
    ]
    cols = st.columns(2)
    for i, (name, desc, hours, trail) in enumerate(strategies):
        with cols[i % 2], st.container(border=True):
            st.subheader(name)
            st.caption("PAUSED" if st.session_state.halted else "SAMPLE CONFIGURATION")
            st.write(desc)
            st.caption(f"{hours} · Trail: {trail} · 1 lot")
            b1, b2, b3 = st.columns(3)
            b1.button("Deploy", key=f"deploy{i}", disabled=True, help="Paper deployment will be wired after validation.")
            b2.button("Edit", key=f"edit{i}", disabled=True)
            if b3.button("Ask AI", key=f"ai{i}"):
                st.session_state.page = "AI research"
                st.rerun()
    with st.container(border=True):
        st.subheader("Deploy settings")
        a, b = st.columns(2)
        a.selectbox("Trailing stop method", ["Chandelier Exit (ATR 9, ×1.5)", "Supertrend A (5, 1.0)", "Supertrend B (7, 1.5)", "Parabolic SAR A (0.02 / 0.02 / 0.20)", "Parabolic SAR B (0.04 / 0.04 / 0.10)", "Trailing Stop Lab"])
        b.selectbox("Stop calculated on", ["Option premium chart", "Underlying chart"])
        st.number_input("Max loss per day (₹); 0 = disabled", min_value=0, value=0, step=500)

elif st.session_state.page == "Orders":
    st.title("Orders")
    live, history, trades = st.tabs(["Live orders", "Order history", "Trades"])
    with live:
        st.dataframe(pd.DataFrame([{"Time":"10:12:04","Contract":"NIFTY 24550 CE","Side":"Buy","Type":"Market","Qty":65,"Price":112.0,"Status":"Simulated fill"},{"Time":"10:12:04","Contract":"NIFTY 24550 CE","Side":"Sell","Type":"Stop","Qty":65,"Price":89.6,"Status":"Pending"}]), hide_index=True, use_container_width=True)
    with history:
        st.dataframe(pd.DataFrame([{"Time":"09:47","Contract":"NIFTY 24500 PE","Side":"Buy","Qty":65,"Price":96.4,"Status":"Simulated fill"},{"Time":"09:58","Contract":"NIFTY 24500 PE","Side":"Sell","Qty":65,"Price":108.2,"Status":"Exit: trailing stop"}]), hide_index=True, use_container_width=True)
    with trades:
        st.dataframe(pd.DataFrame([{"Contract":"NIFTY 24500 PE","Entry":96.4,"Exit":108.2,"Gross":"₹767","Costs":"₹94","Net":"₹673"}]), hide_index=True, use_container_width=True)
    st.caption("Every row above is sample data, not a broker order or actual fill.")

elif st.session_state.page == "Portfolio":
    st.title("Portfolio")
    st.subheader("Strategy-wise P&L (net of fees)")
    st.dataframe(pd.DataFrame([
        {"Strategy":"KTMI A: momentum","Status":"sample running","Open":1,"Closed":4,"Win rate":"75%","Net":"+₹1,610"},
        {"Strategy":"KTMI B: speed","Status":"sample running","Open":0,"Closed":2,"Win rate":"50%","Net":"+₹230"},
        {"Strategy":"Total","Status":"—","Open":1,"Closed":6,"Win rate":"67%","Net":"+₹1,840"},
    ]), hide_index=True, use_container_width=True)
    st.caption("Illustrative portfolio summary. Not a performance claim.")

elif st.session_state.page == "AI research":
    st.title("AI research")
    st.caption("Provider selector and chat layout only. No AI provider is connected in this prototype.")
    providers = ["Claude", "ChatGPT", "Gemini", "DeepSeek", "Grok", "Groq", "Mistral", "OpenRouter"]
    provider = st.radio("AI provider", providers, horizontal=True)
    for role, msg in st.session_state.chat:
        with st.chat_message(role):
            st.write(msg)
    question = st.chat_input("Describe a strategy, indicator, or ask about your trades…")
    if question:
        st.session_state.chat.append(("user", question))
        st.session_state.chat.append(("assistant", f"{provider} is not connected yet. In the finished platform, generated rules will be shown for your review before paper deployment."))
        st.rerun()

elif st.session_state.page == "Settings":
    st.title("Settings")
    left, right = st.columns(2)
    with left, st.container(border=True):
        st.subheader("Brokers")
        st.text_input("FYERS app ID", placeholder="Stored locally in the future build")
        st.text_input("Dhan client ID", placeholder="Stored locally in the future build")
        st.button("Save and verify", disabled=True, help="Broker credentials are not stored by this prototype.")
    with right, st.container(border=True):
        st.subheader("AI providers (bring your own keys)")
        st.text_input("Claude API key", type="password", placeholder="Not stored")
        st.text_input("OpenAI API key", type="password", placeholder="Not stored")
        st.text_input("Gemini API key", type="password", placeholder="Not stored")
        st.button("Save keys", disabled=True, help="Keys are not stored by this prototype.")
    with left, st.container(border=True):
        st.subheader("Live trading guard")
        st.write("Live orders remain blocked. This prototype has no live order path.")
        phrase = st.text_input("Type ENABLE LIVE TRADING")
        st.button("Enable live trading", disabled=True, help="Disabled by design.")
    with right, st.container(border=True):
        st.subheader("Paper wallet")
        balance = st.number_input("Virtual balance (₹)", min_value=0, value=100000, step=1000)
        if st.button("Reset sample balance"):
            st.success(f"Prototype input set to ₹{balance:,.0f}; no account state was changed.")
    st.error("Stop everything? The kill switch pauses this prototype only. Real strategies and open positions are not connected.")

st.markdown("---")
st.caption("Kunal Quant · UI prototype · Sample data only · No broker connection · No real orders")
