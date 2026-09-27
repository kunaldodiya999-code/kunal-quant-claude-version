"""Kunal Quant Dashboard — main entry point.

Run with: streamlit run app.py

This file is the landing page. The rest of the dashboard lives in pages/
(Streamlit's native multipage convention -- each file there shows up as
its own sidebar entry automatically).

Per the project brief (section 44): this UI must not contain trading
logic. Every number below comes from dashboard/data/source.py, which is
the only file that will change when real data replaces demo data.
"""

import streamlit as st

from data.source import latest_backtest_summary, strategy_registry
from theme import configure_page

configure_page("Overview")

st.title("📈 Kunal Quant")
st.caption("Algorithmic options trading platform — Indian index derivatives")

st.markdown("---")

col1, col2, col3 = st.columns(3)

backtest = latest_backtest_summary()
strategies = strategy_registry()
locked = sum(1 for s in strategies if s.state == "LOCKED")
experimental = sum(1 for s in strategies if s.state == "EXPERIMENTAL")

with col1:
    st.metric("Phase", "1 — Backtest Validation")
    st.caption("Per the project brief: backtest validation comes before paper/live infra")

with col2:
    st.metric("KTMI events classified", f"{backtest.completed_trades + (backtest.ktmi_events - backtest.unresolved - backtest.no_entry_candle)}/{backtest.ktmi_events}")
    st.caption(f"As of {backtest.as_of} — {backtest.unresolved} unresolved, {backtest.no_entry_candle} no-entry-candle still pending")

with col3:
    st.metric("Live trading", "Disabled", delta="by design", delta_color="off")
    st.caption("No order-placement code exists yet — read-only broker data only")

st.markdown("---")
st.subheader("Strategy registry")
st.caption(f"{locked} locked · {experimental} experimental / research-only")

for s in strategies:
    css_class = {
        "LOCKED": "status-locked",
        "EXPERIMENTAL": "status-experimental",
        "IN PROGRESS": "status-progress",
    }.get(s.state, "")
    enabled = "🟢 enabled" if s.enabled else "⚪ disabled"
    st.markdown(
        f"**{s.name}** — <span class='{css_class}'>{s.state}</span> · {enabled}  \n"
        f"<small>{s.note}</small>",
        unsafe_allow_html=True,
    )

st.markdown("---")
st.info(
    "Use the sidebar to navigate: Market Overview, Options Chain, "
    "Signals & Strategy, Positions & Risk, Backtest Summary. Pages marked "
    "with a demo-data banner are placeholder UI awaiting real data."
)
