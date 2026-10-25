"""BETA trailing stops (research only): R-ladder, tightening Chandelier, two-key. Never part of the live engine."""

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from research.tsl_beta import BETA_METHODS, _ladder_lock, r_points, run_beta

IST = ZoneInfo("Asia/Kolkata")
T0 = int(datetime(2026, 10, 26, 9, 15, tzinfo=IST).timestamp())
CUT = int(datetime(2026, 10, 26, 15, 10, tzinfo=IST).timestamp())


class C:
    def __init__(self, i, o, h, l, c):
        self.timestamp, self.open, self.high, self.low, self.close, self.volume = T0 + 60 * i, o, h, l, c, 0


def path(prices):
    out, prev = [], prices[0]
    for i, p in enumerate(prices):
        out.append(C(i, prev, max(prev, p) + 1, min(prev, p) - 1, p))
        prev = p
    return out


def test_r_is_the_live_30pct_premium_stop_as_an_index_move():
    assert r_points(25_000, {"premium_pct": 0.6, "initial_sl_pct": 30.0, "delta": 0.5}) == pytest.approx(90.0)
    assert [_ladder_lock(x) for x in (0.2, 0.99, 1.0, 1.7, 2.0, 3.4)] == [-1, -1, 0, 0, 1, 2]


def run(method, prices, side="LONG", entry_i=30):
    minutes = path(prices)
    return run_beta(method, side=side, entry=minutes[entry_i].open, entry_ts=minutes[entry_i].timestamp,
                    minutes=minutes[entry_i:], bars_window=minutes, timeframe=5, cutoff=CUT)


def test_r_ladder_stops_at_minus_1r_then_locks_profit():
    flat = [25_000.0] * 30
    ts, px, reason = run("BETA_R_LADDER", flat + [25_000 - 3 * k for k in range(1, 60)])
    assert reason == "LADDER" and px == pytest.approx(25_000 - 90)                     # -1R
    up_then_back = flat + [25_000 + 4 * k for k in range(1, 60)] + [25_236 - 6 * k for k in range(1, 60)]
    ts, px, reason = run("BETA_R_LADDER", up_then_back)
    assert reason == "LADDER" and px == pytest.approx(25_000 + 90)                     # reached 2.6R -> locked +1R


def test_two_key_gives_back_at_most_35pct_of_the_peak_profit():
    flat = [25_000.0] * 30
    prices = flat + [25_000 + 5 * k for k in range(1, 40)] + [25_195 - 2 * k for k in range(1, 200)]
    ts, px, reason = run("BETA_TWO_KEY", prices)
    peak = max(p.high for p in path(prices)[30:]) - 25_000
    assert reason in ("PREMIUM_LOCK", "TSL_CLOSE")
    if reason == "PREMIUM_LOCK":
        assert px - 25_000 == pytest.approx(peak * 0.65, abs=1.0)
    assert px > 25_000                                                                 # a winner stays a winner


def test_short_side_is_the_mirror_and_every_method_runs():
    flat = [25_000.0] * 30
    down_then_up = flat + [25_000 - 4 * k for k in range(1, 60)] + [24_764 + 6 * k for k in range(1, 60)]
    ts, px, reason = run("BETA_R_LADDER", down_then_up, side="SHORT")
    assert reason == "LADDER" and px == pytest.approx(25_000 - 90)
    for m in BETA_METHODS:
        assert run(m, flat + [25_000 + (k % 7) for k in range(300)])[2] in ("TIME_15:10", "TSL_CLOSE", "LADDER",
                                                                             "PREMIUM_LOCK")


def test_beta_never_reaches_the_live_engine():
    from paper_trading.tsl_methods import PRESETS
    from strategies.exit_plan import TSL_CHOICES
    assert not any(m in PRESETS or m in TSL_CHOICES for m in BETA_METHODS)
