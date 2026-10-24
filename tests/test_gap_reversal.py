"""Gap Reversal: the 10 setups (short and mirrored long), strength %, gap filter, window, entries, trades."""

import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from draw_reversal_setups import SHORT, mirror  # noqa: E402

from strategies.gap_reversal import (  # noqa: E402
    Bar, GapReversalSettings, GapReversalStore, SideSettings, detect, flip, gap_side, scan_bars, simulate, strength,
)

IST = ZoneInfo("Asia/Kolkata")
S = GapReversalSettings()
EXPECTED = {0: ("SHOOTING_STAR", 5), 1: ("DOJI", 5), 2: ("ENGULFING", 5), 3: ("EVENING_STAR", 5),
            4: ("DARK_CLOUD", 5), 5: ("TWEEZER", 5), 6: ("HARAMI", 5), 7: ("FAILED_BREAKOUT", 5),
            8: ("VOLUME_CLIMAX", 5), 9: ("DOUBLE_TOP", 6)}


@pytest.mark.parametrize("n", range(10))
def test_every_setup_on_the_sheet_is_recognised_short_and_long(n):
    name, _rule, _setup, candles = SHORT[n]
    pattern, at = EXPECTED[n]
    short = [Bar(i * 300, *c) for i, c in enumerate(candles)]
    long_up = flip([Bar(i * 300, *c) for i, c in enumerate(mirror(candles))])
    assert pattern in [x.pattern for x in detect(short, at, S)], name
    assert pattern in [x.pattern for x in detect(long_up, at, S)], name


def test_strength_parts_and_weights():
    _n, _r, _s, candles = SHORT[8]                                   # volume climax
    bars = [Bar(i * 300, *c) for i, c in enumerate(candles)]
    setup = next(x for x in detect(bars, 5, S) if x.pattern == "VOLUME_CLIMAX")
    parts = strength(bars, setup, S)
    assert parts["volume_ratio"] > 3 and parts["absorption"] > 90 and parts["confirmed"] is True
    assert parts["strength"] > 80
    no_volume = [Bar(b.timestamp, b.open, b.high, b.low, b.close, 0) for b in bars]
    assert strength(no_volume, setup, S)["absorption"] == 50                       # neutral without volume
    harami_bars = [Bar(i * 300, *c) for i, c in enumerate(SHORT[6][3])]
    harami = next(x for x in detect(harami_bars, 5, S) if x.pattern == "HARAMI")
    full = strength(harami_bars, harami, GapReversalSettings(pattern_weights={"HARAMI": 1.0}))["strength"]
    assert strength(harami_bars, harami, S)["strength"] == pytest.approx(full * 0.8, abs=0.11)


def test_gap_filter_is_a_setting():
    assert gap_side(100, 103.0, S) == ("SHORT", pytest.approx(3.0))
    assert gap_side(100, 97.0, S)[0] == "LONG"
    assert gap_side(100, 102.0, S)[0] is None
    assert gap_side(100, 102.0, GapReversalSettings(gap_pct=2.0))[0] == "SHORT"
    off = GapReversalSettings(short=SideSettings(enabled=False))
    assert gap_side(100, 105.0, off)[0] is None                                     # each side on/off


def ts(h, m):
    return int(datetime(2026, 10, 26, h, m, tzinfo=IST).timestamp())


def hcl_like_day():
    """Gap up 3.5%, runs up, volume climax + doji at the top at 09:40, then falls."""
    five = [(103.5, 104.2, 103.0, 104.0, 900), (104.0, 105.1, 103.8, 105.0, 800), (105.0, 106.2, 104.9, 106.0, 900),
            (106.0, 107.6, 105.9, 107.5, 1000), (107.5, 109.0, 107.4, 108.8, 1100),
            (108.8, 110.0, 108.6, 108.85, 3200), (108.8, 109.0, 106.5, 106.8, 1500), (106.8, 107.0, 105.0, 105.2, 900),
            (105.2, 105.5, 103.0, 103.3, 900), (103.3, 103.6, 101.0, 101.2, 800)]
    bars = [Bar(ts(9, 15) + 300 * i, *row) for i, row in enumerate(five)]
    minutes = []
    for b in bars:            # five 1-minute candles walking open -> high/low -> close
        path = [b.open, b.high, b.low, b.close] if b.close < b.open else [b.open, b.low, b.high, b.close]
        pts = [path[0], path[1], path[2], path[3], b.close]
        for j in range(5):
            a, c = pts[j], pts[min(j + 1, 4)]
            minutes.append(Bar(b.timestamp + 60 * j, a, max(a, c), min(a, c), c, b.volume / 5))
    return bars, minutes


def test_scan_marks_the_reversal_with_its_strength_and_trades_it():
    bars, minutes = hcl_like_day()
    cands = scan_bars("HCLTECH", 100.0, bars, S)
    best = next(c for c in cands if c.qualifies)                  # the FIRST qualifying candidate is traded
    assert (best.side, best.bar_index, best.qualifies) == ("SHORT", 5, True)
    assert any("Evening star" in c.pattern_names and c.bar_index == 6 for c in cands)   # also marked
    assert "Volume climax" in best.pattern_names and best.strength >= 60 and best.gap_pct == 3.5
    trade = simulate(best, bars, minutes, S, rr=2.0)
    assert trade.entry == pytest.approx(108.6) and trade.stop == pytest.approx(110.0)   # day high
    assert trade.result == "TARGET" and trade.r_multiple == pytest.approx(2.0)
    close_mode = GapReversalSettings(short=SideSettings(entry_mode="CLOSE"))
    late = simulate(best, bars, minutes, close_mode, rr=2.0)
    assert late.entry == pytest.approx(106.8) and late.entry_time == ts(9, 50)          # waited for the close


def test_long_side_is_the_mirror():
    bars, minutes = hcl_like_day()
    down = flip(bars)
    down = [Bar(b.timestamp, b.open + 200, b.high + 200, b.low + 200, b.close + 200, b.volume) for b in down]
    mins = [Bar(b.timestamp, b.open + 200, b.high + 200, b.low + 200, b.close + 200, b.volume) for b in flip(minutes)]
    best = next(c for c in scan_bars("STOCK", 103.6, down, S) if c.qualifies)
    assert best.side == "LONG" and best.bar_index == 5 and "Selling climax" in best.pattern_names
    trade = simulate(best, down, mins, S, rr=2.0)
    assert trade.stop == pytest.approx(90.0) and trade.entry == pytest.approx(91.4)     # stop at the day low
    assert trade.result == "TARGET" and trade.points > 0


def test_setups_after_the_window_are_ignored():
    bars, _ = hcl_like_day()
    late = GapReversalSettings(window_5m=5)                       # only candles 0-4 may hold a setup
    assert all(c.bar_index < 5 for c in scan_bars("X", 100.0, bars, late))
    assert GapReversalSettings(timeframe=3).window_bars() == 16


def test_settings_are_saved_per_side(tmp_path):
    store = GapReversalStore(tmp_path)
    store.update(gap_pct=2.0, short={"min_strength": 70, "entry_mode": "CLOSE", "patterns": {"HARAMI": False}})
    again = GapReversalStore(tmp_path).settings
    assert again.gap_pct == 2.0 and again.short.min_strength == 70 and again.short.entry_mode == "CLOSE"
    assert again.short.patterns["HARAMI"] is False and again.long.patterns["HARAMI"] is True
    assert again.enabled is False                                                    # OFF by default
