"""Research backtests: no look-ahead exits, opening scalp rules, KTMI accuracy, kq-db source."""

import json
import sqlite3
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

import pytest

from database.schema import initialize_database
from market_data.resampling import Candle
from research.ktmi_accuracy import evaluate, find_signals
from research.opening_scalp_backtest import run_days
from research.trade_outcomes import simulate, stats
from strategies.opening_scalp import OpeningScalpConfig, opening_scalp_signal

IST = ZoneInfo("Asia/Kolkata")


def ts(h, m, day=21):
    return int(datetime(2026, 10, day, h, m, tzinfo=IST).timestamp())


def bar(h, m, o, hi, lo, c, day=21):
    return Candle(ts(h, m, day), o, hi, lo, c, 0)


# ------------------------------------------------------------------ exits

PATH = [bar(10, 0, 100, 101, 99, 100), bar(10, 1, 100, 112, 99, 110), bar(10, 2, 110, 141, 109, 140)]


def test_entry_is_the_next_open_and_target_is_reached():
    out = simulate(PATH, decision_ts=ts(10, 0), direction="LONG", target=40, stop=20, exit_by=ts(15, 10))
    assert (out.entry, out.result, out.points) == (100, "TARGET", 40)


def test_candle_touching_both_counts_as_stop():
    path = [bar(10, 0, 100, 145, 75, 120)]
    out = simulate(path, decision_ts=ts(10, 0), direction="LONG", target=40, stop=20, exit_by=ts(15, 10))
    assert (out.result, out.points) == ("STOP", -20)


def test_gap_through_stop_fills_at_the_worse_open():
    path = [bar(10, 0, 100, 101, 99, 100), bar(10, 1, 70, 72, 65, 66)]
    out = simulate(path, decision_ts=ts(10, 0), direction="LONG", target=40, stop=20, exit_by=ts(15, 10))
    assert (out.result, out.exit) == ("STOP", 70)


def test_time_exit_and_short_side():
    out = simulate(PATH, decision_ts=ts(10, 0), direction="SHORT", target=40, stop=50, exit_by=ts(10, 2))
    assert (out.result, out.points) == ("TIME", -10)          # closed 10:01 at 110


def test_breakeven_moves_stop_to_cost_only_after_the_candle_closes():
    path = [bar(10, 0, 100, 101, 99, 100), bar(10, 1, 100, 125, 99, 122), bar(10, 2, 122, 123, 95, 96)]
    with_be = simulate(path, decision_ts=ts(10, 0), direction="LONG", target=40, stop=20, exit_by=ts(15, 10),
                       breakeven_after=20)
    without = simulate(path, decision_ts=ts(10, 0), direction="LONG", target=40, stop=20, exit_by=ts(15, 10))
    assert (with_be.result, with_be.points) == ("STOP", 0)
    assert without.result == "TIME"


def test_stats_profit_factor():
    s = stats([40, -20, 40, -20, -20])
    assert (s["trades"], s["win_rate_pct"], s["profit_factor"]) == (5, 40.0, 1.33)


# ------------------------------------------------------------ opening scalp

def opening_day(day=21, *, first_move=0.0, after=()):
    """09:15..09:24 quiet range 100-110 (plus optional drift), then the given candles."""
    bars, price = [], 105.0
    for i in range(10):
        nxt = price + first_move / 10
        bars.append(Candle(ts(9, 15 + i, day), price, max(price, nxt) + 2, min(price, nxt) - 2, nxt, 0))
        price = nxt
    minute = 25
    for o, h, l, c in after:
        bars.append(Candle(ts(9, minute, day), o, h, l, c, 0))
        minute += 1
    return bars


def test_orb_needs_a_close_beyond_the_range_plus_buffer():
    cfg = OpeningScalpConfig()
    day = opening_day(after=[(106, 115, 105, 108), (108, 120, 107, 118)])   # first only wicks above
    sig = opening_scalp_signal(day, cfg)
    assert sig.direction == "LONG" and sig.decision_ts == ts(9, 27)          # second candle closed beyond
    assert cfg.min_stop <= sig.stop_points <= cfg.max_stop


def test_orb_down_side_and_no_trade_after_last_entry():
    down = opening_day(after=[(104, 105, 90, 92)])
    assert opening_scalp_signal(down, OpeningScalpConfig()).direction == "SHORT"
    late = opening_day(after=[(105, 106, 104, 105)] * 25 + [(105, 130, 104, 128)])
    assert opening_scalp_signal(late, OpeningScalpConfig()) is None


def test_drive_and_fade_and_range_filter():
    strong_up = opening_day(first_move=80)
    assert opening_scalp_signal(strong_up, OpeningScalpConfig(mode="DRIVE")).direction == "LONG"
    assert opening_scalp_signal(strong_up, OpeningScalpConfig(mode="FADE")).direction == "SHORT"
    assert opening_scalp_signal(strong_up, OpeningScalpConfig(mode="DRIVE", max_range=30)) is None


def test_no_trade_without_the_0915_candle():
    assert opening_scalp_signal(opening_day()[1:], OpeningScalpConfig()) is None


def test_default_is_off_and_scaling():
    cfg = OpeningScalpConfig()
    assert cfg.enabled is False
    big = cfg.scaled(2.0)
    assert (big.target_points, big.max_stop, big.breakeven_after) == (100, 40, 40)
    with pytest.raises(ValueError):
        OpeningScalpConfig(mode="MAGIC")


def test_run_days_full_trade():
    day = opening_day(after=[(106, 118, 105, 117)] + [(117 + i * 10, 128 + i * 10, 116 + i * 10, 127 + i * 10)
                                                      for i in range(8)])
    trades = run_days({date(2026, 10, 21): day}, OpeningScalpConfig(), index="NIFTY")
    assert len(trades) == 1 and trades[0]["result"] == "TARGET" and trades[0]["points"] == 50


# --------------------------------------------------------------- KTMI accuracy

def wave_days(days=(20, 21, 22)):
    import math
    out = []
    for d in days:
        for i in range(375):
            p = 22000 + 60 * math.sin(i / 25) + d
            out.append(Candle(ts(9, 15, d) + 60 * i, p, p + 3, p - 3, p + 1, 0))
    return out


def test_signals_only_on_clean_days_and_inside_the_window():
    minutes = wave_days()
    all_sigs = find_signals(minutes, index="NIFTY", timeframe=3, clean_days=[date(2026, 10, d) for d in (20, 21, 22)])
    some = find_signals(minutes, index="NIFTY", timeframe=3, clean_days=[date(2026, 10, 21)])
    assert all_sigs and some and len(some) < len(all_sigs)
    for s in all_sigs:
        assert time(9, 30) <= datetime.fromtimestamp(s.decision_ts, IST).time() < time(15, 0)
    result = evaluate(all_sigs, minutes, targets=[40], stops=[20])
    assert result["grid"][0]["trades"] == len(result["signals"])
    assert set(result["direction_accuracy_pct"]) == {"5m", "15m", "30m"}


# ------------------------------------------------------------- kq-db source

def make_kq_db(folder):
    """A small copy of the KunalQuant database layout holding three NIFTY days."""
    db = folder / "kunal_quant.db"
    initialize_database(db)
    with sqlite3.connect(db) as con:
        con.execute("INSERT INTO instruments (broker, exchange, segment, symbol, instrument_type) "
                    "VALUES ('FYERS','NSE','INDEX','NSE:NIFTY50-INDEX','INDEX')")
        con.executemany("INSERT INTO candles (instrument_id, timestamp, open, high, low, close, resolution, source) "
                        "VALUES (1,?,?,?,?,?,'1','FYERS')",
                        [(c.timestamp, c.open, c.high, c.low, c.close) for c in wave_days()])
    return db


def run_research_commands(folder):
    from scripts.ktmi_accuracy import main as accuracy
    from scripts.opening_scalp_backtest import main as scalp
    db = make_kq_db(folder)
    common = ["--source", "kq-db", "--kq-db", str(db), "--index", "NIFTY", "--data-folder", str(folder)]
    return accuracy(common), scalp(common)


def test_commands_run_on_the_original_kunalquant_database(tmp_path, capsys):
    assert run_research_commands(tmp_path) == (0, 0)
    out = capsys.readouterr().out
    assert "3 clean days" in out and "OPENING SCALP BACKTEST" in out
    summary = json.loads((tmp_path / "research" / "results" / "opening_scalp_summary.json").read_text())
    assert summary["clean_days"] == {"NIFTY": 3} and summary["default_config"]["enabled"] == "False"
