"""The Time Machine box: a closed expander under a strategy's tables (never on the chart).

One row per trade / shortlisted stock: the chance of reaching each target before the exit time, the chance the
stop comes first, and the win chance with the strategy's own exit plan.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

NOTE = ("How to read it: the rest of the day replayed 1,000 times from the stock's own 5-minute candles of the "
        "last 60 sessions. Use the target columns to pick a realistic reward (1:1.5 ... 1:3): in our check on ~480 "
        "past trades they ranked correctly but were cautious (real hit rates were 6-15 points higher). The win "
        "chance did NOT predict winners in that check, so it is not used to choose or skip trades.")


def show(odds: dict | None, *, label: str = "Time Machine: chance of reaching each target before 15:10") -> None:
    if not odds:
        return
    rows = []
    for name, o in odds.items():
        ladder = o.get("ladder") or {}
        rows.append({"symbol": name.replace("NSE:", "").replace("-EQ", ""), "win %": o.get("win_pct"),
                     **{f"{k} %": v.get("target_pct") for k, v in ladder.items()},
                     "stop first %": o.get("stop_pct"), "sessions": o.get("sessions")})
    with st.expander(label, expanded=False):
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
        st.caption(NOTE)


__all__ = ["NOTE", "show"]
