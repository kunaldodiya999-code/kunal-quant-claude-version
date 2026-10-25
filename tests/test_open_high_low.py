"""Open High Low confluence: conditions, strikes, scoring, liquidity, top-N, the live program (fake FYERS)."""

import json
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from strategies.open_high_low import (
    OpenHighLowSettings, OpenHighLowStore, Quote, evaluate, open_is_high, open_is_low, option_strikes, select_top,
    side_of,
)

IST = ZoneInfo("Asia/Kolkata")
DAY = date(2026, 10, 26)
EXPIRY = int(datetime(2026, 10, 27, 15, 30, tzinfo=IST).timestamp())


def q(sym, o, h, l, ltp, vol=0.0, bid=0.0, ask=0.0):
    return Quote(sym, o, h, l, ltp, vol, bid, ask)


def test_open_equals_low_or_high_with_tolerance():
    assert open_is_low(q("A", 100, 101, 100, 100.5), 0.05) and not open_is_high(q("A", 100, 101, 100, 100.5), 0.05)
    assert open_is_low(q("A", 100, 101, 99.96, 100.5), 0.05)                 # 0.04% below the open: still equal
    assert not open_is_low(q("A", 100, 101, 99.9, 100.5), 0.05)
    assert side_of(q("A", 100, 100, 99, 99.5), 0.05) == "SHORT"
    assert side_of(q("A", 100, 100, 100, 100), 0.05) is None                 # nothing traded away from the open
    assert side_of(None, 0.05) is None and side_of(q("A", 0, 0, 0, 0), 0.05) is None


def master_for(stocks):
    m = {}
    for stock, step, lot in stocks:
        m[f"NSE:{stock}26OCTFUT"] = {"symTicker": f"NSE:{stock}26OCTFUT", "underSym": stock, "exInstType": 13,
                                     "optType": "XX", "strikePrice": -1, "expiryDate": str(EXPIRY), "minLotSize": lot}
        for k in range(80, 121):
            strike = float(k * step)
            for t in ("CE", "PE"):
                sym = f"NSE:{stock}26OCT{strike:g}{t}"
                m[sym] = {"symTicker": sym, "underSym": stock, "exInstType": 15, "optType": t, "strikePrice": strike,
                          "expiryDate": str(EXPIRY), "minLotSize": lot}
    return m


def test_eleven_strikes_around_the_price_from_the_real_strike_list():
    expiry, rows = option_strikes(master_for([("AAA", 1, 500)]), "AAA", 100.4, DAY)
    assert expiry == date(2026, 10, 27) and [r[0] for r in rows] == [float(k) for k in range(95, 106)]
    assert rows[5] == (100.0, "NSE:AAA26OCT100CE", "NSE:AAA26OCT100PE")
    assert option_strikes(master_for([("AAA", 1, 500)]), "AAA", 100.4, DAY, min_days=5) == (None, [])


def ladder(long_calls, long_puts, side="LONG", n=11, base=95):
    """Options where the first ``long_calls`` calls / ``long_puts`` puts agree with ``side``."""
    rows = []
    for i in range(n):
        k = float(base + i)
        up, down = q("ce", 2, 2.6, 2, 2.5, 1000, 2.48, 2.5), q("pe", 2, 2, 1.5, 1.6, 1000, 1.59, 1.6)
        flat = q("x", 2, 2.2, 1.8, 2, 1000, 1.99, 2.0)
        if side == "LONG":
            ce, pe = (up if i < long_calls else flat), (down if i < long_puts else flat)
        else:
            ce, pe = (down if i < long_calls else flat), (up if i < long_puts else flat)
        rows.append((k, ce, pe))
    return rows


def test_score_counts_calls_and_puts_and_checks_liquidity():
    s = OpenHighLowSettings()
    spot, fut = q("S", 100, 101, 100, 100.8), q("F", 100.2, 101.2, 100.2, 101, vol=1_000_000)
    c = evaluate("AAA", spot, fut, ladder(9, 8), s, atm_strike=100.0)
    assert (c.side, c.spot_ok, c.fut_ok, c.call_matches, c.put_matches) == ("LONG", True, True, 9, 8)
    assert c.option_score == pytest.approx(77.3, abs=0.1) and c.fut_value_cr == pytest.approx(10.1) and c.passes
    weak = evaluate("BBB", spot, fut, ladder(3, 2), s, atm_strike=100.0)
    assert not weak.passes and any("options 5/22 < 11" in r for r in weak.reasons)
    thin = evaluate("CCC", spot, q("F", 100, 101, 100, 101, vol=1000), ladder(11, 11), s, atm_strike=100.0)
    assert not thin.passes and any("futures value" in r for r in thin.reasons)
    disagree = evaluate("DDD", spot, q("F", 100, 101, 99, 100.5, vol=1e6), ladder(11, 11), s, atm_strike=100.0)
    assert any("disagree" in r for r in disagree.reasons)
    either = OpenHighLowSettings(confirm="EITHER")
    assert evaluate("DDD", spot, q("F", 100, 101, 99, 100.5, vol=1e6), ladder(11, 11), either, atm_strike=100.0).passes
    short = evaluate("EEE", q("S", 100, 100, 99, 99.2), q("F", 100, 100, 99, 99.3, vol=1e6),
                     ladder(11, 11, side="SHORT"), s, atm_strike=100.0)
    assert short.side == "SHORT" and short.call_matches == 11 and short.put_matches == 11 and short.passes


def test_top_n_by_option_score_then_liquidity():
    s = OpenHighLowSettings(top_n=2)
    spot = q("S", 100, 101, 100, 100.8)
    c1 = evaluate("A1", spot, q("F", 100, 101, 100, 101, vol=600_000), ladder(9, 9), s, atm_strike=100.0)
    c2 = evaluate("A2", spot, q("F", 100, 101, 100, 101, vol=6_000_000), ladder(9, 9), s, atm_strike=100.0)
    c3 = evaluate("A3", spot, q("F", 100, 101, 100, 101, vol=600_000), ladder(11, 10), s, atm_strike=100.0)
    assert [c.stock for c in select_top([c1, c2, c3], s)] == ["A3", "A2"]


def test_settings_store_and_checks(tmp_path):
    store = OpenHighLowStore(tmp_path)
    assert store.settings.enabled is False and store.settings.top_n == 5 and store.settings.scan_at == "09:20"
    store.update(top_n=3, instrument="OPTION", long={"target_rr": None, "tsl_method": "PSAR_0.04_0.04_0.10"})
    again = OpenHighLowStore(tmp_path).settings
    assert again.top_n == 3 and again.instrument == "OPTION" and again.long.exit_plan().uses_tsl
    for bad in ({"confirm": "MAYBE"}, {"instrument": "CRYPTO"}, {"scan_at": "09:10"}, {"min_option_matches": 40}):
        with pytest.raises(ValueError):
            OpenHighLowSettings(**bad)


# ---------------------------------------------------------------- the live program with a fake FYERS

class Candle:
    def __init__(self, ts, o, h, l, c, v=1000):
        self.timestamp, self.open, self.high, self.low, self.close, self.volume = ts, o, h, l, c, v


def ts(h, m):
    return int(datetime(2026, 10, 26, h, m, tzinfo=IST).timestamp())


class FakeClient:
    """AAA: open = low on spot and futures, 9 calls + 8 puts agree, liquid -> traded, runs to the target.
    BBB: open = low on spot only (futures dipped below the open) -> fails 'BOTH'. CCC: nothing."""

    def __init__(self, clock):
        self.clock = clock

    def quotes(self, symbols):
        out = []
        for s in symbols:
            if s == "NSE:AAA-EQ":
                v = (100, 101, 100, 100.8, 1e6, 100.75, 100.8)
            elif s == "NSE:AAA26OCTFUT":
                v = (100.2, 101.2, 100.2, 101.0, 1_000_000, 100.95, 101.0)
            elif s == "NSE:BBB-EQ":
                v = (200, 202, 200, 201, 1e6, 200.9, 201)
            elif s == "NSE:BBB26OCTFUT":
                v = (200, 202, 199, 201, 1e6, 200.9, 201)
            elif s.startswith("NSE:CCC"):
                v = (300, 301, 299, 300, 1e6, 299.9, 300)
            elif "AAA26OCT" in s:
                k = int(s.split("26OCT")[1][:-2])
                agree = (k - 96) < (9 if s.endswith("CE") else 8)
                v = ((2, 2.6, 2, 2.5) if s.endswith("CE") else (2, 2, 1.5, 1.6)) if agree else (2, 2.2, 1.8, 2.0)
                v = (*v, 1000, v[3] - 0.01, v[3])
            else:
                v = (5, 5.5, 4.5, 5, 10, 4.9, 5)
            out.append({"n": s, "v": dict(zip(("open_price", "high_price", "low_price", "lp", "volume", "bid", "ask"), v))})
        return {"s": "ok", "d": out}

    def history(self, symbol, *, resolution, range_from, range_to):
        if symbol == "NSE:AAA26OCT101CE":              # the ATM call: premium 2.5 -> +0.03 a minute
            return {"s": "ok", "candles": [[ts(9, 15) + 60 * i, 2.5 + 0.03 * i, 2.5 + 0.03 * i, 2.5 + 0.03 * i,
                                            2.5 + 0.03 * i, 10] for i in range(80)]}
        if symbol != "NSE:AAA-EQ":
            return {"s": "ok", "candles": []}
        rows, price = [], 100.0
        for i in range(0, 80):                         # 09:15 -> 10:35, open = low, then a steady climb
            t = ts(9, 15) + 60 * i
            o = price
            price = 100.8 if i == 4 else price + (0.06 if i > 4 else 0.15)
            rows.append([t, o, max(o, price) + 0.01, min(o, price), price, 1000])
        rows[0][3] = 100.0
        return {"s": "ok", "candles": rows}


def run_day(tmp_path, enabled=True, extra=(), **settings):
    from scripts.run_open_high_low import main
    OpenHighLowStore(tmp_path / "open_high_low").update(enabled=enabled, **settings)
    t = {"now": datetime(2026, 10, 26, 9, 18, 0, tzinfo=IST)}

    def sleep(sec):
        t["now"] += timedelta(seconds=60)

    master = master_for([("AAA", 1, 500), ("BBB", 2, 250), ("CCC", 3, 100)])
    main(["--data-folder", str(tmp_path), "--stop-at", "10:40", *extra], client=FakeClient(lambda: t["now"]),
         clock=lambda: t["now"], sleep=sleep, master=master)
    return json.loads((tmp_path / "open_high_low" / "status.json").read_text())


def test_program_scans_at_0920_and_paper_trades_the_top_candidate(tmp_path):
    status = run_day(tmp_path)
    assert status["scanned_at"] == "09:20"
    scan = {r["stock"]: r for r in status["scan"]}
    assert set(scan) == {"AAA", "BBB"}                                 # CCC: no open = high / low
    assert scan["AAA"]["selected"] and scan["AAA"]["calls"] == 9 and scan["AAA"]["puts"] == 8
    assert not scan["BBB"]["passes"] and "disagree" in scan["BBB"]["why_not"]
    (trade,) = status["trades"]
    assert trade["action"] == "PAPER BUY" and trade["symbol"] == "NSE:AAA-EQ" and trade["entry"] == 100.8
    assert trade["stop"] == pytest.approx(99.8) and trade["quantity"] == int(50_000 // 100.8)
    assert trade["status"] == "TARGET" and trade["exit"] == pytest.approx(102.8) and trade["pnl"] > 0


def test_switched_off_or_scan_only_never_trades(tmp_path):
    assert run_day(tmp_path / "off", enabled=False)["trades"] == []
    status = run_day(tmp_path / "scan", enabled=True, extra=["--scan-only"])
    assert status["trades"] == [] and status["scan"]


def test_option_instrument_buys_the_atm_call_and_counts_premium(tmp_path):
    status = run_day(tmp_path, instrument="OPTION")
    (trade,) = status["trades"]
    assert trade["action"] == "PAPER BUY CE" and trade["symbol"] == "NSE:AAA26OCT101CE" and trade["entry"] == 2.5
    assert trade["quantity"] == 500 and trade["status"] == "TARGET"           # levels on the stock chart
    assert trade["exit"] > 2.5 and trade["pnl"] == pytest.approx((trade["exit"] - 2.5) * 500, abs=0.01)
