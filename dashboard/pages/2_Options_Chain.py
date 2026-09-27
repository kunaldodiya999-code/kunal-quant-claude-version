import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from data.source import IS_DEMO_DATA, options_chain, pcr_and_gex  # noqa: E402
from theme import configure_page, demo_banner  # noqa: E402

configure_page("Options Chain")
st.title("Options Chain — NIFTY")
if IS_DEMO_DATA:
    demo_banner("The full chain, PCR, and GEX")

metrics = pcr_and_gex()
c1, c2 = st.columns(2)
c1.metric("PCR (OI)", metrics["pcr_oi"])
c2.metric("Net GEX", metrics["net_gex"])

st.markdown("---")

rows = options_chain()
df = pd.DataFrame(
    [
        {
            "CE OI": r.ce_oi,
            "CE IV%": r.ce_iv,
            "CE LTP": r.ce_ltp,
            "Strike": r.strike,
            "PE LTP": r.pe_ltp,
            "PE IV%": r.pe_iv,
            "PE OI": r.pe_oi,
        }
        for r in rows
    ]
)


def highlight_atm(row: pd.Series) -> list[str]:
    atm = df["Strike"].iloc[(df["Strike"] - df["Strike"].median()).abs().argsort()[:1]].values[0]
    return ["background-color: #1a2733" if row["Strike"] == atm else "" for _ in row]


st.dataframe(
    df.style.apply(highlight_atm, axis=1).format(
        {"CE OI": "{:,}", "PE OI": "{:,}", "CE LTP": "{:.2f}", "PE LTP": "{:.2f}"}
    ),
    width="stretch",
    hide_index=True,
    height=560,
)

st.caption(
    "Real version: reads `instruments` + `candles` (LTP) and "
    "`option_analytics` (IV, computed via the Black-76 pipeline already "
    "in the codebase) for the nearest weekly expiry. GEX comes from "
    "`gex_snapshots`, which is currently a research/analytics table, not "
    "wired into the locked KTMI strategy."
)
