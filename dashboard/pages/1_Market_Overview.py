import sys
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from data.source import IS_DEMO_DATA, intraday_series, market_overview  # noqa: E402
from theme import configure_page, demo_banner  # noqa: E402

configure_page("Market Overview")
st.title("Market Overview")
if IS_DEMO_DATA:
    demo_banner("Index prices, change%, and the intraday chart")

quotes = market_overview()
cols = st.columns(len(quotes))
for col, q in zip(cols, quotes):
    col.metric(q.symbol, f"{q.ltp:,.2f}", f"{q.change:+.2f} ({q.change_pct:+.2f}%)")

st.markdown("---")
symbol = st.selectbox("Chart", [q.symbol for q in quotes if "VIX" not in q.symbol])
series = intraday_series(symbol)
df = pd.DataFrame(series, columns=["timestamp", "price"])

fig = go.Figure()
fig.add_trace(go.Scatter(x=df["timestamp"], y=df["price"], mode="lines", line=dict(color="#4fc3f7", width=2)))
fig.update_layout(
    template="plotly_dark",
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(0,0,0,0)",
    height=420,
    margin=dict(l=10, r=10, t=30, b=10),
    xaxis_title=None,
    yaxis_title="Price",
)
st.plotly_chart(fig, width="stretch")

st.caption(
    "Real version: this chart reads from the `candles` table (or a live "
    "FYERS WebSocket feed via `api.fyers_client.FyersClient`) for the "
    "selected instrument at 3-minute resolution, matching the KTMI "
    "pipeline's timeframe."
)
