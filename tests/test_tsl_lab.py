"""TSL Lab (historical comparison of trailing stops on KTMI Uni Lite signals)."""

import csv
from datetime import datetime
from zoneinfo import ZoneInfo

from market_data.resampling import Candle
from research.ktmi_accuracy import Signal
from research.tsl_lab import run, run_signal
from market_data.day_quality import group_by_day
from paper_trading.trade_management import TradeManagementSettings

IST = ZoneInfo("Asia/Kolkata")


def ts(d, h, m):
    return int(datetime(2026, 10, d, h, m, tzinfo=IST).timestamp())


def day(d, path):
    """375 minutes; ``path(i)`` gives the close of minute i."""
    out, prev = [], path(0)
    for i in range(375):
        c = path(i)
        out.append(Candle(ts(d, 9, 15) + 60 * i, prev, max(prev, c) + 1, min(prev, c) - 1, c, None))
        prev = c
    return out


def test_point_trail_on_a_long_signal_keeps_the_trend_and_stops_on_the_pullback():
    # rise 0.5 point a minute from 10:00 for an hour, then fall
    minutes = day(20, lambda i: 22000.0) + day(21, lambda i: 22000 + max(0, min(i - 45, 60)) * 0.5
                                                 - max(0, i - 105) * 1.0)
    sig = Signal("NIFTY", 1, "LONG", ts(21, 9, 59), ts(21, 10, 0))
    by_day = group_by_day(minutes)
    row = run_signal(sig, by_day, sorted(by_day), preset="POINTS_10_15", trigger="CLOSE", timeframe=1,
                     settings=TradeManagementSettings())
    assert row["reason"] == "TSL_CLOSE" and row["points"] > 15 and row["points"] < row["mfe"]
    assert row["direction"] == "LONG" and row["capture_pct"] > 50


def test_every_method_and_trigger_is_reported():
    minutes = day(20, lambda i: 22000 + 30 * __import__("math").sin(i / 20)) + \
        day(21, lambda i: 22000 + 30 * __import__("math").sin(i / 20))
    sigs = [Signal("NIFTY", 3, "LONG", ts(21, 10, 0), ts(21, 10, 3)), Signal("NIFTY", 3, "SHORT", ts(21, 11, 0), ts(21, 11, 3))]
    trades, summary = run(sigs, minutes)
    assert len(trades) == 2 * 6 * 2 and len(summary) == 6 * 2
    assert {r["trigger"] for r in summary} == {"CLOSE", "TOUCH"}
    assert all(r["trades"] == 2 for r in summary)


def test_command_runs_on_the_kunalquant_database(tmp_path, capsys):
    from scripts.tsl_lab import main
    from tests.test_research_backtests import make_kq_db
    db = make_kq_db(tmp_path)
    assert main(["--source", "kq-db", "--kq-db", str(db), "--index", "NIFTY", "--timeframes", "3",
                 "--triggers", "CLOSE", "--data-folder", str(tmp_path)]) == 0
    with (tmp_path / "research" / "results" / "tsl_lab_summary.csv").open(newline="", encoding="utf-8") as h:
        rows = list(csv.DictReader(h))
    assert len(rows) == 6 and "NIFTY 3m" in capsys.readouterr().out


def test_tsl_checker_prints_every_indicator_for_a_day(tmp_path, capsys):
    from scripts.tsl_check import main
    from tests.test_research_backtests import make_kq_db
    db = make_kq_db(tmp_path)
    assert main(["--date", "2026-10-21", "--timeframe", "3", "--database", str(db),
                 "--data-folder", str(tmp_path), "--out", str(tmp_path / "out")]) == 0
    out = capsys.readouterr().out
    assert "TSL CHECK" in out and "PSAR A" in out
    with next((tmp_path / "out").glob("*.csv")).open(newline="", encoding="utf-8") as h:
        rows = list(csv.DictReader(h))
    assert len(rows) == 125 and rows[-1]["chandelier_long_stop"] and rows[-1]["psar_0.02_0.02_0.2"]
