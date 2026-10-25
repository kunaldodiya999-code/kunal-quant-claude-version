"""Time Machine: replays from the stock's own candles, the shared exit plan, repeatable, shown off the chart."""

import random
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from strategies.exit_plan import ExitPlan
from strategies.time_machine import relative_moves, run_odds, summary

IST = ZoneInfo("Asia/Kolkata")


class C:
    def __init__(self, ts, o, h, l, c):
        self.timestamp, self.open, self.high, self.low, self.close, self.volume = ts, o, h, l, c, 100


def sessions(n=40, drift=0.0, vol=0.002, seed=1, start=date(2026, 8, 3)):
    """n weekday sessions of 75 five-minute candles, a random walk (drift per candle, in %)."""
    rng = random.Random(seed)
    out, price, d = [], 100.0, start
    while len({datetime.fromtimestamp(c.timestamp, IST).date() for c in out}) < n:
        if d.weekday() < 5:
            t0 = int(datetime(d.year, d.month, d.day, 9, 15, tzinfo=IST).timestamp())
            for k in range(75):
                o = price
                c = o * (1 + drift + rng.gauss(0, vol))
                out.append(C(t0 + 300 * k, o, max(o, c) * (1 + vol / 3), min(o, c) * (1 - vol / 3), c))
                price = c
        d += timedelta(days=1)
    return out, d


def at(d, h, m):
    return int(datetime(d.year, d.month, d.day, h, m, tzinfo=IST).timestamp())


def test_moves_are_measured_per_time_of_day():
    hist, _ = sessions(25)
    moves, used = relative_moves(hist)
    assert used == 25 and set(moves) == set(range(75))
    assert len(moves[5]) == 25 and len(moves[0]) == 24          # the first day's opening gap has no previous close


def test_no_edge_history_gives_a_coin_flip_and_the_ladder_falls():
    hist, day = sessions(40)
    common = dict(symbol="X", side="LONG", entry=100.0, stop=99.5, entry_ts=at(day, 10, 0) - 1, history=hist)
    one = run_odds(plan=ExitPlan(1.0, "NONE"), replays=1500, **common)
    assert one.sessions == 40 and 40 <= one.win_pct <= 60 and abs(one.avg_r) < 0.15 and one.verdict == "COIN FLIP"
    s = summary(plan=ExitPlan(2.0, "NONE"), replays=600, **common)
    hits = [s["ladder"][k]["target_pct"] for k in ("1:1.5", "1:2", "1:2.5", "1:3")]
    assert hits == sorted(hits, reverse=True) and hits[0] > hits[-1]          # a bigger target is reached less often
    assert s["text"].startswith("win ") and "target" in s["text"]


def test_rising_history_favours_longs_and_shorts_are_the_mirror():
    up, day = sessions(40, drift=0.0015)
    long = run_odds(symbol="X", side="LONG", entry=100, stop=99.5, plan=ExitPlan(1.0, "NONE"),
                    entry_ts=at(day, 10, 0), history=up, replays=800)
    short = run_odds(symbol="X", side="SHORT", entry=100, stop=100.5, plan=ExitPlan(1.0, "NONE"),
                     entry_ts=at(day, 10, 0), history=up, replays=800)
    assert long.win_pct > 65 > 35 > short.win_pct


def test_same_day_same_numbers_and_tsl_plans_work():
    hist, day = sessions(30)
    kw = dict(symbol="RELIANCE", side="LONG", entry=100, stop=99.4, entry_ts=at(day, 9, 30), history=hist, replays=300)
    a = run_odds(plan=ExitPlan(2.0, "NONE"), **kw)
    b = run_odds(plan=ExitPlan(2.0, "NONE"), **kw)
    assert a == b
    t = run_odds(plan=ExitPlan(None, "PSAR_0.04_0.04_0.10"), **kw)
    assert t.target_pct == 0 and t.tsl_pct + t.stop_pct + t.time_pct == pytest.approx(100, abs=0.2)


def test_refuses_without_enough_history_or_a_wrong_stop():
    hist, day = sessions(10)
    assert run_odds(symbol="X", side="LONG", entry=100, stop=99, plan=ExitPlan(2.0, "NONE"),
                    entry_ts=at(day, 10, 0), history=hist) is None
    hist, day = sessions(25)
    assert run_odds(symbol="X", side="LONG", entry=100, stop=101, plan=ExitPlan(2.0, "NONE"),
                    entry_ts=at(day, 10, 0), history=hist) is None
    assert run_odds(symbol="X", side="LONG", entry=100, stop=99, plan=ExitPlan(2.0, "NONE"),
                    entry_ts=at(day, 15, 20), history=hist) is None             # nothing left before 15:10


def test_desks_show_the_odds_and_never_trade_differently(tmp_path):
    from paper_trading.gap_reversal_paper import GapReversalDesk
    from strategies.gap_reversal import GapReversalSettings
    from tests.test_gap_reversal import hcl_like_day
    bars, minutes = hcl_like_day()
    hist, _ = sessions(30, start=date(2026, 8, 3))
    s = GapReversalSettings(enabled=True)
    with_odds = GapReversalDesk(tmp_path / "a", s, odds_history=lambda sym: hist)
    without = GapReversalDesk(tmp_path / "b", s)
    for desk in (with_odds, without):
        desk.set_gap("NSE:HCLTECH-EQ", 100.0, 103.5)
        desk.on_minutes("NSE:HCLTECH-EQ", minutes, minutes[-1].timestamp + 60)
    a, b = with_odds.write_status(minutes[-1].timestamp + 60), without.write_status(minutes[-1].timestamp + 60)
    (ta,), (tb,) = a["trades"], b["trades"]
    assert ta["time_machine"].startswith("win ") and tb["time_machine"] == ""
    assert {k: v for k, v in ta.items() if k != "time_machine"} == {k: v for k, v in tb.items() if k != "time_machine"}
    assert set(a["time_machine"]["NSE:HCLTECH-EQ"]["ladder"]) == {"1:1.5", "1:2", "1:2.5", "1:3"}
    broken = GapReversalDesk(tmp_path / "c", s, odds_history=lambda sym: 1 / 0)       # a data error never stops it
    broken.set_gap("NSE:HCLTECH-EQ", 100.0, 103.5)
    broken.on_minutes("NSE:HCLTECH-EQ", minutes, minutes[-1].timestamp + 60)
    assert len(broken.write_status(minutes[-1].timestamp + 60)["trades"]) == 1


def test_command_prints_the_chances(capsys):
    from scripts.time_machine import main
    hist, day = sessions(30)
    assert main(["--symbol", "RELIANCE", "--side", "LONG", "--entry", "100", "--stop", "99.5", "--day",
                 day.isoformat(), "--at", "10:00", "--replays", "300"], candles=hist) == 0
    out = capsys.readouterr().out
    assert "TIME MACHINE  RELIANCE LONG" in out and "1:3" in out and "stop first" in out


def test_page_shows_the_box_closed_under_the_trades(tmp_path, monkeypatch):
    from pathlib import Path
    from streamlit.testing.v1 import AppTest
    from paper_trading.gap_reversal_paper import GapReversalDesk
    from strategies.gap_reversal import GapReversalSettings, GapReversalStore
    from tests.test_gap_reversal import hcl_like_day
    bars, minutes = hcl_like_day()
    hist, _ = sessions(30)
    GapReversalStore(tmp_path).update(enabled=True)
    desk = GapReversalDesk(tmp_path, GapReversalSettings(enabled=True), odds_history=lambda sym: hist)
    desk.set_gap("NSE:HCLTECH-EQ", 100.0, 103.5)
    desk.on_minutes("NSE:HCLTECH-EQ", minutes, minutes[-1].timestamp + 60)
    desk.write_status(minutes[-1].timestamp + 60)
    monkeypatch.setenv("KQ_GAP_DIR", str(tmp_path))
    page = Path(__file__).resolve().parents[1] / "dashboard" / "pages" / "8_Gap_Reversal.py"
    at = AppTest.from_file(str(page), default_timeout=60).run()
    assert not at.exception
    box = [e for e in at.expander if e.label.startswith("Time Machine")]
    assert len(box) == 1
    table = box[0].dataframe[0].value
    assert list(table["symbol"]) == ["HCLTECH"] and {"1:1.5 %", "1:3 %", "stop first %"} <= set(table.columns)
