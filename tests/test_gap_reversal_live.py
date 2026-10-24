"""Gap Reversal live scanner and paper desk with a scripted FYERS day (no network)."""

import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from strategies.gap_reversal import GapReversalStore
from tests.test_gap_reversal import hcl_like_day, ts

IST = ZoneInfo("Asia/Kolkata")
MASTER = {
    "NSE:HCLTECH26OCTFUT": {"symTicker": "NSE:HCLTECH26OCTFUT", "underSym": "HCLTECH", "exInstType": 13, "minLotSize": 350},
    "NSE:SBIN26OCTFUT": {"symTicker": "NSE:SBIN26OCTFUT", "underSym": "SBIN", "exInstType": 13, "minLotSize": 750},
    "NSE:NIFTY26OCTFUT": {"symTicker": "NSE:NIFTY26OCTFUT", "underSym": "NIFTY", "exInstType": 11, "minLotSize": 65},
}


class FakeClient:
    def __init__(self, clock):
        self.clock = clock
        _bars, self.minutes = hcl_like_day()

    def quotes(self, symbols):
        levels = {"NSE:HCLTECH-EQ": (100.0, 103.5), "NSE:SBIN-EQ": (800.0, 801.0)}
        return {"s": "ok", "d": [{"n": s, "v": {"prev_close_price": levels[s][0], "open_price": levels[s][1]}}
                                 for s in symbols if s in levels]}

    def history(self, symbol, *, resolution, range_from, range_to):
        rows = [[m.timestamp, m.open, m.high, m.low, m.close, int(m.volume)] for m in self.minutes]
        return {"s": "ok", "candles": rows}


def run(tmp_path, enabled):
    from scripts.run_gap_reversal import main
    GapReversalStore(tmp_path / "gap_reversal").update(enabled=enabled, include_indexes=False)
    t = {"now": datetime(2026, 10, 26, 9, 16, 5, tzinfo=IST)}
    client = FakeClient(lambda: t["now"])

    def sleep(_s):
        t["now"] += timedelta(minutes=1)

    main(["--data-folder", str(tmp_path), "--stop-at", "10:20", "--every", "60"], client=client,
         clock=lambda: t["now"], sleep=sleep, master=MASTER)
    return json.loads((tmp_path / "gap_reversal" / "status.json").read_text())


def test_scanner_marks_the_gap_reversal_and_paper_trades_it(tmp_path):
    status = run(tmp_path, enabled=True)
    assert [g["symbol"] for g in status["gaps"]] == ["NSE:HCLTECH-EQ"]                 # SBIN gap only 0.1%
    best = next(c for c in status["candidates"] if c["qualifies"])
    assert best["side"] == "SHORT" and best["strength"] >= 60
    (trade,) = status["trades"]
    assert trade["action"] == "PAPER SHORT SELL" and trade["status"] == "TARGET"
    assert trade["stop"] == 110.0 and trade["quantity"] == int(100_000 * 0.2 // trade["entry"])
    assert trade["pnl"] > 0 and (tmp_path / "gap_reversal" / "journal").exists()


def test_switched_off_only_marks_setups(tmp_path):
    status = run(tmp_path, enabled=False)
    assert status["candidates"] and status["trades"] == [] and status["strategy_enabled"] is False
