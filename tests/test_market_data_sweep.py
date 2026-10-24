"""Data sweep: day quality rules, research store, Yahoo/FYERS sweep and cross-verification."""

import csv
import json
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from market_data.day_quality import assess_series, longest_clean_stretch
from market_data.research_store import ResearchStore
from market_data.resampling import Candle
from market_data.sources.fyers_history import nearest_future, option_ladder_symbols
from market_data.sources.yahoo import parse_chart
from scripts.sweep_market_data import main as sweep

IST = ZoneInfo("Asia/Kolkata")


def day_bars(day, start_price=22000.0, *, drop=(), dead_tail_from=None):
    """375 one-minute candles with small real moves; optional holes and a frozen tail."""
    start = int(datetime(2026, 10, day, 9, 15, tzinfo=IST).timestamp())
    out, price = [], start_price
    for i in range(375):
        ts = start + 60 * i
        hhmm = datetime.fromtimestamp(ts, IST).strftime("%H:%M")
        if hhmm in drop:
            continue
        if dead_tail_from and hhmm >= dead_tail_from:
            out.append(Candle(ts, price, price, price, price, 0))
            continue
        step = 3.0 if i % 2 else -2.0
        out.append(Candle(ts, price, max(price, price + step) + 1, min(price, price + step) - 1, price + step, 0))
        price += step
    return out


def test_clean_day_and_hole_day():
    reports, clean = assess_series(day_bars(20) + day_bars(21, drop=("11:45", "11:46")))
    assert [r.clean for r in reports] == [True, False]
    assert "2 missing (11:45, 11:46)" in reports[1].reason
    assert len(clean) == 375                               # only the clean day is kept


def test_dead_tail_is_cut_and_day_stays_clean_if_after_1510():
    reports, clean = assess_series(day_bars(20, dead_tail_from="15:15"))
    assert reports[0].clean and reports[0].cut_after == "15:14"
    assert datetime.fromtimestamp(clean[-1].timestamp, IST).strftime("%H:%M") == "15:14"


def test_feed_dying_before_1510_makes_the_day_unusable():
    reports, _ = assess_series(day_bars(20, dead_tail_from="14:00"))
    assert not reports[0].clean and "feed stopped at 13:59" in reports[0].reason


def test_frozen_middle_spike_duplicate_and_bad_ohlc_are_caught():
    bars = day_bars(20)
    frozen = [Candle(c.timestamp, 22000, 22000, 22000, 22000, 0) if 100 <= i < 112 else c for i, c in enumerate(bars)]
    assert "frozen runs" in assess_series(frozen)[0][0].reason
    spike = [Candle(c.timestamp, c.open, c.high * 1.05, c.low, c.close * 1.05, 0) if i == 200 else c
             for i, c in enumerate(bars)]
    assert "spikes" in assess_series(spike)[0][0].reason
    assert "duplicates" in assess_series(bars + [bars[10]])[0][0].reason
    bad = [Candle(c.timestamp, c.open, c.low - 5, c.low, c.close, 0) if i == 50 else c for i, c in enumerate(bars)]
    assert "bad ohlc" in assess_series(bad)[0][0].reason


def test_longest_clean_run():
    reports, _ = assess_series(day_bars(19) + day_bars(20) + day_bars(21, drop=("10:00",)) + day_bars(22))
    assert longest_clean_stretch(reports)[2] == 2


def test_store_loads_only_clean_days_up_to_the_cut(tmp_path):
    store = ResearchStore(tmp_path / "r.db")
    candles = day_bars(20, dead_tail_from="15:20") + day_bars(21, drop=("12:00",))
    reports, _ = assess_series(candles)
    store.save_candles("NIFTY", "yahoo", "1m", candles)
    store.save_quality("NIFTY", "yahoo", "1m", reports)
    loaded = store.load("NIFTY", "yahoo", "1m")
    assert {datetime.fromtimestamp(c.timestamp, IST).day for c in loaded} == {20}
    assert datetime.fromtimestamp(loaded[-1].timestamp, IST).strftime("%H:%M") == "15:19"
    assert len(store.load("NIFTY", "yahoo", "1m", clean_only=False)) == len(candles)


def test_yahoo_parse_drops_holes_instead_of_filling():
    payload = {"chart": {"result": [{"timestamp": [1, 2, 3], "indicators": {"quote": [{
        "open": [1, None, 3], "high": [1, None, 3], "low": [1, None, 3], "close": [1, None, 3], "volume": [0, 0, 0]}]}}]}}
    assert [c.timestamp for c in parse_chart(payload)] == [1, 3]
    with pytest.raises(ValueError):
        parse_chart({"chart": {"result": None, "error": {"code": "x"}}})


def yahoo_payload(candles):
    return {"chart": {"result": [{"timestamp": [c.timestamp for c in candles], "indicators": {"quote": [{
        k: [getattr(c, k) for c in candles] for k in ("open", "high", "low", "close")} | {
        "volume": [0] * len(candles)}]}}]}}


class FakeFyers:
    def __init__(self, by_symbol):
        self.by_symbol, self.calls = by_symbol, []

    def history(self, symbol, *, resolution, range_from, range_to, cont_flag="0"):
        self.calls.append((symbol, resolution, cont_flag))
        lo = int(datetime.fromisoformat(range_from).replace(tzinfo=IST).timestamp())
        hi = int(datetime.fromisoformat(range_to).replace(tzinfo=IST).timestamp()) + 86400
        return {"s": "ok", "candles": [[c.timestamp, c.open, c.high, c.low, c.close, 0]
                                       for c in self.by_symbol.get(symbol, []) if lo <= c.timestamp < hi]}


def master():
    exp = str(int(datetime(2026, 10, 27, 15, 30, tzinfo=IST).timestamp()))
    rows = {"NSE:NIFTY26OCTFUT": {"symTicker": "NSE:NIFTY26OCTFUT", "underSym": "NIFTY", "expiryDate": exp}}
    for strike in range(21800, 22201, 50):
        for typ in ("CE", "PE"):
            s = f"NSE:NIFTY26OCT{strike}{typ}"
            rows[s] = {"symTicker": s, "underSym": "NIFTY", "optType": typ, "strikePrice": strike, "expiryDate": exp}
    return rows


def test_futures_and_option_ladder_from_master():
    today = date(2026, 10, 24)
    assert nearest_future(master(), "NIFTY", today) == "NSE:NIFTY26OCTFUT"
    ladder = option_ladder_symbols(master(), "NIFTY", 22010, 50, today, width=1)
    assert ladder == sorted(f"NSE:NIFTY26OCT{k}{t}" for k in (21950, 22000, 22050) for t in ("CE", "PE"))


def test_full_sweep_both_sources_and_cross_verification(tmp_path):
    days = [day_bars(d) for d in (20, 21, 22, 23)]
    nifty = [c for d in days for c in d]
    altered = [Candle(c.timestamp, c.open, c.high + 30, c.low, c.close + 30, 0) if i == 900 else c
               for i, c in enumerate(nifty)]                         # FYERS disagrees on day 3
    fyers = FakeFyers({"NSE:NIFTY50-INDEX": altered, "NSE:NIFTY26OCTFUT": nifty})
    now = datetime(2026, 10, 24, 10, 0, tzinfo=IST)
    rc = sweep(["--source", "both", "--days", "10", "--data-folder", str(tmp_path)],
               client=fyers, masters={"NSE_FO": master(), "BSE_FO": {}},
               yahoo_get=lambda url: yahoo_payload(nifty), now=now)
    assert rc == 0
    store = ResearchStore(tmp_path / "research" / "market_data.db")
    summary = {(s, src, res): (days_, clean, verified) for s, src, res, days_, clean, _, _, verified in store.summary()}
    assert summary[("NIFTY", "yahoo", "1m")] == (4, 4, 3)                # 3 days agree, 1 does not
    assert summary[("NIFTY", "fyers", "1m")][2] == 3
    assert ("NIFTY_FUT", "fyers", "1m") in summary
    assert ("NIFTY", "fyers", "1m") in summary and ("NSE:NIFTY26OCT22000CE", "fyers", "1m") not in summary  # no data
    assert ("NSE:NIFTY26OCTFUT", "1", "1") in fyers.calls                # continuous futures requested
    report = list(csv.DictReader((tmp_path / "research" / "sweep_report.csv").open()))
    nifty_1m = next(r for r in report if (r["series"], r["source"], r["resolution"]) == ("NIFTY", "yahoo", "1m"))
    assert (nifty_1m["clean_days"], nifty_1m["verified_days"]) == ("4", "3")
