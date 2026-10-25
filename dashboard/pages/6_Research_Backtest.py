"""Research Backtest: clean-data sweep, KTMI Uni Lite accuracy, Opening Scalp results.

Read-only. Results come from the research scripts (run them in
C:\\Users\\USER\\Desktop\\Kunal\\kunal-quant-claude-version). See docs/OPENING_SCALP_AND_DATA.md.
"""

import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from data.research import (  # noqa: E402
    COMMANDS, ktmi_meta, ktmi_signals, ktmi_summary, scalp_grid, scalp_summary, scalp_trades, sweep_report,
    tsl_lab_meta, tsl_lab_summary, tsl_lab_trades,
)
from paper_trading.trade_management import LABELS  # noqa: E402
from research.tsl_beta import BETA_LABELS  # noqa: E402
from theme import configure_page  # noqa: E402

configure_page("Research Backtest")
st.title("Research Backtest")
st.info("Research only: these results never place trades. The Opening Scalp is OFF by default. "
        "Option points are an ESTIMATE (0.5 x index points - 1.5 cost).", icon="🔬")


def missing(what: str, key: str) -> None:
    st.warning(f"No {what} results yet. In VS Code, folder "
               "`C:\\Users\\USER\\Desktop\\Kunal\\kunal-quant-claude-version`, run:  "
               f"`{COMMANDS[key]}`")


data_tab, ktmi_tab, scalp_tab, tsl_tab = st.tabs(["Clean data", "KTMI Uni Lite accuracy", "Opening Scalp", "TSL Lab"])

with data_tab:
    st.subheader("Which history is clean")
    st.caption("Clean day = all minutes present, no duplicates, valid OHLC, no frozen run, no spike.")
    report = sweep_report()
    if report is None:
        missing("data sweep", "sweep")
    else:
        st.dataframe(report, hide_index=True, width="stretch")

with ktmi_tab:
    st.subheader("KTMI Uni Lite signals (UNI_LITE_CORE)")
    summary = ktmi_summary()
    if summary is None:
        missing("KTMI accuracy", "ktmi")
    else:
        meta = ktmi_meta() or {}
        st.caption(f"Source: {meta.get('source', '?')}, generated {meta.get('generated_at', '?')}. "
                   "Entry at the next candle open after the signal candle closes.")
        indexes = sorted(summary["index"].unique())
        index = st.selectbox("Index", indexes, key="ktmi_index")
        rows = summary[summary["index"] == index]
        best = rows.sort_values("profit_factor", ascending=False).head(1)
        if not best.empty:
            b = best.iloc[0]
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Clean days", int(b["clean_days"]))
            c2.metric("Signals", int(b["trades"]))
            c3.metric("Best profit factor", f"{b['profit_factor']:.2f}")
            c4.metric("Direction right after 15 min", f"{b['dir_acc_15m']:.1f}%")
        st.dataframe(rows, hide_index=True, width="stretch")
        signals = ktmi_signals()
        if signals is not None:
            with st.expander("Every signal"):
                st.dataframe(signals[signals["index"] == index], hide_index=True, width="stretch")

with scalp_tab:
    st.subheader("Opening Scalp (09:15 - 10:15), default OFF")
    summary = scalp_summary()
    if summary is None:
        missing("Opening Scalp", "scalp")
    else:
        d = summary.get("default", {})
        st.caption(f"Source: {summary.get('source', '?')} {summary.get('resolution', '')}, clean days "
                   f"{summary.get('clean_days', {})}, generated {summary.get('generated_at', '?')}.")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Trades", d.get("trades", 0))
        c2.metric("Win rate", f"{d.get('win_rate_pct', 0)}%")
        c3.metric("Profit factor", d.get("profit_factor", 0))
        c4.metric("Avg option pts (est.)", d.get("approx_option_points_per_trade", 0))
        wf = summary.get("walk_forward") or {}
        if wf.get("second_half_unseen"):
            st.markdown(f"**Walk-forward (unseen second half):** profit factor "
                        f"{wf['second_half_unseen'].get('profit_factor')} on "
                        f"{wf['second_half_unseen'].get('trades')} trades.")
        with st.expander("Default settings"):
            st.json(summary.get("default_config", {}))
        trades = scalp_trades()
        if trades is not None and not trades.empty:
            trades = trades.sort_values(["day", "index"])
            trades["cumulative_points"] = trades["points"].cumsum()
            st.line_chart(trades, x="day", y="cumulative_points")
            st.dataframe(trades, hide_index=True, width="stretch")
        grid = scalp_grid()
        if grid is not None:
            with st.expander("All settings tried (best first)"):
                st.dataframe(grid, hide_index=True, width="stretch")

with tsl_tab:
    st.subheader("TSL Lab: which trailing stop keeps the most of each KTMI move")
    summary = tsl_lab_summary()
    if summary is None:
        missing("TSL Lab", "tsl")
    else:
        meta = tsl_lab_meta() or {}
        st.caption(f"Source: {meta.get('source', '?')}, generated {meta.get('generated_at', '?')}. KTMI Uni Lite "
                   "signals, entry at the next minute, each TSL on the SPOT chart (same rules as live), forced exit "
                   "15:10. Index points. Capture = points kept / best move in favour. Option-chart TSLs are compared "
                   "live on the Live Paper Trading page (tab 'TSL comparison'). Rows starting with BETA are test methods "
                   "(two-key, tightening Chandelier, R-ladder): research only, never used by live trading; they "
                   "include a -1R stop (the live 30% premium stop as an index move) and their premium part is "
                   "estimated (ATM delta 0.5, no time decay).")
        indexes = sorted(summary["index"].unique())
        index = st.selectbox("Index", indexes, key="tsl_index")
        rows = summary[summary["index"] == index].copy()
        rows["method"] = rows["method"].map(lambda m: LABELS.get(m, BETA_LABELS.get(m, m)))
        rows = rows.sort_values("total_points", ascending=False)
        best = rows.iloc[0]
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Best method", str(best["method"]).split(" - ")[0])
        c2.metric("Total points", f"{best['total_points']:.0f}")
        c3.metric("Profit factor", best["profit_factor"])
        c4.metric("Capture", f"{best['capture_pct']}%")
        st.dataframe(rows, hide_index=True, width="stretch")
        trades = tsl_lab_trades()
        if trades is not None:
            with st.expander("Every trade of every method"):
                st.dataframe(trades[trades["index"] == index], hide_index=True, width="stretch")
