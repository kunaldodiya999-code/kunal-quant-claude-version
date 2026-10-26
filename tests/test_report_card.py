"""Report card (owner 26 Oct 2026): Rs 10 lakh, Rs 30,000 per trade, every strategy x exit, VIX / trend tags, HTML."""

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest

from market_data.resampling import Candle
from research import report_card as rc
from tests.test_fetch_and_prove import FakeFyers, TODAY
from tests.test_open_high_low import master_for

IST = ZoneInfo("Asia/Kolkata")


def test_option_money_estimate_for_rs_30000():
    gross, charges, qty = rc.option_money("NIFTY", 25000.0, 100.0)      # premium 150 x lot 65 = 9,750 -> 3 lots
    assert qty == 195
    assert gross == pytest.approx((0.5 * 100 - 1.0) * 195)
    assert 40 < charges < 200
    gross, _c, _q = rc.option_money("NIFTY", 25000.0, -10_000.0)        # a bought option cannot lose more than it cost
    assert gross >= -150 * 195


def row(day, entry_ts, exit_ts, net, strategy="S", exit_label="1:2"):
    return {"strategy": strategy, "variant": "v", "exit": exit_label, "market": "Stock (intraday)", "timeframe": "5m",
            "symbol": f"X{entry_ts}", "day": day, "entry_ts": entry_ts, "exit_ts": exit_ts, "net": net, "r": 0.5,
            "charges": 10.0}


def test_portfolio_skips_trades_when_33_are_open_and_tracks_drawdown():
    rows = [row("2026-10-20", 100, 1000, 100.0) for _ in range(35)] + [row("2026-10-21", 2000, 2100, -500.0)]
    p = rc.portfolio(rows)
    assert p["taken"] == 34 and p["skipped"] == 2                         # 33 at once, then one more the next day
    assert p["net"] == 33 * 100 - 500 and p["max_dd"] == 500


def test_stars_need_a_good_profit_factor_and_both_halves():
    good = {"trades": 40, "pf": 1.7, "stable": True}
    assert rc.stars(good, {}) == 5
    assert rc.stars({**good, "stable": False}, {}) == 4
    assert rc.stars({**good, "trades": 12}, {}) == 4
    assert rc.stars({"trades": 40, "pf": 0.8, "stable": False}, {}) == 1


def day_candles(d, o, c, hi, lo):
    t = int(datetime.combine(d, time(9, 15), tzinfo=IST).timestamp())
    return [Candle(t, o, hi, lo, (o + c) / 2), Candle(t + 3600, (o + c) / 2, hi, lo, c)]


def test_regimes_tag_vix_groups_and_trend_days():
    days = [date(2026, 10, 19) + timedelta(days=k) for k in range(4)]
    nifty = day_candles(days[0], 100, 110, 111, 99) + day_candles(days[1], 100, 101, 108, 95) + \
        day_candles(days[2], 100, 92, 101, 90) + day_candles(days[3], 100, 100, 103, 97)
    vix = [c for d, v in zip(days, (12, 14, 16, 18)) for c in day_candles(d, v, v, v, v)]
    reg, th = rc.regimes(nifty, vix)
    assert [reg[d].day_type for d in days] == ["TREND", "RANGE", "TREND", "RANGE"]
    assert [reg[d].vix_regime for d in days] == ["LOW", "NORMAL", "HIGH", "HIGH"]
    assert reg[days[1]].vix_move == "VIX up"
    tagged = rc.tag([{"day": days[2].isoformat(), "entry_time": "11:20"}], reg)[0]
    assert (tagged["hour"], tagged["vix_regime"], tagged["day_type"]) == ("11:00-12:00", "HIGH", "TREND")


def test_report_card_runs_end_to_end_and_writes_the_html(tmp_path):
    from market_data.kq_store import KQStore
    from scripts.fetch_data import main as fetch
    from scripts.report_card import main
    from tests.test_research_backtests import wave_days
    db = tmp_path / "kunal_quant.db"
    fetch(["--data-folder", str(tmp_path), "--kq-db", str(db), "--only", "stocks", "--days", "10", "--pause", "0"],
          client=FakeFyers(), master=master_for([("AAA", 1, 500)]), today=TODAY)
    store = KQStore(db)
    waves = wave_days(days=(19, 20, 21, 22, 23))                         # NIFTY with KTMI arrows, 19-23 Oct
    store.add_candles("NSE:NIFTY50-INDEX", waves)
    store.add_candles("NSE:INDIAVIX-INDEX", [Candle(c.timestamp, 14.0, 14.1, 13.9, 14.0) for c in waves])
    assert main(["--data-folder", str(tmp_path), "--kq-db", str(db), "--days", "10", "--long-days", "10",
                 "--timeframes", "3"]) == 0
    out = tmp_path / "research" / "report_card"
    page = (out / "report_card.html").read_text(encoding="utf-8")
    for name in ("Summary", "Ranking", "Strategies", "TSL methods", "Fixed targets", "Timeframes", "Time of day",
                 "India VIX", "Rs 10 lakh plan", "Honesty check", "1-year NIFTY", "Suggestions", "How to read"):
        assert f">{name}" in page
    assert "KTMI Uni Lite" in page and "Rs 10 lakh capital, Rs 30,000 per trade" in page
    summary = (out / "summary.txt").read_text(encoding="utf-8")
    assert "TOP 20:" in summary and "ANSWERS:" in summary
    assert (out / "trades.csv").exists() and (out / "ranking.csv").exists()
