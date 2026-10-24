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

from data.source import latest_backtest_summary
from data.strategies import rows as strategy_rows
from theme import configure_page

configure_page("Overview")

st.title("📈 Kunal Quant")
st.caption("Algorithmic options trading platform — Indian index derivatives")

st.markdown("---")

col1, col2, col3 = st.columns(3)

backtest = latest_backtest_summary()
strategies = strategy_rows()

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
st.subheader("Strategies")
deployed = [s for s in strategies if s["deployed"]]
st.caption(f"{len(deployed)} deployed (paper trading). Change it on the page Strategies; start them with "
           "python scripts\\run_strategies.py")
for s in strategies:
    state = "🟢 deployed" if s["deployed"] else ("⚪ not deployed" if s["stage"] == "PAPER" else "🔬 research only")
    st.markdown(f"**{s['name']}** · {state} · {s['now']}  \n<small>{s['market']} · exit: {s['exit plan']}</small>",
                unsafe_allow_html=True)

st.markdown("---")
st.info(
    "Use the sidebar to navigate: Market Overview, Options Chain, "
    "Signals & Strategy, Positions & Risk, Backtest Summary. Pages marked "
    "with a demo-data banner are placeholder UI awaiting real data."
)
