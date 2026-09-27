import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from data.source import latest_backtest_summary  # noqa: E402
from theme import configure_page, real_data_banner  # noqa: E402

configure_page("Backtest Summary")
st.title("Backtest Summary")

b = latest_backtest_summary()
real_data_banner(f"pulled from the {b.as_of} checkpoint in the canonical repo, not demo data")

if not b.is_conclusive:
    st.error(
        "⚠️ NOT a performance conclusion. " + b.note,
        icon="⚠️",
    )

c1, c2, c3 = st.columns(3)
c1.metric("Sample 3M bars", f"{b.sample_bars:,}")
c2.metric("KTMI events", f"{b.ktmi_events:,}")
c3.metric("Gross P&L (sample)", f"₹{b.gross_pnl:,.2f}")

st.markdown("---")

c1, c2, c3, c4 = st.columns(4)
c1.metric("Completed trades", b.completed_trades)
c2.metric("Open trades", b.open_trades)
c3.metric("Unresolved", b.unresolved, delta="pending classification", delta_color="off")
c4.metric("No entry candle", b.no_entry_candle, delta="pending classification", delta_color="off")

st.markdown("---")
st.subheader("What happens next, per the project brief's own priority order")
st.markdown(
    """
1. Classify the 198 unresolved + 16 no-entry-candle events
   (`proposals/diagnose_option_data_coverage_v2.py` in this repo is
   ready — needs the real database to run)
2. Verify remaining historical option coverage gaps
3. Complete option-data acquisition where gaps are found
4. Run the full historical options backtest (not just this 2,500-bar sample)
5. Validate trade-level results
6. Upgrade the economic execution model (real costs, slippage)
7. Build out analytics
8. *Then* paper trading infrastructure
9. *Then* the wider user-facing platform

Nothing on this page skips ahead of that order — the dashboard exists
alongside this work, not instead of it.
"""
)
