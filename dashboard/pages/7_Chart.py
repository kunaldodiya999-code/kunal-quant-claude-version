"""Chart: candles + KTMI Uni Lite + drawing tools, for NIFTY, BANK NIFTY and SENSEX.

Drawing tools (left toolbar): trend line, horizontal line, vertical line, rectangle,
path, fib retracement. Drawings are saved in this browser per index and stay when the
chart refreshes or the timeframe changes. Read-only: this page never places orders.
"""

import sys
from datetime import date
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from chart_component import show_chart  # noqa: E402
from data.chart import SOURCES, chart_payload, load_minutes, trading_days  # noqa: E402
from data.live import INDEX_KEYS, settings_store  # noqa: E402
from strategies.index_profiles import INDEX_PROFILES  # noqa: E402
from theme import configure_page  # noqa: E402

configure_page("Chart")
st.title("Chart")

TIMEFRAMES = (1, 3, 5, 10, 15, 30, 60)
c1, c2, c3 = st.columns([2, 2, 3])
index = c1.radio("Index", INDEX_KEYS, format_func=lambda k: INDEX_PROFILES[k].label, horizontal=True,
                 key="chart_index")
saved_tf = settings_store(index).settings.timeframe_minutes
timeframe = c2.selectbox("Timeframe (minutes)", TIMEFRAMES, index=TIMEFRAMES.index(saved_tf),
                         key=f"chart_tf_{index}", help="Starts on the timeframe saved for trading this index.")
source = c3.selectbox("Data", list(SOURCES), format_func=SOURCES.get, key="chart_source")

o1, o2, o3, o4 = st.columns(4)
show_days = o1.selectbox("Days shown", (1, 2, 3, 5), key="chart_days")
pick_day = None
if source != "live":
    pick_day = o2.date_input("Last day", value=None, key=f"chart_day_{source}",
                             help="Empty = newest day available.")
momentum = o3.checkbox("Show momentum lines (silent)", value=False, key="chart_momentum")
auto = o4.checkbox("Refresh every minute", value=source == "live", key=f"chart_auto_{source}")


def render() -> None:
    minutes = load_minutes(source, index, last_day=pick_day if isinstance(pick_day, date) else None)
    if not minutes:
        if source == "live":
            st.info("No candles yet. Start the trading program first (window 1, folder "
                    "`C:\\Users\\USER\\Desktop\\Kunal\\kunal-quant-claude-version`):  "
                    "`python scripts\\run_paper_session.py`. It loads the morning history at start.")
        elif source == "research":
            st.info("No research data on this PC yet. Run:  `python scripts\\sweep_market_data.py --source yahoo`")
        else:
            st.info("KunalQuant database not found (or no candles for this index/day). It is expected at "
                    "`C:\\Users\\USER\\Desktop\\Kunal\\KunalQuant\\data\\database\\kunal_quant.db` (NIFTY only).")
        return
    payload = chart_payload(minutes, int(timeframe), show_days=int(show_days), momentum=momentum)
    days = payload["days"]
    st.caption(f"{INDEX_PROFILES[index].label} · {timeframe}-minute candles · {', '.join(days)} · "
               f"{len(payload['markers'])} KTMI arrows (green BUY CALL, red BUY PUT) · "
               f"{len(trading_days(minutes))} days loaded (earlier days are KTMI warm-up)")
    show_chart(payload, store_key=f"kq_drawings_{index}",
               title=f"{INDEX_PROFILES[index].label} · {timeframe}m", height=660)


if auto:
    st.fragment(run_every=60)(render)()
else:
    render()

st.caption("Tools on the left: cursor, trend line, horizontal line, vertical line, rectangle, path, fib retracement, "
           "colour, delete selected, clear all. Drawings are saved in this browser for each index. "
           "Charts by TradingView Lightweight Charts™ (Apache 2.0).")
