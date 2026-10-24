"""Chart data saved by the trading program: futures volume, daily candles, option-chain OI."""

import json
from datetime import datetime, timedelta

from paper_trading.chart_feeds import (
    FuturesMinuteRecorder, parse_option_chain, read_candles, save_daily_candles, save_option_chain,
)
from tests.test_run_paper_session import EXPIRY_EPOCH, IST, FakeClient, master, run_day

FUT = "NSE:NIFTY26OCTFUT"


def at(h, m, s=0):
    return int(datetime(2026, 10, 26, h, m, s, tzinfo=IST).timestamp())


def tick(ts, price, total):
    return {"symbol": FUT, "ltp": price, "last_traded_time": ts, "vol_traded_today": total, "type": "sf"}


def test_futures_minute_volume_comes_from_the_day_total(tmp_path):
    rec = FuturesMinuteRecorder(tmp_path, FUT)
    for ts, price, total in [(at(10, 0, 1), 100, 1000), (at(10, 0, 30), 102, 1300), (at(10, 0, 59), 101, 1450),
                             (at(10, 1, 5), 103, 1500), (at(10, 1, 50), 99, 1900), (at(10, 2, 1), 98, 1950)]:
        rec.on_message(tick(ts, price, total))
    rec.on_message({"symbol": "OTHER", "ltp": 5, "last_traded_time": at(10, 3)})       # ignored
    candles = read_candles(tmp_path / "futures_minute_candles.csv")
    assert [(c.open, c.high, c.low, c.close, c.volume) for c in candles] == [
        (100, 102, 100, 101, 450),        # first minute: from its first tick
        (103, 103, 99, 99, 450)]          # 1900 - 1450
    rec.seed(candles)                                                                # restart: same minutes
    assert len(read_candles(tmp_path / "futures_minute_candles.csv")) == 2           # never twice


class ChainClient(FakeClient):
    def __init__(self):
        self.model = self
        self.calls = []

    def history(self, symbol, *, resolution, range_from, range_to, **kwargs):
        self.calls.append((symbol, resolution, kwargs.get("cont_flag")))
        if resolution == "D":
            day = int(datetime(2026, 10, 23, 0, 0, tzinfo=IST).timestamp())
            vol = 123456 if symbol == FUT else 0
            return {"s": "ok", "candles": [[day, 22000, 22100, 21900, 22050, vol]]}
        start = int(datetime(2026, 10, 23, 9, 15, tzinfo=IST).timestamp())
        vol = 500 if symbol == FUT else 0
        return {"s": "ok", "candles": [[start + 60 * i, 22000, 22001, 21999, 22000, vol] for i in range(375)]}

    def optionchain(self, data):
        rows = [{"option_type": "", "strike_price": -1, "ltp": 22010.5}]
        for k in (21950, 22000, 22050):
            rows.append({"option_type": "CE", "strike_price": k, "oi": 1000 + k - 21950, "oich": 50})
            rows.append({"option_type": "PE", "strike_price": k, "oi": 2000, "prev_oi": 1500})
        return {"s": "ok", "data": {"optionsChain": rows, "expiryData": [{"date": "27-10-2026"}]}}


def test_option_chain_parsing():
    chain = parse_option_chain(ChainClient().optionchain({}))
    assert chain["spot"] == 22010.5 and chain["expiry"] == "27-10-2026"
    assert chain["rows"][1] == {"strike": 22000, "call_oi": 1050, "put_oi": 2000,
                                "call_oi_change": 50, "put_oi_change": 500}


def test_daily_candles_get_futures_volume(tmp_path):
    client = ChainClient()
    save_daily_candles(client, tmp_path, spot="NSE:NIFTY50-INDEX", future=FUT,
                       today=datetime(2026, 10, 26).date(), pause=0)
    (day,) = read_candles(tmp_path / "daily_candles.csv")
    assert (day.close, day.volume) == (22050, 123456)
    assert (FUT, "D", "1") in client.calls                         # continuous futures for old days


def test_runner_saves_all_chart_data(tmp_path, monkeypatch):
    rows = master()
    rows[FUT] = {"symTicker": FUT, "underSym": "NIFTY", "exInstType": 11, "expiryDate": str(EXPIRY_EPOCH + 2 * 86400),
                 "minLotSize": 65, "tickSize": 0.05, "exchange": 10, "exchangeName": "NSE", "fyToken": FUT}
    monkeypatch.setattr("tests.test_run_paper_session.master", lambda: rows)
    sockets = run_day(tmp_path, monkeypatch, client=ChainClient())
    folder = tmp_path / "paper_trading" / "NIFTY"
    futures = read_candles(folder / "futures_minute_candles.csv")
    assert len(futures) == 375 and futures[0].volume == 500           # warm-up history with volume
    assert read_candles(folder / "daily_candles.csv")[0].volume == 123456
    chain = json.loads((folder / "oi_chain.json").read_text())
    assert len(chain["rows"]) == 3 and chain["symbol"] == "NSE:NIFTY50-INDEX"
    assert FUT in sockets[0].subscribed                                # live futures ticks for volume
