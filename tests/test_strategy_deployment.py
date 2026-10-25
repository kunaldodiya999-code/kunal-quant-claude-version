"""Deploy one, several or all strategies: registry, launcher, KTMI runner check, Strategies page."""

import io
import json
from pathlib import Path

import pytest

from strategies.gap_reversal import GapReversalStore
from strategies.registry import STRATEGIES, DeploymentStore, parse_keys

AppTest = pytest.importorskip("streamlit.testing.v1").AppTest
ROOT = Path(__file__).resolve().parents[1]


def test_defaults_ktmi_deployed_gap_reversal_not(tmp_path):
    store = DeploymentStore(tmp_path)
    assert store.deployed() == ["KTMI_UNI_LITE"]
    assert set(STRATEGIES) == {"KTMI_UNI_LITE", "GAP_REVERSAL", "OPEN_HIGH_LOW", "OPENING_SCALP", "HFT_GAP_OPEN"}


@pytest.mark.parametrize("text, keys", [("all", ["KTMI_UNI_LITE", "GAP_REVERSAL", "OPEN_HIGH_LOW"]), ("none", []),
                                        ("gap_reversal", ["GAP_REVERSAL"]),
                                        ("KTMI_UNI_LITE, GAP_REVERSAL", ["KTMI_UNI_LITE", "GAP_REVERSAL"])])
def test_single_several_or_all(tmp_path, text, keys):
    store = DeploymentStore(tmp_path)
    assert store.set_deployed(parse_keys(text)) == keys
    assert DeploymentStore(tmp_path).deployed() == keys
    # Gap Reversal's own "Strategy ON" switch is the same flag
    assert GapReversalStore(tmp_path / "gap_reversal").settings.enabled == ("GAP_REVERSAL" in keys)
    from strategies.open_high_low import OpenHighLowStore
    assert OpenHighLowStore(tmp_path / "open_high_low").settings.enabled == ("OPEN_HIGH_LOW" in keys)


def test_research_strategies_cannot_be_deployed():
    with pytest.raises(ValueError):
        parse_keys("OPENING_SCALP")
    with pytest.raises(ValueError):
        parse_keys("SOMETHING")


class FakeProc:
    def __init__(self, cmd, **kw):
        self.cmd = cmd
        self.stdout = io.StringIO(f"hello from {Path(cmd[1]).name}\n")

    def wait(self):
        return 0

    def terminate(self):
        pass


def test_launcher_starts_every_deployed_strategy(tmp_path, capsys):
    from scripts.run_strategies import main
    started = []

    def popen(cmd, **kw):
        started.append(cmd)
        return FakeProc(cmd)

    assert main(["--data-folder", str(tmp_path), "--deploy", "all", "--index", "NIFTY", "--stop-at", "15:00"],
                popen=popen) == 0
    scripts = [Path(c[1]).name for c in started]
    assert scripts == ["run_paper_session.py", "run_gap_reversal.py", "run_open_high_low.py"]
    assert "--index" in started[0] and "--index" not in started[1] and "--live-orders" not in started[0]
    assert all(["--stop-at", "15:00"] == c[c.index("--stop-at"):c.index("--stop-at") + 2] for c in started)
    out = capsys.readouterr().out
    assert "[KTMI_UNI_LITE] hello from run_paper_session.py" in out and "[GAP_REVERSAL] hello" in out
    started.clear()
    assert main(["--data-folder", str(tmp_path), "--deploy", "none"], popen=popen) == 0 and started == []
    assert main(["--data-folder", str(tmp_path), "--list"], popen=popen) == 0 and started == []


def test_ktmi_runner_does_nothing_when_not_deployed(tmp_path, capsys):
    from scripts.run_paper_session import main
    (tmp_path / "strategies.json").write_text(json.dumps({"deployed": {"KTMI_UNI_LITE": False}}), encoding="utf-8")
    assert main(["--data-folder", str(tmp_path)], client=object()) == 0
    assert "NOT deployed" in capsys.readouterr().out


def test_strategies_page_saves_the_choice(tmp_path, monkeypatch):
    monkeypatch.setenv("KQ_PAPER_DIR", str(tmp_path / "paper_trading"))
    monkeypatch.setenv("KQ_GAP_DIR", str(tmp_path / "gap_reversal"))
    monkeypatch.setenv("KQ_OHOL_DIR", str(tmp_path / "open_high_low"))
    at = AppTest.from_file(str(ROOT / "dashboard" / "pages" / "9_Strategies.py"), default_timeout=60).run()
    assert not at.exception
    at.checkbox(key="deploy_GAP_REVERSAL").check()
    at.checkbox(key="deploy_KTMI_UNI_LITE").uncheck()
    at.button[0].click().run()
    assert not at.exception
    assert DeploymentStore(tmp_path, gap_folder=tmp_path / "gap_reversal").deployed() == ["GAP_REVERSAL"]
    table = at.dataframe[0].value
    assert list(table[table["deployed"]]["name"]) == ["Gap Reversal (stocks)"]
    assert at.checkbox(key="deploy_OPENING_SCALP").disabled
