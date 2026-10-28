"""The screens open without errors: FYERS login page, then the terminal (pretend FYERS, no network)."""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

import terminal.engine as engine
import terminal.fyers as fyers
from tests.fakes import FakeFyers, master

APP = str(Path(__file__).resolve().parents[1] / "app.py")


def test_login_page_asks_for_the_app_details_first():
    at = AppTest.from_file(APP, default_timeout=30).run()
    assert not at.exception
    assert any("Log in with FYERS" in s.value for s in at.subheader)
    assert [t.label for t in at.text_input][:3] == ["App ID", "Secret ID", "Redirect URL"]


def test_terminal_page_with_a_token(monkeypatch, tmp_path):
    monkeypatch.setenv("FYERS_CLIENT_ID", "ABCD-100")
    monkeypatch.setenv("FYERS_SECRET_KEY", "s")
    fyers.save_token("tok")
    fake = FakeFyers()
    fake.set_price("NSE:NIFTY50-INDEX", 25010)
    monkeypatch.setattr(fyers, "Fyers", lambda cid, tok: fake)
    monkeypatch.setattr(engine, "load_master", lambda name, today, folder=None: master())
    monkeypatch.setattr(engine, "CHART_FILE", tmp_path / "chart.json")
    monkeypatch.setattr(engine.Terminal, "start", lambda self: self.tick())     # one pass, no thread
    at = AppTest.from_file(APP, default_timeout=30).run()
    assert not at.exception, at.exception
    assert [c.label for c in at.checkbox] == ["Call", "Put"]
    assert any(m.label == "Funds available" and "50,000" in m.value for m in at.metric)
    assert any("25000" in m.value and "CALL" in m.value for m in at.markdown)  # the option chain table
    at.checkbox[1].uncheck().run()
    assert not at.exception
    from terminal.settings import SettingsStore
    assert SettingsStore().load().put_on is False
    at.radio[2].set_value("PER_LOT").run()
    assert any(n.label == "Per lot amount (Rs)" for n in at.number_input)


def test_open_trade_and_todays_trades_show(monkeypatch, tmp_path):
    import json
    from datetime import datetime
    from terminal.candles import IST
    from terminal.engine import TRADE_FIELDS
    monkeypatch.setenv("FYERS_CLIENT_ID", "ABCD-100")
    monkeypatch.setenv("FYERS_SECRET_KEY", "s")
    fyers.save_token("tok2")
    folder = fyers.data_dir()
    today = datetime.now(IST).date().isoformat()
    pos = {"day": today, "index": "NIFTY", "side": "CALL", "symbol": "NSE:NIFTY26N0425000CE", "strike": 25000,
           "lot_size": 65, "lots": 2, "qty": 130, "entry_time": "10:03:05", "entry_price": 101.5, "stop": 96.0,
           "mode": "PAPER", "signal_bar": 0}
    (folder / "state.json").write_text(json.dumps({"position": pos}))
    (folder / "trades.csv").write_text(",".join(TRADE_FIELDS) + "\n" + ",".join(
        [today, "NIFTY", "PUT", "NSE:NIFTY26N0425000PE", "25000", "1", "65", "09:40:03", "120", "110", "09:52:03",
         "131", "715", "Direction crossed above 0", "PAPER"]) + "\n")
    fake = FakeFyers()
    fake.set_price("NSE:NIFTY50-INDEX", 25010)
    fake.set_price("NSE:NIFTY26N0425000CE", 104.0)
    monkeypatch.setattr(fyers, "Fyers", lambda cid, tok: fake)
    monkeypatch.setattr(engine, "load_master", lambda name, today, folder=None: master())
    monkeypatch.setattr(engine, "CHART_FILE", tmp_path / "chart.json")
    eleven = datetime.now(IST).replace(hour=11, minute=0, second=0)          # market hours: no 15:10 exit

    def one_pass(self):
        self.clock = lambda: eleven
        self.tick()
    monkeypatch.setattr(engine.Terminal, "start", one_pass)
    at = AppTest.from_file(APP, default_timeout=30).run()
    assert not at.exception, at.exception
    assert any("NSE:NIFTY26N0425000CE" in m.value and "P&L" in m.value for m in at.markdown)
    assert any(m.label == "Funds utilized" and m.value.startswith("26.4") for m in at.metric)   # 13,195 / 50,000
    assert any(m.label == "Today's P&L" and "715" in m.value for m in at.metric)
