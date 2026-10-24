"""Strategies: deploy one, several or all Kunal Quant strategies (paper trading), and see their exit plans.

One command starts every deployed strategy: python scripts\\run_strategies.py
"""

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from data.strategies import COMMAND, deployment, rows  # noqa: E402
from strategies.registry import PAPER_KEYS, STRATEGIES  # noqa: E402
from theme import configure_page  # noqa: E402

configure_page("Strategies")
st.title("Strategies")
st.caption("Deploy a single strategy, several, or all of them, as the market needs. Paper trading on real prices; "
           "nothing here places real orders.")

table = rows()

with st.form("deploy"):
    st.markdown("**Deploy**")
    cols = st.columns(len(STRATEGIES))
    chosen = []
    for col, (key, info) in zip(cols, STRATEGIES.items()):
        row = next(r for r in table if r["key"] == key)
        if info.stage == "PAPER":
            if col.checkbox(info.name, value=row["deployed"], key=f"deploy_{key}"):
                chosen.append(key)
        else:
            col.checkbox(info.name + " (research only)", value=False, disabled=True, key=f"deploy_{key}")
    if st.form_submit_button("Save deployment"):
        saved = deployment().set_deployed(chosen)
        st.success("Deployed: " + (", ".join(STRATEGIES[k].name for k in saved) or "nothing") +
                   ". A strategy that is already running picks this up when it is started again.")

table = rows()                 # again: after a save it shows the new choice
st.dataframe(pd.DataFrame([{k: r[k] for k in ("name", "market", "stage", "deployed", "now", "exit plan")}
                           for r in table]), hide_index=True, width="stretch",
             column_config={"deployed": st.column_config.CheckboxColumn("deployed")})

st.markdown("**Start them** (one PowerShell window, folder `C:\\Users\\USER\\Desktop\\Kunal\\kunal-quant-claude-version`, "
            "`(.venv)` active, after the FYERS login):")
st.code(COMMAND, language="powershell")
st.caption("It starts every deployed strategy in that window (lines start with the strategy's name). Ctrl+C stops them "
           "all. Research-only strategies are backtests; they get the deploy box when they are wired to live prices.")

st.markdown("**Exit plan (the same for every strategy)**")
st.markdown("- **Reward 1 : [box]**: type 1.5, 2, 2.5, 3 or any other number = the whole trade closes at that target.\n"
            "- **Empty box** = no fixed target: the trailing stop (TSL method you choose) takes you out when a candle "
            "CLOSES beyond it.\n- The strategy's own stop always protects the trade.")
for r in table:
    if r["key"] in PAPER_KEYS:
        st.caption(f"{r['name']}: change it on {r['exit settings']}. Guide: {r['guide']}")
