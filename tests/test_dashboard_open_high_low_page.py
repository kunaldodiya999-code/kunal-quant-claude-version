"""Open High Low dashboard page, rendered with Streamlit's AppTest."""

from pathlib import Path

import pytest

AppTest = pytest.importorskip("streamlit.testing.v1").AppTest
ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "dashboard" / "pages" / "10_Open_High_Low.py"


def test_page_without_data_shows_the_commands(tmp_path, monkeypatch):
    monkeypatch.setenv("KQ_OHOL_DIR", str(tmp_path / "ohol"))
    at = AppTest.from_file(str(PAGE), default_timeout=60).run()
    assert not at.exception
    text = " ".join(w.value for w in at.warning)
    assert "run_open_high_low.py" in text and "open_high_low_backtest.py" in text


def test_page_with_a_live_day_saves_settings(tmp_path, monkeypatch):
    from tests.test_open_high_low import run_day
    run_day(tmp_path)
    folder = tmp_path / "open_high_low"
    monkeypatch.setenv("KQ_OHOL_DIR", str(folder))
    at = AppTest.from_file(str(PAGE), default_timeout=60).run()
    assert not at.exception
    assert at.metric[2].value == "1" and len(at.dataframe) >= 2
    at.number_input(key="oh_top").set_value(3)
    at.selectbox(key="oh_instr").set_value("OPTION")
    at.text_input(key="oh_long_rr").set_value("")
    at.selectbox(key="oh_long_tsl").set_value("PSAR_0.04_0.04_0.10")
    at.button[0].click().run()
    assert not at.exception
    from strategies.open_high_low import OpenHighLowStore
    saved = OpenHighLowStore(folder).settings
    assert saved.top_n == 3 and saved.instrument == "OPTION"
    assert saved.long.target_rr is None and saved.long.tsl_method == "PSAR_0.04_0.04_0.10"
    assert saved.short.target_rr == 2.0
