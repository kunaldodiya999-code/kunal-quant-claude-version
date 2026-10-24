"""Signal checker: ktmi_bars.csv from the live engine == scripts/ktmi_check.py."""

import csv
import random
import sqlite3
from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from database.schema import initialize_database
from market_data.resampling import Candle
from paper_trading.session import PaperSessionConfig, build_paper_session
from scripts.ktmi_check import check_day, main

IST = ZoneInfo("Asia/Kolkata")
SYMBOL = "NSE:NIFTY50-INDEX"


def flat_minutes(days, seed=3):
    """One price per minute (open=high=low=close), like one tick per minute."""
    rng = random.Random(seed)
    price, out = 22000.0, []
    for day in days:
        start = int(datetime(2026, 10, day, 9, 15, tzinfo=IST).timestamp())
        for i in range(375):
            price += rng.gauss(0, 6)
            out.append(Candle(start + 60 * i, round(price, 2), round(price, 2), round(price, 2), round(price, 2)))
    return out


def test_live_engine_journal_matches_the_checker(tmp_path):
    minutes = flat_minutes([22, 23])
    day1 = [c for c in minutes if datetime.fromtimestamp(c.timestamp, IST).day == 22]
    day2 = [c for c in minutes if datetime.fromtimestamp(c.timestamp, IST).day == 23]

    session = build_paper_session(
        client=object(),
        config=PaperSessionConfig(lot_size=65, output_dir=tmp_path, pending_journal_path=tmp_path / "p.csv"),
        resolver=object(), socket_factory=lambda **k: None,
    )
    session.pipeline.seed_history(SYMBOL, day1)
    for c in day2 + [Candle(day2[-1].timestamp + 60, 1, 1, 1, 1)]:       # last tick closes 15:29
        session.pipeline.on_message({"symbol": SYMBOL, "ltp": c.close, "last_traded_time": c.timestamp + 1})

    with (tmp_path / "ktmi_bars.csv").open() as handle:
        live = list(csv.DictReader(handle))
    checker = check_day(minutes, date(2026, 10, 23), 3)
    assert len(live) == 125 == len(checker)
    for got, want in zip(live, checker):
        assert got["candle_time"] == want["candle_time"]
        for field in ("long_speed", "long_signal", "short_speed", "short_signal", "long_buy", "short_buy"):
            assert got[field] == str(want[field]), (got["candle_time"], field)
    assert any(r["long_buy"] for r in checker) and any(r["short_buy"] for r in checker)


class FakeClient:
    def __init__(self, minutes):
        self.minutes = minutes

    def history(self, symbol, *, resolution, range_from, range_to):
        lo = int(datetime.fromisoformat(range_from).replace(tzinfo=IST).timestamp())
        hi = int(datetime.fromisoformat(range_to).replace(tzinfo=IST).timestamp()) + 86400
        return {"s": "ok", "candles": [[c.timestamp, c.open, c.high, c.low, c.close, 0]
                                       for c in self.minutes if lo <= c.timestamp < hi]}


def test_command_with_fyers_prints_and_saves(tmp_path, capsys):
    client = FakeClient(flat_minutes([21, 22, 23]))
    assert main(["--date", "2026-10-23", "--timeframe", "5", "--out", str(tmp_path)], client=client) == 0
    out = capsys.readouterr().out
    assert "Fri 23 Oct 2026 - 5-minute candles" in out
    assert "Arrows today:" in out
    rows = list(csv.DictReader((tmp_path / "ktmi_2026-10-23_5m.csv").open()))
    assert len(rows) == 75 and rows[0]["candle_time"] == "2026-10-23 09:15"


def test_command_with_local_database(tmp_path, capsys):
    db = tmp_path / "kq.db"
    initialize_database(db)
    with sqlite3.connect(db) as con:
        con.execute("INSERT INTO instruments (broker, exchange, segment, symbol, instrument_type) "
                    "VALUES ('FYERS','NSE','INDEX',?,'INDEX')", (SYMBOL,))
        con.executemany(
            "INSERT INTO candles (instrument_id, timestamp, open, high, low, close, resolution, source) "
            "VALUES (1,?,?,?,?,?,'1','FYERS')",
            [(c.timestamp, c.open, c.high, c.low, c.close) for c in flat_minutes([22, 23])])
    assert main(["--date", "2026-10-23", "--timeframe", "15", "--database", str(db), "--out", str(tmp_path)]) == 0
    assert "15-minute candles" in capsys.readouterr().out


def test_holiday_gives_a_clear_message(tmp_path):
    with pytest.raises(SystemExit, match="No NIFTY candles"):
        main(["--date", "2026-10-25", "--out", str(tmp_path)], client=FakeClient(flat_minutes([23])))
