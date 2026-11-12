"""BB Reversal R:R (owner 11 Nov 2026): bands, setups, stop at the candle high/low, 1:2 target, breakeven at 1:1."""

from pathlib import Path

import pytest

from indicators.bb_reversal.bb_rr import BBSettings, Bar, bands, run, signals

PINE = (Path(__file__).resolve().parents[1] / "indicators" / "bb_reversal" / "BB_Reversal_RR.pine").read_text()


def flat(n=20, price=100.0):
    return [Bar(price, price + 0.5, price - 0.5, price + (0.2 if i % 2 else -0.2)) for i in range(n)]


def test_bands_are_sma_plus_minus_two_population_sd():
    closes = [float(x) for x in range(1, 21)]
    lo, mid, up = bands(closes, 20, 2.0)[-1]
    sd = (sum((x - 10.5) ** 2 for x in closes) / 20) ** 0.5
    assert mid == pytest.approx(10.5) and up == pytest.approx(10.5 + 2 * sd) and lo == pytest.approx(10.5 - 2 * sd)


def test_short_on_open_and_close_above_band_then_breakeven_then_stopped_at_entry():
    bars = flat()
    bars.append(Bar(110, 112, 109.5, 111))           # opens and closes above the upper band -> SHORT at 111
    bars.append(Bar(110.5, 110.8, 109.9, 110))       # 1R = 1 point: low 109.9 <= 110 -> breakeven
    bars.append(Bar(110.5, 111.2, 110.2, 111))       # back up to the entry -> out at breakeven
    t = run(bars)[0]
    assert (t.side, t.entry, t.stop, t.target, t.risk) == ("SHORT", 111, 111, 109, 1)   # stop moved to entry
    assert t.be_bar == 21 and t.why == "BREAKEVEN" and t.r == 0


def test_target_is_one_to_two_and_changeable():
    bars = flat()
    bars.append(Bar(110, 112, 109.5, 111))
    bars.append(Bar(110, 110.2, 108.5, 109))         # reaches 109 = 1:2 target
    t = run(bars)[0]
    assert t.why == "TARGET" and t.r == pytest.approx(2.0)
    t3 = run(bars, BBSettings(rr=3))[0]
    assert t3.target == 108 and t3.why == "" and t3.be_bar == 21


def test_stop_at_the_candle_high_and_gap_fills_worse():
    bars = flat()
    bars.append(Bar(110, 112, 109.5, 111))
    bars.append(Bar(113, 113.5, 112.5, 113))         # gaps above the stop 112 -> out at the open 113
    t = run(bars)[0]
    assert t.why == "STOP" and t.exit == 113 and t.r == pytest.approx(-2.0)


def test_long_mirror_and_setup_choice():
    bars = flat()
    bars.append(Bar(90, 90.5, 88, 89))               # opens and closes below the lower band -> LONG
    t = run(bars)[0]
    assert (t.side, t.entry, t.stop, t.target) == ("LONG", 89, 88, 91)
    only_close = flat() + [Bar(100, 112, 99.5, 111)]  # opens inside, closes outside: setup 2 only
    assert signals(only_close, BBSettings())[-1] == (False, False)
    assert signals(only_close, BBSettings(setups=(2,)))[-1] == (True, False)
    assert signals(only_close, BBSettings(setups=(2,), trade_short=False))[-1] == (False, False)


def test_same_candle_stop_and_target_uses_the_safer_choice_by_default():
    bars = flat()
    bars.append(Bar(110, 112, 109.5, 111))
    bars.append(Bar(111, 112.5, 108.5, 109))         # both 112 and 109 inside one candle
    assert run(bars)[0].why == "STOP"
    assert run(bars, BBSettings(target_first=True))[0].why == "TARGET"


def test_pine_file_has_the_same_rules_and_settings():
    for needed in ('input.int(20, "Length"', 'input.float(2.0, "Multiplier', 'input.float(2.0, "Target R:R',
                   'input.float(1.0, "Breakeven when price reaches (R)"', "set1 and open > upper and close > upper",
                   "set1 and open < lower and close < lower", "stopPx = high + slBuffer", "stopPx = low - slBuffer",
                   "tStop := tEntry", "barstate.isconfirmed", "box.new(", "alertcondition(enterShort"):
        assert needed in PINE, needed


def test_setup_5_whole_candle_outside_the_band():
    whole = flat() + [Bar(110, 112, 109.5, 111)]     # low 109.5 above the upper band: all of it outside
    touch = flat() + [Bar(110, 112, 100.0, 111)]     # opens/closes outside but the low dips inside
    s5 = BBSettings(setups=(5,))
    assert signals(whole, s5)[-1] == (True, False) and signals(touch, s5)[-1] == (False, False)
    assert signals(touch, BBSettings())[-1] == (True, False)        # setup 1 (default) still takes it
    down = flat() + [Bar(90, 90.5, 88, 89)]          # high 90.5 below the lower band
    assert signals(down, s5)[-1] == (False, True)
    assert "set5 and low > upper" in PINE and "set5 and high < lower" in PINE
    assert 'input.bool(false, "5. WHOLE candle outside the band' in PINE
