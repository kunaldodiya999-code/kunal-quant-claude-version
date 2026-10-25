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
        up, down = q("ce", 2, 2.6, 2, 2.5, 1000, 2.495, 2.5), q("pe", 2, 2, 1.5, 1.6, 1000, 1.597, 1.6)
        flat = q("x", 2, 2.2, 1.8, 2, 1000, 1.995, 2.0)
        if side == "LONG":
            ce, pe = (up if i < long_calls else flat), (down if i < long_puts else flat)
        else:
            ce, pe = (down if i < long_calls else flat), (up if i < long_puts else flat)
        rows.append((k, ce, pe))
    return rows


def test_every_match_counts_and_liquidity_is_checked():
    s = OpenHighLowSettings()                     # owner defaults: one of spot / future enough, no minimum, 0.30%
    assert (s.confirm, s.min_option_matches, s.max_atm_spread_pct) == ("EITHER", 0, 2.0)
    spot, fut = q("S", 100, 101, 100, 100.8), q("F", 100.2, 101.2, 100.2, 101, vol=1_000_000)
    c = evaluate("AAA", spot, fut, ladder(9, 8), s, atm_strike=100.0)
    assert (c.side, c.spot_ok, c.fut_ok, c.call_matches, c.put_matches) == ("LONG", True, True, 9, 8)
    assert c.matches == 19 and c.matches_possible == 24 and c.row()["matches"] == "19/24"
    assert c.fut_value_cr == pytest.approx(10.1) and c.passes
    # owner's example: spot open = low, 2 calls and 4 puts agree -> a candidate (no minimum), 7/24
    few = evaluate("REL", spot, q("F", 100, 101, 99, 100.5, vol=1e6), ladder(2, 4), s, atm_strike=100.0)
    assert few.passes and (few.spot_ok, few.fut_ok, few.matches) == (True, False, 7)
    strict = OpenHighLowSettings(confirm="BOTH", min_option_matches=11)
    assert any("disagree" in r for r in evaluate("REL", spot, q("F", 100, 101, 99, 100.5, vol=1e6), ladder(2, 4),
                                                 strict, atm_strike=100.0).reasons)
    assert any("options 6/22 < 11" in r for r in evaluate("REL", spot, fut, ladder(2, 4), strict,
                                                         atm_strike=100.0).reasons)
    thin = evaluate("CCC", spot, q("F", 100, 101, 100, 101, vol=1000), ladder(11, 11), s, atm_strike=100.0)
    assert not thin.passes and any("futures value" in r for r in thin.reasons)
    # owner's example: buyers at 15, sellers at 20 = 28.6% of the middle price -> no real market, rejected
    wide = [(k, q("ce", 2, 2.6, 2, 18, 1000, 15.0, 20.0), pe) for k, _, pe in ladder(11, 11)]
    assert any("ATM spread 28.57% not below 2%" in r for r in evaluate("WWW", spot, fut, wide, s,
                                                                        atm_strike=100.0).reasons)
    nobid = [(k, q("ce", 2, 2.6, 2, 2.5, 1000, 0.0, 2.5), pe) for k, _, pe in ladder(11, 11)]
    assert not evaluate("NNN", spot, fut, nobid, s, atm_strike=100.0).liquidity_ok          # no buyer at all
    tight = OpenHighLowSettings(max_atm_spread_pct=0.30)
    # exactly 0.30% is NOT less than 0.30% (owner: strictly less); 0.25% passes
    exact = [(k, q("ce", 2, 2.6, 2, 20.0, 1000, 19.94, 20.0), q("pe", 2, 2, 1.5, 20.0, 1000, 19.95, 20.0))
             for k, _, _ in ladder(11, 11)]
    assert not evaluate("XXX", spot, fut, exact, tight, atm_strike=100.0).liquidity_ok
    under = [(k, q("ce", 2, 2.6, 2, 20.0, 1000, 19.95, 20.0), q("pe", 2, 2, 1.5, 20.0, 1000, 19.95, 20.0))
             for k, _, _ in ladder(11, 11)]
    assert evaluate("YYY", spot, fut, under, tight, atm_strike=100.0).liquidity_ok
    assert evaluate("ZZZ", spot, fut, [(k, q("ce", 2, 2.6, 2, 99.5, 1000, 99.0, 100.0),
                                        q("pe", 2, 2, 1.5, 99.5, 1000, 99.0, 100.0)) for k, _, _ in ladder(1, 1)],
                    s, atm_strike=100.0).liquidity_ok                                    # 1% < 2%: fine
    assert not evaluate("WWW", spot, fut, wide, OpenHighLowSettings(max_atm_spread_pct=5.0), atm_strike=100.0).passes
    short = evaluate("EEE", q("S", 100, 100, 99, 99.2), q("F", 100, 100, 99, 99.3, vol=1e6),
                     ladder(11, 11, side="SHORT"), s, atm_strike=100.0)
    assert short.side == "SHORT" and short.matches == 24 and short.passes


def test_top_n_by_matches_then_liquidity():
    s = OpenHighLowSettings(top_n=2)
    spot = q("S", 100, 101, 100, 100.8)
    c1 = evaluate("A1", spot, q("F", 100, 101, 100, 101, vol=600_000), ladder(9, 9), s, atm_strike=100.0)
    c2 = evaluate("A2", spot, q("F", 100, 101, 100, 101, vol=6_000_000), ladder(9, 9), s, atm_strike=100.0)
    c3 = evaluate("A3", spot, q("F", 100, 101, 100, 101, vol=600_000), ladder(11, 10), s, atm_strike=100.0)
    # A4: same options as A3 but the future does not agree -> one match less than A3
    c4 = evaluate("A4", spot, q("F", 100, 101, 99, 100.5, vol=6_000_000), ladder(11, 10), s, atm_strike=100.0)
    assert (c3.matches, c4.matches) == (23, 22)
    assert [c.stock for c in select_top([c1, c2, c3, c4], s)] == ["A3", "A4"]


def test_settings_store_and_checks(tmp_path):
    store = OpenHighLowStore(tmp_path)
    assert store.settings.enabled is False and store.settings.top_n == 5 and store.settings.scan_at == "09:20"
    store.update(top_n=3, instrument="OPTION", long={"target_rr": None, "tsl_method": "PSAR_0.04_0.04_0.10"})
    again = OpenHighLowStore(tmp_path).settings
    assert again.top_n == 3 and again.instrument == "OPTION" and again.long.exit_plan().uses_tsl
    assert OpenHighLowSettings(first_candle_minutes=15).scan_at == "09:30"
    for bad in ({"confirm": "MAYBE"}, {"instrument": "CRYPTO"}, {"first_candle_minutes": 7}, {"entry_valid_candles": 0},
                {"min_option_matches": 40}):
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
                v = (*v, 1000, round(v[3] * 0.998, 4), v[3])
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
    assert scan["AAA"]["matches"] == "19/24"
    # BBB: spot open = low (enough on its own) but its options are illiquid (2% spread) -> not traded
    assert scan["BBB"]["spot"] and not scan["BBB"]["future"] and not scan["BBB"]["passes"]
    assert "ATM spread" in scan["BBB"]["why_not"]
    (trade,) = status["trades"]
    # first candle 09:15-09:20: high 100.81; the 09:20 minute crosses it -> entry at 100.81, stop below the open
    assert trade["action"] == "PAPER BUY" and trade["symbol"] == "NSE:AAA-EQ" and trade["trigger"] == 100.81
    assert trade["entry"] == 100.81 and trade["entry_time"] == "09:20"
    assert trade["stop"] == pytest.approx(99.8) and trade["quantity"] == int(50_000 // 100.81)
    assert trade["status"] == "TARGET" and trade["exit"] == pytest.approx(102.83) and trade["pnl"] > 0


def test_switched_off_or_scan_only_never_trades(tmp_path):
    assert run_day(tmp_path / "off", enabled=False)["trades"] == []
    status = run_day(tmp_path / "scan", enabled=True, extra=["--scan-only"])
    assert status["trades"] == [] and status["scan"]


def test_option_instrument_buys_the_atm_call_and_counts_premium(tmp_path):
    status = run_day(tmp_path, instrument="OPTION")
    (trade,) = status["trades"]
    # entered at the 09:20 breakout of the stock: premium of that minute = 2.5 + 0.03 x 5
    assert trade["action"] == "PAPER BUY CE" and trade["symbol"] == "NSE:AAA26OCT101CE" and trade["entry"] == 2.65
    assert trade["quantity"] == 500 and trade["status"] == "TARGET"           # levels on the stock chart
    assert trade["exit"] > 2.65 and trade["pnl"] == pytest.approx((trade["exit"] - 2.65) * 500, abs=0.01)


def minutes_from(prices, start=(9, 15)):
    """1-minute candles from (open, high, low, close) rows starting at 09:15."""
    return [Candle(ts(*start) + 60 * i, *row) for i, row in enumerate(prices)]


def test_breakout_entry_rules():
    from strategies.open_high_low import breakout
    s = OpenHighLowSettings()
    first = [(100, 100.5, 100, 100.4), (100.4, 100.9, 100.3, 100.8), (100.8, 101.0, 100.6, 100.7),
             (100.7, 100.8, 100.5, 100.6), (100.6, 100.7, 100.4, 100.5)]          # 09:15-09:19, high 101.0
    # still inside the first candle: waiting
    assert breakout(minutes_from(first[:3]), "LONG", s)["state"] == "WAITING"
    # the next candle crosses 101.0 at 09:22 -> entry at 101.0, stop 0.2% below the day's low (100)
    up = first + [(100.5, 100.8, 100.4, 100.7), (100.7, 100.9, 100.6, 100.8), (100.9, 101.3, 100.9, 101.2)]
    b = breakout(minutes_from(up), "LONG", s)
    assert b["state"] == "ENTERED" and b["entry"] == 101.0 and b["entry_ts"] == ts(9, 22)
    assert b["stop"] == pytest.approx(100.0 * 0.998)
    # opened above the trigger: entry at that minute's open
    gap = first + [(101.4, 101.6, 101.3, 101.5)]
    assert breakout(minutes_from(gap), "LONG", s)["entry"] == 101.4
    # price goes below the open (100) before the breakout: cancelled
    broke = first + [(100.5, 100.6, 99.8, 99.9), (99.9, 101.5, 99.9, 101.4)]
    assert breakout(minutes_from(broke), "LONG", s)["state"] == "CANCELLED"
    # the next candle (09:20-09:24) never crosses: no entry, even if 09:26 crosses later
    late = first + [(100.5, 100.8, 100.4, 100.7)] * 5 + [(100.7, 101.5, 100.7, 101.4)] * 2
    assert breakout(minutes_from(late), "LONG", s)["state"] == "NO ENTRY"
    from dataclasses import replace
    two = breakout(minutes_from(late), "LONG", replace(s, entry_valid_candles=2))
    assert two["state"] == "ENTERED" and two["entry_ts"] == ts(9, 25)
    # SHORT: the mirror (break below the first candle's low)
    down = [(100, 100, 99.5, 99.6), (99.6, 99.8, 99.2, 99.3), (99.3, 99.6, 99.1, 99.5), (99.5, 99.7, 99.3, 99.4),
            (99.4, 99.6, 99.3, 99.5), (99.5, 99.6, 99.0, 99.1)]
    sb = breakout(minutes_from(down), "SHORT", s)
    assert sb["state"] == "ENTERED" and sb["entry"] == 99.1 and sb["stop"] == pytest.approx(100.0 * 1.002)


def test_no_breakout_means_no_trade_in_the_program(tmp_path, monkeypatch):
    from tests import test_open_high_low as mod
    flat = lambda self, symbol, **kw: {"s": "ok", "candles": [[ts(9, 15) + 60 * i, 100.4, 100.6, 100.4, 100.5, 10]
                                                               for i in range(60)]}   # noqa: E731
    monkeypatch.setattr(mod.FakeClient, "history", flat)
    status = run_day(tmp_path)
    (trade,) = status["trades"]
    assert trade["status"] == "NO ENTRY" and trade["pnl"] == 0 and trade["entry"] == ""


def test_first_candle_vwap_and_bollinger_filters():
    from dataclasses import replace
    from strategies.open_high_low import candle_filters
    s = OpenHighLowSettings()
    assert (s.vwap_filter, s.bb_filter, s.bb_band) == (False, False, "UPPER")        # OFF by default
    # two earlier days flat at 100 (5-min closes 100 +- 0.1), then today: a strong first candle 100 -> 101.5
    prev = []
    for d, day in enumerate((22, 23)):
        t0 = int(datetime(2026, 10, day, 9, 15, tzinfo=IST).timestamp())
        prev += [Candle(t0 + 60 * i, 100, 100.1, 99.9, 100 + (0.1 if i % 2 else -0.1), 1000) for i in range(375)]
    today = [Candle(ts(9, 15) + 60 * i, 100 + 0.3 * i, 100.3 + 0.3 * i, 100 + 0.3 * i, 100.3 + 0.3 * i, 1000 + 500 * i)
             for i in range(5)]
    f = candle_filters(prev + today, "LONG", s)
    assert f["vwap_ok"] and f["bb_ok"] and f["close"] == 101.5 and f["close"] > f["bb_upper"] > f["bb_mid"]
    assert not candle_filters(prev + today, "SHORT", s)["vwap_ok"]
    weak = [Candle(ts(9, 15) + 60 * i, 100, 100.15, 99.95, 100.0 + (0.12 if i == 4 else 0.05), 1000) for i in range(5)]
    w = candle_filters(prev + weak, "LONG", s)
    assert w["bb_ok"] is False and candle_filters(prev + weak, "LONG", replace(s, bb_band="MIDDLE"))["bb_ok"]
    assert candle_filters(today, "LONG", s)["bb_ok"] is None                         # no earlier days: band unknown
    # ON filters refuse the stock; OFF ignores them
    spot, fut = q("S", 100, 101, 100, 100.8), q("F", 100.2, 101.2, 100.2, 101, vol=1_000_000)
    on = replace(s, vwap_filter=True, bb_filter=True)
    bad = {"vwap_ok": False, "bb_ok": None}
    c = evaluate("AAA", spot, fut, ladder(9, 8), on, atm_strike=100.0, filters=bad)
    assert not c.passes and any("not above VWAP" in r for r in c.reasons) and any("Bollinger unknown" in r
                                                                                  for r in c.reasons)
    assert evaluate("AAA", spot, fut, ladder(9, 8), s, atm_strike=100.0, filters=bad).passes
    good = evaluate("AAA", spot, fut, ladder(9, 8), on, atm_strike=100.0, filters={"vwap_ok": True, "bb_ok": True})
    assert good.passes and good.row()["above_vwap"] is True and good.row()["beyond_bb"] is True


def test_program_applies_the_filters_when_switched_on(tmp_path):
    vwap = run_day(tmp_path / "vwap", vwap_filter=True)               # AAA's first candle closes above its VWAP
    assert [t["stock"] for t in vwap["trades"]] == ["AAA"]
    row = next(r for r in vwap["scan"] if r["stock"] == "AAA")
    assert row["above_vwap"] is True
    bb = run_day(tmp_path / "bb", bb_filter=True)                     # the fake has no earlier days: band unknown
    assert bb["trades"] == [] and "Bollinger unknown" in next(r for r in bb["scan"] if r["stock"] == "AAA")["why_not"]


def test_trade_sim_trails_on_another_chart():
    """Owner 25 Oct: the TSL can follow another chart (spot / futures / option); stop and target stay on the trade."""
    from paper_trading.trade_management import session_bars
    from strategies.exit_plan import ExitPlan
    from strategies.trade_sim import manage_trade
    stock = minutes_from([(100 + 0.05 * i, 100.06 + 0.05 * i, 99.99 + 0.05 * i, 100.05 + 0.05 * i)
                          for i in range(120)])                         # a steady climb: its own TSL never hits
    opt = minutes_from([(50 + 0.5 * i, 50.6 + 0.5 * i, 49.9 + 0.5 * i, 50.5 + 0.5 * i) if i < 60 else
                        (80 - 1.5 * (i - 60), 80.1 - 1.5 * (i - 60), 78.4 - 1.5 * (i - 60), 78.5 - 1.5 * (i - 60))
                        for i in range(120)])                           # the premium collapses after 10:15
    plan = ExitPlan(target_rr=None)
    common = dict(entry_ts=ts(9, 20), exit_time="15:10")
    own = manage_trade(side="LONG", entry=100.25, stop=99.0, plan=plan, bars=session_bars(stock, 5),
                       minutes=stock, **common)
    assert own.result == "TIME"
    alone = manage_trade(side="LONG", entry=52.5, stop=52.5 * 1e-6, plan=plan, bars=session_bars(opt, 5),
                         minutes=opt, **common)
    assert alone.result == "TSL"
    out = manage_trade(side="LONG", entry=100.25, stop=99.0, plan=plan, bars=session_bars(stock, 5), minutes=stock,
                       tsl_chart={"label": "option", "side": "LONG", "entry": 52.5, "bars": session_bars(opt, 5),
                                  "minutes": opt}, **common)
    assert out.result == "TSL" and out.exit_time == alone.exit_time and "option chart" in out.detail
    k = next(i for i, m in enumerate(stock) if m.timestamp >= alone.exit_time)
    assert out.exit == pytest.approx(stock[k - 1].close)                # the stock's price at that moment


def test_tsl_chart_setting_fits_the_instrument(tmp_path):
    s = OpenHighLowSettings()
    assert s.tsl_chart == "SPOT" and s.effective_tsl_chart == "SPOT"
    assert OpenHighLowSettings(instrument="FUTURE", tsl_chart="FUTURE").effective_tsl_chart == "FUTURE"
    assert OpenHighLowSettings(instrument="OPTION", tsl_chart="OPTION").effective_tsl_chart == "OPTION"
    assert OpenHighLowSettings(instrument="STOCK", tsl_chart="OPTION").effective_tsl_chart == "SPOT"
    assert OpenHighLowSettings(instrument="FUTURE", tsl_chart="OPTION").effective_tsl_chart == "SPOT"
    with pytest.raises(ValueError):
        OpenHighLowSettings(tsl_chart="INDEX")
    assert OpenHighLowStore(tmp_path).update(tsl_chart="OPTION").tsl_chart == "OPTION"


def test_program_records_the_tsl_chart_of_each_trade(tmp_path):
    (trade,) = run_day(tmp_path / "spot", instrument="OPTION")["trades"]
    assert trade["tsl_chart"] == "SPOT" and trade["tsl_symbol"] == "NSE:AAA-EQ"
    (trade,) = run_day(tmp_path / "opt", instrument="OPTION", tsl_chart="OPTION")["trades"]
    assert trade["tsl_chart"] == "OPTION" and trade["tsl_symbol"] == "NSE:AAA26OCT101CE"
    assert trade["status"] == "TARGET"                                  # the target stays on the stock chart
