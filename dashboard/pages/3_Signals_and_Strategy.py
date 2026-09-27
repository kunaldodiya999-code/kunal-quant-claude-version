import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from data.source import IS_DEMO_DATA, recent_signal_events, strategy_registry  # noqa: E402
from theme import configure_page, demo_banner  # noqa: E402

configure_page("Signals & Strategy")
st.title("Signals & Strategy Status")

st.subheader("Strategy registry")
st.caption("Real — reflects the actual locked/experimental status from the project brief, not demo data.")
for s in strategy_registry():
    badge = {"LOCKED": "🔒", "EXPERIMENTAL": "🧪", "IN PROGRESS": "🚧"}.get(s.state, "")
    st.write(f"{badge} **{s.name}** — {s.state} · {'enabled' if s.enabled else 'disabled'} — {s.note}")

st.markdown("---")
st.subheader("Recent KTMI signal events")
if IS_DEMO_DATA:
    demo_banner("This event feed")

events = recent_signal_events()
df = pd.DataFrame(
    [
        {
            "Time": e.timestamp.strftime("%Y-%m-%d %H:%M"),
            "Direction": e.direction,
            "Underlying price": e.price,
            "Classification": e.classification,
        }
        for e in events
    ]
)


def classification_color(val: str) -> str:
    colors = {
        "RESOLVED_WITH_CANDLE": "color: #66bb6a",
        "NO_OPTION_DATA": "color: #ef5350",
        "DATA_GAP": "color: #ffa726",
        "EXPIRY_NOT_FOUND": "color: #ef5350",
        "CONTRACT_NOT_FOUND": "color: #ef5350",
    }
    return colors.get(val, "")


st.dataframe(
    df.style.map(classification_color, subset=["Classification"]),
    width="stretch",
    hide_index=True,
)

st.caption(
    "Real version: reads from `diagnose_option_data_coverage_v2.py`'s "
    "output (or a persisted version of it) via "
    "`unresolved_event_classifier.py`, both proposed in this same repo "
    "and verified against synthetic data — not yet run against the real "
    "198/16 events, which is still pending."
)
