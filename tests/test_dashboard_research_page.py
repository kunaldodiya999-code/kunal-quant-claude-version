"""Research Backtest dashboard page, rendered with Streamlit's AppTest."""

from pathlib import Path

import pytest

AppTest = pytest.importorskip("streamlit.testing.v1").AppTest
ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "dashboard" / "pages" / "6_Research_Backtest.py"


def test_page_without_results_shows_the_commands(tmp_path, monkeypatch):
    monkeypatch.setenv("KQ_RESEARCH_DIR", str(tmp_path))
    at = AppTest.from_file(str(PAGE), default_timeout=30).run()
    assert not at.exception
    text = " ".join(w.value for w in at.warning)
    assert "sweep_market_data.py" in text and "ktmi_accuracy.py" in text and "opening_scalp_backtest.py" in text


def test_page_with_results(tmp_path, monkeypatch, capsys):
    from tests.test_research_backtests import run_research_commands
    assert run_research_commands(tmp_path) == (0, 0)
    capsys.readouterr()
    (tmp_path / "research" / "sweep_report.csv").write_text(
        "series,source,resolution,days,clean_days\nNIFTY,yahoo,1m,18,17\n", encoding="utf-8")
    monkeypatch.setenv("KQ_RESEARCH_DIR", str(tmp_path / "research"))
    at = AppTest.from_file(str(PAGE), default_timeout=30).run()
    assert not at.exception
    assert not at.warning
    assert len(at.dataframe) >= 3
