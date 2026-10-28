"""FYERS answers -> prices, funds, contracts and the chain; limit prices (never market)."""

from datetime import date

import pytest

from terminal.broker import PaperBroker, buy_limit, sell_limit
from terminal.fyers import (Fyers, auth_code_from, chain_strikes, load_master, nearest_contracts, save_token,
                            saved_token)
from tests.fakes import master


class Model:
    def quotes(self, data):
        syms = data["symbols"].split(",")
        return {"s": "ok", "d": [{"n": s, "v": {"lp": 100.0 + i, "bid": 99.5 + i, "ask": 100.5 + i}}
                                 for i, s in enumerate(syms)]}

    def funds(self):
        return {"s": "ok", "fund_limit": [{"id": 1, "title": "Total Balance", "equityAmount": 90000},
                                          {"id": 10, "title": "Available Balance", "equityAmount": 50000.5}]}

    def history(self, data):
        return {"s": "ok", "candles": [[1800000000, 1, 2, 0.5, 1.5, 7]]}


def test_quotes_in_batches_of_50_funds_and_history():
    f = Fyers("X-100", "t", model=Model())
    q = f.quotes([f"S{i}" for i in range(120)])
    assert len(q) == 120 and q["S0"] == {"ltp": 100.0, "bid": 99.5, "ask": 100.5}
    assert f.available_funds() == 50000.5
    assert f.minutes("NSE:NIFTY50-INDEX", date(2026, 10, 28), date(2026, 10, 28))[0].volume == 7


def test_auth_code_from_the_pasted_address():
    url = "http://127.0.0.1:8000/?s=ok&code=200&auth_code=eyJabc.def.ghi1234567890&state=kunal_fyers_terminal"
    assert auth_code_from(url) == "eyJabc.def.ghi1234567890"
    assert auth_code_from("eyJabc.def.ghi1234567890") == "eyJabc.def.ghi1234567890"
    with pytest.raises(ValueError):
        auth_code_from("http://127.0.0.1:8000/?s=error")


def test_token_is_kept_for_today_only(tmp_path):
    save_token("abc", tmp_path)
    assert saved_token(tmp_path) == "abc"
    (tmp_path / "token.json").write_text('{"date": "2020-01-01", "token": "old"}')
    assert saved_token(tmp_path) is None


def test_nearest_expiry_lot_and_chain_widths():
    m = master()
    m["NSE:NIFTY26N1125000CE"] = {**m["NSE:NIFTY26N0425000CE"], "expiryDate": 1794000000,
                                  "symTicker": "NSE:NIFTY26N1125000CE"}
    c = nearest_contracts(m, "NIFTY", date(2026, 10, 28))
    assert c.lot_size == 65 and c.step == 50 and c.future == "NSE:NIFTY26NOVFUT"
    assert c.calls[25000] == "NSE:NIFTY26N0425000CE"
    strikes = chain_strikes(c, 25012.0, 5)
    assert len(strikes) == 11 and strikes[5] == 25000              # 5 ITM, ATM, 5 OTM
    assert len(chain_strikes(c, 25012.0, 8)) == 17                 # SENSEX width 8


def test_contract_list_is_downloaded_once_a_day(tmp_path):
    calls = []
    fetch = lambda url: calls.append(url) or {"A": {}}
    load_master("NSE_FO", date(2026, 10, 28), tmp_path, fetch)
    load_master("NSE_FO", date(2026, 10, 28), tmp_path, fetch)
    assert len(calls) == 1 and "NSE_FO_sym_master.json" in calls[0]


def test_limit_prices_buffer_and_tick():
    assert buy_limit(100, 2) == 102.0 and buy_limit(100.03, 2) == 102.05
    assert sell_limit(100, 2) == 98.0 and sell_limit(1.0, 2) == 0.05


def test_paper_fills_never_worse_than_the_limit():
    b = PaperBroker(2, 2)
    assert b.buy("X", 65, {"ltp": 100, "bid": 99.5, "ask": 100.5}, 65).price == 100.5
    assert b.buy("X", 65, {"ltp": 100, "bid": 99, "ask": 104}, 65).price == 100      # ask above 102: at ltp
    assert b.sell("X", 65, {"ltp": 100, "bid": 99.5, "ask": 100.5}, 65).price == 99.5


def test_no_market_order_anywhere():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    for path in list((root / "terminal").glob("*.py")) + list((root / "live_trading").glob("*.py")):
        text = path.read_text(encoding="utf-8")
        assert '"type": 2' not in text and "'type': 2" not in text, path    # FYERS type 2 = market
