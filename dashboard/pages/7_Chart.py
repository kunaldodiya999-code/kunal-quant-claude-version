"""Chart (TradingView style) for NIFTY, BANK NIFTY and SENSEX.

On the chart itself: timeframe buttons (1m 3m 5m 10m 15m 30m 1h 1D), signal filter
(Both / Long / Short / Off), Indicators menu (Volume from futures, KTMI Uni Lite, VWAP with
1/2/3 standard-deviation bands, Bollinger Bands, OI Profile, Smart Money Concepts) and
drawing tools (horizontal, vertical, rectangle, path, measure, fixed range volume profile).
The index has no volume: volume is the nearest futures contract's. Read-only: never trades.
"""

import sys
from datetime import date
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from chart_component import show_chart, write_live_data  # noqa: E402
from data.chart import SOURCES, chart_payload, load_chart_data, trading_days  # noqa: E402
from data.live import INDEX_KEYS, settings_store  # noqa: E402
from strategies.index_profiles import INDEX_PROFILES  # noqa: E402
from theme import configure_page  # noqa: E402

configure_page("Chart")
st.title("Chart")

c1, c2, c3, c4 = st.columns([3, 3, 1.4, 1.6])
index = c1.radio("Index", INDEX_KEYS, format_func=lambda k: INDEX_PROFILES[k].label, horizontal=True,
                 key="chart_index")
source = c2.selectbox("Data", list(SOURCES), format_func=SOURCES.get, key="chart_source")
show_days = c3.selectbox("Days", (1, 2, 3, 5, 10), index=1, key="chart_days",
                         help="Trading days shown on intraday timeframes (1D shows about a year).")
pick_day = None
if source != "live":
    pick_day = c4.date_input("Last day", value=None, key=f"chart_day_{source}", help="Empty = newest day available.")


def build():
    data = load_chart_data(source, index, last_day=pick_day if isinstance(pick_day, date) else None)
    if not data.minutes:
        return data, None
    timeframe = settings_store(index).settings.timeframe_minutes
    return data, chart_payload(data, index=index, show_days=int(show_days), timeframe=timeframe)


data, payload = build()
if payload is None:
    if source == "live":
        st.info("No candles yet. Start the trading program first (window 1, folder "
                "`C:\\Users\\USER\\Desktop\\Kunal\\kunal-quant-claude-version`):  "
                "`python scripts\\run_paper_session.py`. It loads the morning history at start.")
    elif source == "research":
        st.info("No research data on this PC yet. Run:  `python scripts\\sweep_market_data.py --source both`")
    else:
        st.info("KunalQuant database not found (or no candles for this index/day). It is expected at "
                "`C:\\Users\\USER\\Desktop\\Kunal\\KunalQuant\\data\\database\\kunal_quant.db` (NIFTY only).")
    st.stop()

live_name = f"{index}_{source}_{show_days}"
data_url = write_live_data(live_name, payload) if source == "live" else None
st.caption(f"{INDEX_PROFILES[index].label} · days {', '.join(payload['days'])} · "
           f"volume: {data.volume_source or 'none in this data (VWAP uses equal weights, profile counts time)'} · "
           f"option-chain OI: {'yes, ' + str(payload['oi'].get('updated_at')) if payload['oi'] else 'not available'} · "
           f"{len(trading_days(data.minutes))} days loaded (earlier days warm up KTMI)")
show_chart(payload, data_url=data_url, height=760)

if source == "live":
    @st.fragment(run_every=10)
    def keep_fresh() -> None:
        """Save fresh data every 10 s; the chart picks it up without reloading."""
        fresh_data, fresh = build()
        if fresh is not None:
            write_live_data(live_name, fresh)
    keep_fresh()

st.caption("On the chart: timeframe buttons at the top, Signals Both / Long / Short / Off, "
           "ƒx Indicators (tick to add, ⚙ for settings, ✕ in the legend to remove). Tools on the left: cursor, "
           "horizontal line, vertical line, rectangle, path, measure, volume profile, colour, settings, delete, "
           "clear all. Everything you choose is saved in this browser for each index. "
           "Charts by TradingView Lightweight Charts™ (Apache 2.0).")
