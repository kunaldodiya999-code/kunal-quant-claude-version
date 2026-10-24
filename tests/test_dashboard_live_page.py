"""Live Paper Trading dashboard page, rendered with Streamlit's AppTest."""

import json
import time
from pathlib import Path

import pytest

AppTest = pytest.importorskip("streamlit.testing.v1").AppTest
PAGE = Path(__file__).resolve().parents[1] / "dashboard" / "pages" / "0_Live_Paper_Trading.py"


def status(fresh=True):
    return {
        "mode": "PAPER", "updated_at": "2026-10-26 10:15:00", "updated_epoch": time.time() - (1 if fresh else 999),
        "feed": {"connected": True, "messages": 120, "subscribed": [], "last_error": None},
        "spot": 22010.5, "spot_time": "2026-10-26 10:14:59",
        "ladders": {"atm": 22000,
                    "call": [{"choice": c, "strike": k} for c, k in
                             zip(("ITM1", "ATM", "OTM1", "OTM2", "OTM3"), (21950, 22000, 22050, 22100, 22150))],
                    "put": [{"choice": c, "strike": k} for c, k in
                            zip(("ITM1", "ATM", "OTM1", "OTM2", "OTM3"), (22050, 22000, 21950, 21900, 21850))]},
        "contracts": {"nearest_expiry": "2026-10-27", "lot_size": 65},
        "settings": None,
        "positions": [{"slot": "Slot 1", "symbol": "NSE:NIFTY26O2722000CE", "side": "BUY CALL", "entry": 101.5,
                       "quantity": 130, "stop": 71.05, "target": 192.85, "mark": 105.0, "unrealised": 455.0,
                       "opened_at": "2026-10-26 10:03:01"}],
        "account": {"equity": 100455.0, "day_pnl": 455.0, "realised": 0.0, "unrealised": 455.0,
                    "costs": 0.0, "available_cash": 86805.0},
    }


@pytest.fixture()
def folder(tmp_path, monkeypatch):
    monkeypatch.setenv("KQ_PAPER_DIR", str(tmp_path))
    return tmp_path


def run(folder):
    app = AppTest.from_file(str(PAGE), default_timeout=30)
    app.run()
    assert not app.exception, app.exception
    return app


def test_page_shows_live_status_and_strike_dropdowns(folder):
    (folder / "live_status.json").write_text(json.dumps(status()))
    app = run(folder)
    metrics = {m.label: m.value for m in app.metric}
    assert metrics["NIFTY spot"] == "22,010.50"
    assert metrics["ATM strike"] == "22000"
    assert metrics["FYERS feed"] == "Connected"
    call = app.selectbox(key="call_strike")
    put = app.selectbox(key="put_strike")
    assert call.options == ["ITM1 - 21950 CE", "ATM - 22000 CE", "OTM1 - 22050 CE", "OTM2 - 22100 CE", "OTM3 - 22150 CE"]
    assert put.options == ["ITM1 - 22050 PE", "ATM - 22000 PE", "OTM1 - 21950 PE", "OTM2 - 21900 PE", "OTM3 - 21850 PE"]
    assert not app.warning   # runner is fresh: no "not running" warning


def test_stale_status_tells_owner_to_start_the_runner(folder):
    (folder / "live_status.json").write_text(json.dumps(status(fresh=False)))
    app = run(folder)
    assert any("run_paper_session.py" in w.value for w in app.warning)


def test_page_works_before_the_runner_ever_ran(folder):
    app = run(folder)
    assert app.selectbox(key="call_strike").options[1] == "ATM (waiting for live price)"


def test_saving_the_order_window_writes_settings(folder):
    (folder / "live_status.json").write_text(json.dumps(status()))
    app = run(folder)
    app.selectbox(key="call_strike").set_value("OTM2")
    app.checkbox(key="use_atm").check()
    app.checkbox(key="use_atm_plus_1").check()
    app.button[0].click()   # "Save order window"
    app.run()
    saved = json.loads((folder / "strategy_settings.json").read_text())
    assert (saved["call_strike"], saved["use_atm"], saved["use_atm_plus_1"]) == ("OTM2", True, True)


def test_saving_bad_times_is_refused_with_a_message(folder):
    app = run(folder)
    from datetime import time as dtime
    app.time_input(key="start").set_value(dtime(15, 20))
    app.button[1].click()   # "Save settings"
    app.run()
    assert any("Not saved" in e.value for e in app.error)
    assert not (folder / "strategy_settings.json").exists()


def test_saving_timeframe_and_direction(folder):
    app = run(folder)
    app.selectbox(key="timeframe").set_value(5)
    app.radio(key="direction").set_value("LONG")
    app.button[1].click()
    app.run()
    saved = json.loads((folder / "strategy_settings.json").read_text())
    assert (saved["timeframe_minutes"], saved["trade_direction"]) == (5, "LONG")


def test_live_orders_banner_and_broker_orders_tab(folder):
    data = status()
    data["orders_mode"] = "LIVE"
    (folder / "live_status.json").write_text(json.dumps(data))
    live = folder.parent / "live_trading"
    live.mkdir(exist_ok=True)
    (live / "live_orders.csv").write_text(
        "time,mode,kind,symbol,requested_qty,status,filled_qty,avg_price,order_ids,paper_price,message\n"
        f"{time.strftime('%Y-%m-%d')}T10:03:05+05:30,LIVE,ENTRY,NSE:NIFTY26O2722000CE,130,FILLED,130,102.0,ORD1,101.5,\n")
    app = run(folder)
    assert any("LIVE ORDERS ARE ON" in e.value for e in app.error)
    assert len(app.tabs) == 5


def test_dry_run_banner(folder):
    data = status()
    data["orders_mode"] = "DRY_RUN"
    (folder / "live_status.json").write_text(json.dumps(data))
    app = run(folder)
    assert any("DRY RUN" in i.value for i in app.info) and not app.error
