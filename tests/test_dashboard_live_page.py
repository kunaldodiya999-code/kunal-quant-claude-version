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
    for key in ("NIFTY", "BANKNIFTY", "SENSEX"):
        (tmp_path / key).mkdir()
    return tmp_path


def run(folder):
    app = AppTest.from_file(str(PAGE), default_timeout=30)
    app.run()
    assert not app.exception, app.exception
    return app


def test_page_shows_live_status_and_strike_dropdowns(folder):
    (folder / "NIFTY" / "live_status.json").write_text(json.dumps(status()))
    app = run(folder)
    metrics = {m.label: m.value for m in app.metric}
    assert metrics["NIFTY 50 spot"] == "22,010.50"
    assert metrics["ATM strike"] == "22000"
    assert metrics["FYERS feed"] == "Connected"
    call = app.selectbox(key="call_strike_NIFTY")
    put = app.selectbox(key="put_strike_NIFTY")
    assert call.options == ["ITM1 - 21950 CE", "ATM - 22000 CE", "OTM1 - 22050 CE", "OTM2 - 22100 CE", "OTM3 - 22150 CE"]
    assert put.options == ["ITM1 - 22050 PE", "ATM - 22000 PE", "OTM1 - 21950 PE", "OTM2 - 21900 PE", "OTM3 - 21850 PE"]
    assert not app.warning   # runner is fresh: no "not running" warning


def test_stale_status_tells_owner_to_start_the_runner(folder):
    (folder / "NIFTY" / "live_status.json").write_text(json.dumps(status(fresh=False)))
    app = run(folder)
    assert any("run_paper_session.py" in w.value for w in app.warning)


def test_page_works_before_the_runner_ever_ran(folder):
    app = run(folder)
    assert app.selectbox(key="call_strike_NIFTY").options[1] == "ATM (waiting for live price)"


def click(app, label):
    next(b for b in app.button if b.label == label).click()


def test_saving_the_order_window_writes_settings(folder):
    (folder / "NIFTY" / "live_status.json").write_text(json.dumps(status()))
    app = run(folder)
    app.selectbox(key="call_strike_NIFTY").set_value("OTM2")
    app.checkbox(key="use_atm_NIFTY").check()
    app.checkbox(key="use_atm_plus_1_NIFTY").check()
    click(app, "Save order window")
    app.run()
    saved = json.loads((folder / "NIFTY" / "strategy_settings.json").read_text())
    assert (saved["call_strike"], saved["use_atm"], saved["use_atm_plus_1"]) == ("OTM2", True, True)


def test_saving_bad_times_is_refused_with_a_message(folder):
    app = run(folder)
    from datetime import time as dtime
    app.time_input(key="start_NIFTY").set_value(dtime(15, 20))
    click(app, "Save settings")
    app.run()
    assert any("Not saved" in e.value for e in app.error)
    assert not (folder / "NIFTY" / "strategy_settings.json").exists()


def test_saving_timeframe_and_direction(folder):
    app = run(folder)
    app.selectbox(key="timeframe_NIFTY").set_value(5)
    app.radio(key="direction_NIFTY").set_value("LONG")
    click(app, "Save settings")
    app.run()
    saved = json.loads((folder / "NIFTY" / "strategy_settings.json").read_text())
    assert (saved["timeframe_minutes"], saved["trade_direction"]) == (5, "LONG")


def test_live_orders_banner_and_broker_orders_tab(folder):
    data = status()
    data["orders_mode"] = "LIVE"
    (folder / "NIFTY" / "live_status.json").write_text(json.dumps(data))
    live = folder.parent / "live_trading" / "NIFTY"
    live.mkdir(parents=True, exist_ok=True)
    (live / "live_orders.csv").write_text(
        "time,mode,kind,symbol,requested_qty,status,filled_qty,avg_price,order_ids,paper_price,message\n"
        f"{time.strftime('%Y-%m-%d')}T10:03:05+05:30,LIVE,ENTRY,NSE:NIFTY26O2722000CE,130,FILLED,130,102.0,ORD1,101.5,\n")
    app = run(folder)
    assert any("LIVE ORDERS ARE ON" in e.value for e in app.error)
    assert len(app.tabs) == 6


def test_dry_run_banner(folder):
    data = status()
    data["orders_mode"] = "DRY_RUN"
    (folder / "NIFTY" / "live_status.json").write_text(json.dumps(data))
    app = run(folder)
    assert any("DRY RUN" in i.value for i in app.info) and not app.error


def test_summary_table_and_switching_to_sensex(folder):
    nifty = status()
    nifty["orders_mode"] = "DRY_RUN"
    (folder / "NIFTY" / "live_status.json").write_text(json.dumps(nifty))
    sensex = status()
    sensex.update(spot=75060.0, orders_mode="DRY_RUN", ladders={
        "atm": 75100,
        "call": [{"choice": c, "strike": k} for c, k in
                 zip(("ITM1", "ATM", "OTM1", "OTM2", "OTM3"), (75000, 75100, 75200, 75300, 75400))],
        "put": [{"choice": c, "strike": k} for c, k in
                zip(("ITM1", "ATM", "OTM1", "OTM2", "OTM3"), (75200, 75100, 75000, 74900, 74800))]})
    (folder / "SENSEX" / "live_status.json").write_text(json.dumps(sensex))
    app = run(folder)
    table = app.dataframe[0].value
    assert list(table["Index"]) == ["NIFTY 50", "BANK NIFTY", "SENSEX"]
    assert list(table["Running"]) == ["Yes", "No", "Yes"]

    app.radio(key="index").set_value("SENSEX")
    app.run()
    assert app.selectbox(key="call_strike_SENSEX").options[1] == "ATM - 75100 CE"
    app.checkbox(key="use_atm_plus_1_SENSEX").check()
    click(app, "Save order window")
    app.run()
    saved = json.loads((folder / "SENSEX" / "strategy_settings.json").read_text())
    assert saved["use_atm_plus_1"] is True
    assert not (folder / "NIFTY" / "strategy_settings.json").exists()


def test_trade_in_one_index_only(folder):
    app = run(folder)
    assert app.checkbox(key="trade_in_all").value is True        # default: all three trade
    app.checkbox(key="trade_in_all").uncheck()
    app.multiselect(key="trade_in_pick").set_value(["SENSEX"])
    click(app, "Save trade-in choice")
    app.run()
    saved = {k: json.loads((folder / k / "strategy_settings.json").read_text())["trading_enabled"]
             for k in ("NIFTY", "BANKNIFTY", "SENSEX")}
    assert saved == {"NIFTY": False, "BANKNIFTY": False, "SENSEX": True}
    app.run()                                                      # table refreshes every 3 s
    assert list(app.dataframe[0].value["Trade in"]) == ["OFF (watch only)", "OFF (watch only)", "ON"]


def test_trade_in_all_box_wins_over_the_list(folder):
    app = run(folder)
    app.multiselect(key="trade_in_pick").set_value(["NIFTY"])
    click(app, "Save trade-in choice")                             # "All indexes" still ticked
    app.run()
    assert all(json.loads((folder / k / "strategy_settings.json").read_text())["trading_enabled"]
               for k in ("NIFTY", "BANKNIFTY", "SENSEX"))


def test_trade_management_form_saves_every_choice(folder):
    app = run(folder)
    app.selectbox(key="tm_method_NIFTY").set_value("PSAR_0.04_0.04_0.10")
    app.selectbox(key="tm_source_NIFTY").set_value("SPOT")
    app.selectbox(key="tm_tf_NIFTY").set_value("1")
    app.selectbox(key="tm_trigger_NIFTY").set_value("TOUCH")
    app.selectbox(key="tm_after_NIFTY").set_value("LOCK_1R")
    app.number_input(key="tm_r_NIFTY").set_value(3.0)
    app.number_input(key="tm_p_NIFTY_SUPERTREND_7_1.5_factor").set_value(2.5)
    click(app, "Save trade management")
    app.run()
    saved = json.loads((folder / "NIFTY" / "trade_management.json").read_text())
    assert (saved["tsl_method"], saved["tsl_source"], saved["tsl_timeframe"], saved["tsl_trigger"]) == (
        "PSAR_0.04_0.04_0.10", "SPOT", "1", "TOUCH")
    assert (saved["after_partial"], saved["partial_r"]) == ("LOCK_1R", 3.0)
    assert saved["method_params"]["SUPERTREND_7_1.5"] == {"atr_length": 7, "factor": 2.5}
    assert saved["initial_sl_pct"] == 30.0 and saved["partial_pct"] == 50.0      # untouched defaults
    assert json.loads((folder / "NIFTY" / "allocation.json").read_text()) == {"mode": "PERCENT", "value": 20.0}
    assert not (folder / "SENSEX" / "trade_management.json").exists()


def test_open_trade_shows_its_tsl_and_takes_a_manual_stop(folder):
    data = status()
    data["positions"][0].update(trade_id="STRATEGY_A:1:NSE:NIFTY26O2722000CE", tsl="Manual", tsl_chart="OPTION",
                                tsl_timeframe=3, tsl_trigger="CLOSE", tsl_stop=None)
    (folder / "NIFTY" / "live_status.json").write_text(json.dumps(data))
    app = run(folder)
    app.number_input(key="manual_STRATEGY_A:1:NSE:NIFTY26O2722000CE").set_value(95.5)
    click(app, "Save manual stops")
    app.run()
    assert json.loads((folder / "NIFTY" / "manual_stops.json").read_text()) == {
        "STRATEGY_A:1:NSE:NIFTY26O2722000CE": 95.5}
