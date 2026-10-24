"""Chart page: minute candle journal from the runner, chart data, the page and its drawing tools."""

import csv
import math
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from indicators.ktmi.universal import OHLCData
from indicators.ktmi_uni_lite import UNI_LITE_CORE, calculate_uni_lite
from market_data.resampling import Candle, aggregate_day
from paper_trading.market_data_pipeline import PaperMarketDataPipeline
from paper_trading.minute_journal import MinuteCandleJournal

IST = ZoneInfo("Asia/Kolkata")
ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "dashboard" / "pages" / "7_Chart.py"


def ts(h, m, day=21):
    return int(datetime(2026, 10, day, h, m, tzinfo=IST).timestamp())


def wave_days(days=(19, 20, 21)):
    out = []
    for d in days:
        for i in range(375):
            p = 22000 + 60 * math.sin(i / 25) + d
            out.append(Candle(ts(9, 15, d) + 60 * i, p, p + 3, p - 3, p + 1, 0))
    return out


def rows(path):
    with open(path, newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


# ------------------------------------------------------------- minute journal

def test_pipeline_sends_seeded_and_live_minutes_to_the_journal_once(tmp_path):
    journal = MinuteCandleJournal(tmp_path)
    pipe = PaperMarketDataPipeline(resolution_minutes=3, signal_evaluator=lambda bars, **_: [],
                                   minute_sink=journal.record)
    seeded = [Candle(ts(9, 15 + i), 100 + i, 101 + i, 99 + i, 100.5 + i, 0) for i in range(5)]
    pipe.seed_history("NSE:NIFTY50-INDEX", seeded)
    tick = lambda t, p: {"symbol": "NSE:NIFTY50-INDEX", "last_traded_time": t + 5, "ltp": p, "type": "sf"}
    pipe.on_message(tick(ts(9, 20), 110))
    pipe.on_message(tick(ts(9, 21), 111))       # closes the 09:20 minute
    saved = rows(tmp_path / "minute_candles.csv")
    assert [r["time"][-5:] for r in saved] == ["09:15", "09:16", "09:17", "09:18", "09:19", "09:20"]
    # A restart seeds the same minutes again: nothing is written twice.
    MinuteCandleJournal(tmp_path).record("NSE:NIFTY50-INDEX", seeded)
    assert len(rows(tmp_path / "minute_candles.csv")) == 6


# ----------------------------------------------------------------- chart data

def test_chart_payload_matches_the_locked_ktmi_and_shows_only_the_last_days():
    from dashboard.data.chart import IST_OFFSET, chart_payload
    minutes = wave_days()
    payload = chart_payload(minutes, 3, show_days=1)
    day = [c for c in minutes if c.timestamp >= ts(9, 15, 21)]
    bars = [b for d in (19, 20, 21) for b in aggregate_day([c for c in minutes if
            datetime.fromtimestamp(c.timestamp, IST).day == d], 3) if b.complete]
    values = calculate_uni_lite([OHLCData(b.open, b.high, b.low, b.close) for b in bars], UNI_LITE_CORE)
    shown = [(b, v) for b, v in zip(bars, values) if b.timestamp >= day[0].timestamp]
    assert payload["days"] == ["2026-10-21"] and len(payload["candles"]) == len(shown) == 125
    assert payload["candles"][0]["time"] == ts(9, 15) + IST_OFFSET           # axis shows IST
    assert payload["lines"]["long_speed"][-1]["value"] == round(shown[-1][1].long_speed, 4)
    expected = sum(v.long_buy for _, v in shown) + sum(v.short_buy for _, v in shown)
    assert len(payload["markers"]) == expected > 0
    assert "momentum_speed" not in payload["lines"]
    assert "momentum_speed" in chart_payload(minutes, 5, momentum=True)["lines"]


def test_chart_html_has_every_drawing_tool_and_the_local_library():
    from dashboard.chart_component import chart_html
    html = chart_html({"candles": [], "markers": [], "lines": {}, "levels": {}, "bar_seconds": 180,
                       "note": "</script><b>"}, store_key="kq_drawings_NIFTY", title="NIFTY 50")
    for tool in ("cursor", "trend", "hline", "vline", "rect", "path", "fib"):
        assert f'data-tool="{tool}"' in html
    assert "TradingView Lightweight Charts" in html and "unpkg" not in html and "cdn" not in html.lower()
    assert "<\\/script><b>" in html                                   # data cannot break out of the script


# ----------------------------------------------------------------------- page

AppTest = pytest.importorskip("streamlit.testing.v1").AppTest


def test_chart_page_without_candles_explains_how_to_start(tmp_path, monkeypatch):
    monkeypatch.setenv("KQ_PAPER_DIR", str(tmp_path))
    app = AppTest.from_file(str(PAGE), default_timeout=60).run()
    assert not app.exception
    assert any("run_paper_session.py" in i.value for i in app.info)


def test_chart_page_draws_live_candles_for_each_index(tmp_path, monkeypatch):
    monkeypatch.setenv("KQ_PAPER_DIR", str(tmp_path))
    for key in ("NIFTY", "SENSEX"):
        MinuteCandleJournal(tmp_path / key).record(key, wave_days())
    app = AppTest.from_file(str(PAGE), default_timeout=60).run()
    assert not app.exception and not app.info
    assert any("3-minute candles" in c.value and "2026-10-21" in c.value for c in app.caption)
    app.radio(key="chart_index").set_value("BANKNIFTY").run()
    assert any("run_paper_session.py" in i.value for i in app.info)      # no BANK NIFTY candles yet
    app.radio(key="chart_index").set_value("SENSEX").run()
    app.selectbox(key="chart_tf_SENSEX").set_value(15).run()
    assert not app.exception and any("15-minute candles" in c.value for c in app.caption)
