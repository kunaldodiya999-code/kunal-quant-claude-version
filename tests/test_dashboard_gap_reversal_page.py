"""Gap Reversal dashboard page, rendered with Streamlit's AppTest."""

from pathlib import Path

import pytest

AppTest = pytest.importorskip("streamlit.testing.v1").AppTest
ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "dashboard" / "pages" / "8_Gap_Reversal.py"


def test_page_without_data_shows_the_commands(tmp_path, monkeypatch):
    monkeypatch.setenv("KQ_GAP_DIR", str(tmp_path / "gap"))
    monkeypatch.setenv("KQ_RESEARCH_DIR", str(tmp_path / "research"))
    at = AppTest.from_file(str(PAGE), default_timeout=60).run()
    assert not at.exception
    text = " ".join(w.value for w in at.warning)
    assert "run_gap_reversal.py" in text and "gap_reversal_backtest.py" in text


def test_page_with_scanner_and_backtest(tmp_path, monkeypatch):
    from tests.test_gap_reversal_live import run
    run(tmp_path, enabled=True)
    gap = tmp_path / "gap_reversal"
    (gap / "backtest_summary.csv").write_text(
        "group,side,entry_mode,rr,trades,win_rate_pct,profit_factor,avg_r,total_r,targets,stops,time_exits\n"
        "ALL,SHORT,BREAK,2.0,4,50.0,2.0,0.5,2.0,2,2,0\n"
        "SETUP: DOJI,SHORT,BREAK,2.0,4,50.0,2.0,0.5,2.0,2,2,0\n", encoding="utf-8")
    (gap / "backtest_trades.csv").write_text("symbol,day,r\nHCLTECH,2026-10-20,2.0\n", encoding="utf-8")
    monkeypatch.setenv("KQ_GAP_DIR", str(gap))
    monkeypatch.setenv("KQ_RESEARCH_DIR", str(tmp_path / "research"))
    at = AppTest.from_file(str(PAGE), default_timeout=60).run()
    assert not at.exception
    assert not at.warning
    assert at.metric[2].value == "1"                     # one paper trade
    assert len(at.dataframe) >= 5
    # settings form saves both sides separately
    at.number_input(key="gr_gap").set_value(2.0)
    at.selectbox(key="gr_long_entry").set_value("CLOSE")
    at.checkbox(key="gr_short_HARAMI").set_value(False)
    at.text_input(key="gr_long_rr").set_value("")                   # empty box = TSL exit
    at.selectbox(key="gr_long_tsl").set_value("PSAR_0.04_0.04_0.10")
    at.number_input(key="gr_cap_all").set_value(3)
    at.text_input(key="gr_entry_from").set_value("09:45")
    at.number_input(key="gr_cap_long").set_value(2)
    at.button[0].click().run()
    assert not at.exception
    from strategies.gap_reversal import GapReversalStore
    saved = GapReversalStore(gap).settings
    assert saved.gap_pct == 2.0 and saved.long.entry_mode == "CLOSE" and saved.short.entry_mode == "BREAK"
    assert saved.entry_from == "09:45" and saved.max_trades_per_day == 3 and saved.max_long_per_day == 2 and saved.max_short_per_day == 0
    assert saved.long.target_rr is None and saved.long.tsl_method == "PSAR_0.04_0.04_0.10" and saved.short.target_rr == 2
    at.text_input(key="gr_short_rr").set_value("two")
    at.button[0].click().run()
    assert not at.exception and any("Not saved" in e.value for e in at.error)
    assert saved.short.patterns["HARAMI"] is False and saved.long.patterns["HARAMI"] is True


def test_chart_payload_carries_the_strength_marks():
    from dashboard.data.chart import IST_OFFSET, ChartData, chart_payload
    from tests.test_gap_reversal import hcl_like_day
    _bars, minutes = hcl_like_day()
    t = minutes[20].timestamp
    payload = chart_payload(ChartData(minutes, minutes, [], None, "stock volume"), index="HCLTECH", show_days=1,
                            timeframe=5, marks=[{"time": t, "side": "SHORT", "text": "78%"}])
    assert payload["marks"] == [{"time": t + IST_OFFSET, "side": "SHORT", "text": "78%"}]
    assert "HCLTECH" in payload["title"]
