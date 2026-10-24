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

def futures_for(minutes, skip=()):
    return [Candle(c.timestamp, c.open + 30, c.high + 30, c.low + 30, c.close + 30, 1000 + i % 7)
            for i, c in enumerate(minutes) if i not in skip]


def test_every_timeframe_uses_the_locked_ktmi_on_complete_bars():
    from dashboard.data.chart import IST_OFFSET, TIMEFRAMES, ChartData, chart_payload
    minutes = wave_days()
    payload = chart_payload(ChartData(minutes), index="NIFTY", show_days=1)
    assert list(payload["frames"]) == list(TIMEFRAMES) and payload["days"] == ["2026-10-21"]
    bars = [b for d in (19, 20, 21) for b in aggregate_day([c for c in minutes if
            datetime.fromtimestamp(c.timestamp, IST).day == d], 3) if b.complete]
    values = calculate_uni_lite([OHLCData(b.open, b.high, b.low, b.close) for b in bars], UNI_LITE_CORE)
    shown = [(b, v) for b, v in zip(bars, values) if b.timestamp >= ts(9, 15)]
    three = payload["frames"]["3"]
    assert len(three["t"]) == len(shown) == 125 and three["t"][0] == ts(9, 15) + IST_OFFSET   # axis shows IST
    assert three["ktmi"]["long_speed"][-1] == round(shown[-1][1].long_speed, 4)
    assert len(three["long"]) == sum(v.long_buy for _, v in shown) and three["long"]
    assert len(three["short"]) == sum(v.short_buy for _, v in shown)
    assert len(payload["frames"]["1"]["t"]) == 375 and len(payload["frames"]["60"]["t"]) == 7
    assert set(three["v"]) == {0}                                          # spot data alone: no volume


def test_forming_bar_is_drawn_without_ktmi_and_futures_volume_is_added():
    from dashboard.data.chart import ChartData, chart_payload
    minutes = wave_days()[:-1]                                             # 15:28 closed, 15:27 bar unfinished
    payload = chart_payload(ChartData(minutes, futures_for(minutes, skip={755})), index="NIFTY", show_days=1)
    three = payload["frames"]["3"]
    assert len(three["t"]) == 125 and three["ktmi"]["long_speed"][-1] is None
    one = payload["frames"]["1"]
    assert one["v"][0] == 1000 + (375 * 2) % 7 and 0 in one["v"]          # minute with no futures data = 0
    assert three["v"][0] == sum(one["v"][:3])


def test_daily_frame_and_option_chain():
    from dashboard.data.chart import ChartData, chart_payload
    minutes = wave_days()
    daily = [Candle(ts(0, 0, d), 100, 110, 90, 105, 5_000_000) for d in (15, 16)]
    oi = {"rows": [{"strike": 22000, "call_oi": 1, "put_oi": 2}], "updated_at": "10:00"}
    payload = chart_payload(ChartData(minutes, (), daily, oi), index="NIFTY")
    d = payload["frames"]["D"]
    assert len(d["t"]) == 5 and d["v"][:2] == [5_000_000, 5_000_000]        # 2 saved days + 3 from minutes
    assert all(t % 86400 == 0 for t in d["t"])                              # shown at their date
    assert payload["oi"] == oi and payload["version"]


def test_chart_html_has_the_owner_tools_and_the_local_library():
    from dashboard.chart_component import chart_html
    html = chart_html({"title": "NIFTY 50", "note": "</script><b>"}, data_url="app/static/live/x.json")
    for tool in ("cursor", "hline", "vline", "rect", "path", "measure", "vprofile"):
        assert f'data-tool="{tool}"' in html
    for gone in ("trend", "fib"):
        assert f'data-tool="{gone}"' not in html
    for sig in ("Both", "Long", "Short", "Off"):
        assert f'data-sig="{sig}"' in html
    assert "TradingView Lightweight Charts" in html and "unpkg" not in html and "cdn" not in html.lower()
    assert "KQInd" in html and "<\\/script><b>" in html                  # data cannot break out of the script


def test_static_serving_is_switched_on_for_live_updates():
    for folder in (ROOT, ROOT / "dashboard"):
        assert "enableStaticServing = true" in (folder / ".streamlit" / "config.toml").read_text()


# ----------------------------------------------------------------------- page

AppTest = pytest.importorskip("streamlit.testing.v1").AppTest


def test_chart_page_without_candles_explains_how_to_start(tmp_path, monkeypatch):
    monkeypatch.setenv("KQ_PAPER_DIR", str(tmp_path))
    app = AppTest.from_file(str(PAGE), default_timeout=60).run()
    assert not app.exception
    assert any("run_paper_session.py" in i.value for i in app.info)


def test_chart_page_draws_live_candles_for_each_index(tmp_path, monkeypatch):
    import json
    from paper_trading.chart_feeds import CandleFile
    monkeypatch.setenv("KQ_PAPER_DIR", str(tmp_path))
    for key in ("NIFTY", "SENSEX"):
        MinuteCandleJournal(tmp_path / key).record(key, wave_days())
    CandleFile(tmp_path / "NIFTY" / "futures_minute_candles.csv").write("NSE:NIFTY26OCTFUT", futures_for(wave_days()))
    (tmp_path / "NIFTY" / "oi_chain.json").write_text(json.dumps(
        {"rows": [{"strike": 22000, "call_oi": 5, "put_oi": 6}], "updated_at": "2026-10-21 15:29:00"}))
    app = AppTest.from_file(str(PAGE), default_timeout=60).run()
    assert not app.exception and not app.info
    text = " ".join(c.value for c in app.caption)
    assert "NSE:NIFTY26OCTFUT futures" in text and "option-chain OI: yes" in text and "2026-10-21" in text
    live = ROOT / "dashboard" / "static" / "live" / "NIFTY_live_2.json"
    assert json.loads(live.read_text())["frames"]["1"]["v"][0] > 0          # what the chart polls
    app.radio(key="chart_index").set_value("BANKNIFTY").run()
    assert any("run_paper_session.py" in i.value for i in app.info)      # no BANK NIFTY candles yet
    app.radio(key="chart_index").set_value("SENSEX").run()
    assert not app.exception and "volume: none" in " ".join(c.value for c in app.caption)
