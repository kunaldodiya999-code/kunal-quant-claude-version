"""scripts/fetch_data.py (FYERS history, only new days on a re-run) and scripts/prove_strategies.py (one report)."""

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from market_data.research_store import ResearchStore
from tests.test_open_high_low import master_for

IST = ZoneInfo("Asia/Kolkata")
TODAY = date(2026, 10, 26)


def weekdays(days_back, today=TODAY):
    return sum((today - timedelta(days=k)).weekday() < 5 for k in range(days_back + 1))


class FakeFyers:
    """Weekday candles 09:15-15:29 for any symbol (1 or 5 minutes); counts the requests."""

    def __init__(self):
        self.requests = []

    def history(self, symbol, *, resolution, range_from, range_to, cont_flag="0"):
        self.requests.append((symbol, resolution, range_from, range_to))
        step = int(resolution)
        day, end, rows = date.fromisoformat(range_from), date.fromisoformat(range_to), []
        base = 25000.0 if "INDEX" in symbol else 100.0
        while day <= end:
            if day.weekday() < 5:
                t = int(datetime.combine(day, time(9, 15), tzinfo=IST).timestamp())
                for i in range(0, 375, step):
                    p = base * (1 + 0.0004 * ((i // step) % 7 - 3))
                    rows.append([t + 60 * i, p, p * 1.0005, p * 0.9995, p, 1000])
            day += timedelta(days=1)
        return {"s": "ok", "candles": rows}


def test_fetch_downloads_indexes_and_stocks_then_only_new_days(tmp_path):
    from scripts.fetch_data import main
    fake = FakeFyers()
    master = master_for([("AAA", 1, 500), ("BBB", 2, 250)])
    args = ["--data-folder", str(tmp_path), "--index-days", "20", "--stock-days", "10", "--stock-days-5m", "30",
            "--pause", "0"]
    main(args, client=fake, master=master, today=TODAY)
    store = ResearchStore(tmp_path / "research" / "market_data.db")
    nifty = store.load("NIFTY", "fyers", "1m", clean_only=False)
    assert len(nifty) == 375 * weekdays(20)
    assert len(store.clean_days("NIFTY", "fyers")) == weekdays(20)
    assert len(store.load("STK_AAA", "fyers", "1m", clean_only=False)) == 375 * weekdays(10)
    assert len(store.load("STK_BBB", "fyers", "5m", clean_only=False)) == 75 * weekdays(30)
    assert {r[0] for r in fake.requests} >= {"NSE:NIFTY50-INDEX", "BSE:SENSEX-INDEX", "NSE:AAA-EQ", "NSE:BBB-EQ"}
    # the next evening: only the last saved day and the new one are asked for
    fake.requests.clear()
    main(args, client=fake, master=master, today=TODAY + timedelta(days=1))
    assert {(r[2], r[3]) for r in fake.requests} == {(TODAY.isoformat(), (TODAY + timedelta(days=1)).isoformat())}
    assert len(store.load("NIFTY", "fyers", "1m", clean_only=False)) == 375 * (weekdays(20) + 1)


def test_fyers_source_feeds_the_index_research(tmp_path):
    from research.data_loader import load
    from scripts.fetch_data import main
    main(["--data-folder", str(tmp_path), "--only", "indexes", "--index-days", "10", "--pause", "0"],
         client=FakeFyers(), today=TODAY)
    everything, clean = load("fyers", "NIFTY", research_db=tmp_path / "research" / "market_data.db")
    assert len(everything) == len(clean) == 375 * weekdays(10)


def test_prove_runs_every_part_and_saves_one_report(tmp_path, monkeypatch):
    from scripts.fetch_data import main as fetch
    from scripts.prove_strategies import main
    master = master_for([("AAA", 1, 500), ("BBB", 2, 250)])
    fetch(["--data-folder", str(tmp_path), "--index-days", "15", "--stock-days", "10", "--stock-days-5m", "15",
           "--pause", "0"], client=FakeFyers(), master=master, today=TODAY)
    from market_data import stock_universe
    monkeypatch.setattr(stock_universe, "load_fno_stocks",
                        lambda folder, today, fetch=None: stock_universe.fno_stocks(master))
    main(["--data-folder", str(tmp_path)])
    report = (tmp_path / "research" / "proof_report.txt").read_text(encoding="utf-8")
    for title in ("KTMI Uni Lite signal accuracy", "TSL Lab", "Gap Reversal, 1-minute", "Gap Reversal, 5-minute",
                  "Open High Low, 1-minute", "Open High Low, 5-minute"):
        assert title in report
    assert "PART 6 of 6" in report and "Report saved" in report
    assert "Traceback" not in report
