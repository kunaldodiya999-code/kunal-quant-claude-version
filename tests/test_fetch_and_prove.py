"""Clean data chain (owner 26 Oct 2026: "3 months of clean data, not 1 year of broken data"):
day quality rules for stocks, split / bonus days, tradable days, scripts/fetch_data.py (3 months, up to the last
finished day, broken days asked again), scripts/data_audit.py and scripts/prove_strategies.py."""

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from market_data.day_quality import INDEX_RULES, STOCK_RULES, assess_series
from market_data.resampling import Candle
from tests.test_open_high_low import master_for

IST = ZoneInfo("Asia/Kolkata")
TODAY = date(2026, 10, 26)


def weekdays(days_back, end=TODAY):
    return sum((end - timedelta(days=k)).weekday() < 5 for k in range(days_back + 1))


def session(day, base=100.0, skip=(), scale=1.0):
    t = int(datetime.combine(day, time(9, 15), tzinfo=IST).timestamp())
    out = []
    for i in range(375):
        if i in skip:
            continue
        p = base * scale * (1 + 0.0004 * (i % 7 - 3))
        out.append(Candle(t + 60 * i, p, p * 1.0005, p * 0.9995, p, 1000))
    return out


class FakeFyers:
    """Weekday 1-minute candles 09:15-15:29 for any symbol; ``holes`` = {(symbol, day): minutes missing the FIRST
    time that day is asked for} (FYERS sometimes sends a day with holes)."""

    def __init__(self, holes=None):
        self.requests = []
        self.holes = dict(holes or {})

    def history(self, symbol, *, resolution, range_from, range_to, cont_flag="0"):
        self.requests.append((symbol, resolution, range_from, range_to))
        day, end, rows = date.fromisoformat(range_from), date.fromisoformat(range_to), []
        base = 25000.0 if "INDEX" in symbol else 100.0
        while day <= end:
            if day.weekday() < 5:
                skip = self.holes.pop((symbol, day), ())
                rows += [[c.timestamp, c.open, c.high, c.low, c.close, 1000] for c in session(day, base, skip)]
            day += timedelta(days=1)
        return {"s": "ok", "candles": rows}


def test_stock_rules_allow_quiet_minutes_but_not_in_the_opening_or_a_split():
    d1, d2, d3, d4 = date(2026, 10, 19), date(2026, 10, 20), date(2026, 10, 21), date(2026, 10, 22)
    quiet = session(d1, skip=(100, 200))                    # two quiet minutes mid-day
    late_open = session(d2, skip=(3,))                      # 09:18 missing: the open matters
    after_close = session(d3, skip=range(361, 375))         # nothing after 15:15 (Yahoo): strategies are out by 15:10
    reports, _ = assess_series(quiet + late_open + after_close, rules=STOCK_RULES, fix_closing_artifact=False)
    assert [r.clean for r in reports] == [True, False, True]
    assert "first minutes" in reports[1].reason
    strict, _ = assess_series(quiet, rules=INDEX_RULES)      # indexes stay strict
    assert not strict[0].clean
    # a 1:1 bonus: the price halves overnight -> that day and the next 3 are not clean
    days = [d1, d2, d3, d4, date(2026, 10, 23), date(2026, 10, 26)]
    candles = [c for k, d in enumerate(days) for c in session(d, scale=0.5 if k >= 2 else 1.0)]
    reports, _ = assess_series(candles, rules=STOCK_RULES, fix_closing_artifact=False)
    assert [r.clean for r in reports] == [True, True, False, False, False, False]
    assert "split/bonus x0.50" in reports[2].reason


def test_tradable_days_need_a_clean_day_and_the_previous_trading_day():
    from market_data.clean_days import tradable_days
    days = [date(2026, 10, 19), date(2026, 10, 20), date(2026, 10, 21), date(2026, 10, 22), date(2026, 10, 23)]
    candles = [c for d in days if d != date(2026, 10, 21) for c in session(d, skip=(5,) if d == days[3] else ())]
    ok, counts = tradable_days(candles, days)
    # 19th: no earlier day; 21st: missing; 22nd: not clean; 23rd: the 22nd is there (its close gives the gap)
    assert ok == {date(2026, 10, 20), date(2026, 10, 23)}
    assert counts == {"days": 4, "clean": 3, "tradable": 2}


def test_last_finished_day():
    from scripts.fetch_data import last_finished_day
    assert last_finished_day(datetime(2026, 10, 26, 12, 0, tzinfo=IST)) == date(2026, 10, 23)     # Monday noon
    assert last_finished_day(datetime(2026, 10, 26, 15, 40, tzinfo=IST)) == date(2026, 10, 26)
    assert last_finished_day(datetime(2026, 10, 25, 10, 0, tzinfo=IST)) == date(2026, 10, 23)     # Sunday


def shared(tmp_path):
    from market_data.kq_store import KQStore
    return KQStore(tmp_path / "kunal_quant.db")


def test_fetch_three_months_into_the_shared_database_and_asks_broken_days_again(tmp_path):
    from scripts.fetch_data import main
    broken_day = date(2026, 10, 14)
    fake = FakeFyers(holes={("NSE:AAA-EQ", broken_day): range(100, 120), ("NSE:NIFTY50-INDEX", broken_day): (50,)})
    master = master_for([("AAA", 1, 500), ("BBB", 2, 250)])
    db = tmp_path / "kunal_quant.db"
    args = ["--data-folder", str(tmp_path), "--kq-db", str(db), "--days", "20", "--pause", "0"]
    main(args, client=fake, master=master, today=TODAY)
    store = shared(tmp_path)
    n = weekdays(20)
    assert len(store.load("NIFTY")) == 375 * n                          # the hole was filled by asking again
    assert len(store.load("STK_AAA")) == 375 * n
    assert ("NSE:AAA-EQ", "1", broken_day.isoformat(), broken_day.isoformat()) in fake.requests
    assert store.stocks() == ["AAA", "BBB"]
    import sqlite3
    with sqlite3.connect(db) as con:                                      # KunalQuant's own format
        assert con.execute("SELECT DISTINCT resolution, source FROM candles").fetchall() == [("1", "FYERS_HISTORY")]
        assert ("FYERS", "NSE:AAA-EQ", "EQUITY") in con.execute(
            "SELECT broker, symbol, instrument_type FROM instruments").fetchall()
    # the next evening: only the last saved day and the new one
    fake.requests.clear()
    main(args, client=fake, master=master, today=TODAY + timedelta(days=1))
    assert {(r[2], r[3]) for r in fake.requests} == {(TODAY.isoformat(), (TODAY + timedelta(days=1)).isoformat())}


def test_shared_database_is_backed_up_once_and_rows_are_never_changed(tmp_path):
    from database.schema import initialize_database
    from market_data.kq_store import KQStore
    db = tmp_path / "kunal_quant.db"
    initialize_database(db)
    old = session(date(2026, 10, 23), base=25000.0)
    KQStore(db, backup=False).add_candles("NSE:NIFTY50-INDEX", old)        # "the owner's 5-year data"
    store = KQStore(db)
    changed = [Candle(c.timestamp, c.open + 1, c.high + 1, c.low + 1, c.close + 1, 5) for c in old]
    assert store.add_candles("NSE:NIFTY50-INDEX", changed) == 0           # same minutes: nothing changed
    assert store.load("NIFTY")[0].close == old[0].close
    backups = list((tmp_path / "backups").glob("kunal_quant_before_kunal_quant_claude_*.db"))
    assert len(backups) == 1
    KQStore(db).add_candles("NSE:NIFTY50-INDEX", session(date(2026, 10, 26), base=25000.0))
    assert len(list((tmp_path / "backups").glob("*.db"))) == 1            # one backup is enough
    assert len(KQStore(backups[0]).load("NIFTY")) == 375


def test_earlier_downloads_are_moved_in_and_yahoo_is_not_used(tmp_path):
    import pytest
    from market_data.research_store import ResearchStore
    from research.data_loader import load
    from scripts.fetch_data import move_old_downloads
    research = ResearchStore(tmp_path / "research" / "market_data.db")
    research.save_candles("STK_AAA", "fyers", "1m", session(date(2026, 10, 22)))
    research.save_candles("NIFTY", "yahoo", "1m", session(date(2026, 10, 22), base=25000.0))   # never moved
    store = shared(tmp_path)
    assert move_old_downloads(store, research.path) == 375
    assert len(store.load("STK_AAA")) == 375 and store.load("NIFTY") == []
    with pytest.raises(SystemExit, match="FYERS data only"):
        load("research", "NIFTY")


def test_fyers_source_feeds_the_index_research_with_clean_days_only(tmp_path):
    from research.data_loader import load
    from scripts.fetch_data import main
    fake = FakeFyers(holes={("NSE:NIFTY50-INDEX", date(2026, 10, 20)): (10,)})    # mended by asking again
    db = tmp_path / "kunal_quant.db"
    main(["--data-folder", str(tmp_path), "--kq-db", str(db), "--only", "indexes", "--days", "10", "--pause", "0"],
         client=fake, today=TODAY)
    everything, clean = load("fyers", "NIFTY", kq_db=db)
    assert len(everything) == len(clean) == 375 * weekdays(10)


def test_data_audit_says_what_is_missing(tmp_path, capsys):
    from scripts.data_audit import main as audit
    from scripts.fetch_data import main as fetch
    db = ["--kq-db", str(tmp_path / "kunal_quant.db")]
    audit(["--data-folder", str(tmp_path), *db], today=TODAY)
    out = capsys.readouterr().out
    assert "NOT FOUND" in out and "NIFTY      NEED 0 clean" in out and "NEXT: python scripts\\fetch_data.py" in out
    fetch(["--data-folder", str(tmp_path), *db, "--days", "90", "--pause", "0"], client=FakeFyers(),
          master=master_for([("AAA", 1, 500)]), today=TODAY)
    audit(["--data-folder", str(tmp_path), *db], today=TODAY)
    out = capsys.readouterr().out
    assert "NIFTY      OK" in out and "F&O stocks OK" in out and "prove_strategies.py" in out
    assert (tmp_path / "research" / "data_audit_days.csv").exists()


def test_prove_runs_every_part_and_saves_one_report(tmp_path, monkeypatch):
    from scripts.fetch_data import main as fetch
    from scripts.prove_strategies import main
    master = master_for([("AAA", 1, 500), ("BBB", 2, 250)])
    db = ["--kq-db", str(tmp_path / "kunal_quant.db")]
    fetch(["--data-folder", str(tmp_path), *db, "--days", "15", "--pause", "0"], client=FakeFyers(), master=master,
          today=TODAY)
    main(["--data-folder", str(tmp_path), *db, "--days", "15"])
    report = (tmp_path / "research" / "proof_report.txt").read_text(encoding="utf-8")
    for title in ("Data check", "KTMI Uni Lite signal accuracy", "TSL Lab", "Gap Reversal, 1-minute",
                  "Gap Reversal, 5-minute", "Open High Low, 1-minute", "Open High Low, 5-minute"):
        assert title in report
    assert "PART 7 of 7" in report and "Report saved" in report and "Clean data:" in report
    assert "Traceback" not in report
