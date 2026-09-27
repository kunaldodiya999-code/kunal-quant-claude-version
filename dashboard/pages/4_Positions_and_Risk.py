import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from data.source import IS_DEMO_DATA, paper_positions, risk_snapshot  # noqa: E402
from theme import configure_page, demo_banner  # noqa: E402

configure_page("Positions & Risk")
st.title("Positions & Risk")
st.warning(
    "🔒 View-only. There is no order-placement code in this project yet "
    "— by design, per the project brief. This page will show **paper** "
    "positions first; live positions are a separate, later milestone "
    "that needs explicit sign-off once backtest + paper validation are "
    "both done.",
    icon="🔒",
)
if IS_DEMO_DATA:
    demo_banner("Every number on this page")

risk = risk_snapshot()
c1, c2, c3, c4 = st.columns(4)
c1.metric("Capital deployed", f"₹{risk.capital_deployed:,.0f}", f"of ₹{risk.starting_capital:,.0f}")
c2.metric("Day P&L (paper)", f"₹{risk.daily_pnl:,.0f}")
c3.metric("Daily loss limit", f"₹{risk.daily_loss_limit:,.0f}")
c4.metric("Kill switch", "Armed" if risk.kill_switch_armed else "Disarmed")

st.progress(min(abs(risk.daily_pnl) / risk.daily_loss_limit, 1.0) if risk.daily_pnl < 0 else 0.0)
st.caption(f"{risk.open_positions} / {risk.max_positions} max concurrent positions")

st.markdown("---")
st.subheader("Open paper positions")

positions = paper_positions()
df = pd.DataFrame(
    [
        {
            "Symbol": p.symbol,
            "Direction": p.direction,
            "Qty": p.qty,
            "Entry": p.entry_price,
            "LTP": p.ltp,
            "Unrealized P&L": p.unrealized_pnl,
        }
        for p in positions
    ]
)
st.dataframe(
    df.style.map(
        lambda v: "color: #66bb6a" if isinstance(v, (int, float)) and v > 0 else (
            "color: #ef5350" if isinstance(v, (int, float)) and v < 0 else ""
        ),
        subset=["Unrealized P&L"],
    ),
    width="stretch",
    hide_index=True,
)

st.caption(
    "Real version: reads from a paper execution adapter (section 30 of "
    "the brief) sitting behind the same strategy + risk engine as "
    "backtest. Nothing here places or will place a real order — that "
    "requires the LIVE_TRADING_ENABLED flag and the full pre-order risk "
    "checklist from the brief (section 32), none of which exists yet, "
    "on purpose."
)
