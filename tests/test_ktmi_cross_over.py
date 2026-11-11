"""KTMI Cross over (owner 11 Nov 2026): Uni Lite untouched + Speed-crosses-Signal arrows with an optional filter."""

import math
import re
from pathlib import Path

import pytest

from indicators.ktmi.universal import OHLCData
from indicators.ktmi_uni_lite.crossover import CrossFilter, calculate_cross_over, series_crossover
from indicators.ktmi_uni_lite.signals import calculate_uni_lite

HERE = Path(__file__).resolve().parents[1] / "indicators" / "ktmi_uni_lite"
FINAL = (HERE / "KTMI_Uni_Lite_FINAL.pine").read_text(encoding="utf-8").splitlines()
CROSS = (HERE / "KTMI_Cross_Over.pine").read_text(encoding="utf-8").splitlines()


def bars(n=400):
    out, p = [], 25000.0
    for i in range(n):
        o = p
        p = 25000 + 120 * math.sin(i / 9) + 60 * math.sin(i / 3.7) + i * 0.3
        out.append(OHLCData(o, max(o, p) + 5, min(o, p) - 5, p))
    return out


def test_every_uni_lite_line_is_kept_in_order():
    """Only the name changes; everything else of the locked indicator is inside the new one, in the same order."""
    it = iter(CROSS)
    for line in FINAL:
        if line.startswith("indicator(") or line == "// KTMI UNI LITE":      # the name, renamed on purpose
            continue
        assert any(line == c for c in it), f"missing or moved: {line!r}"
    assert 'indicator("KTMI Cross over"' in "\n".join(CROSS)


def test_pine_has_the_cross_inputs_logic_arrows_and_alerts():
    text = "\n".join(CROSS)
    for needed in ('ta.crossover(longSpeed, longSignal)', 'ta.crossover(shortSpeed, shortSignal)',
                   '"Long Cross Filter (empty = all signals)"', '"Short Cross Filter (empty = all signals)"',
                   'options=["Above", "Below"]', 'na(longCrossFilter) or', 'na(shortCrossFilter) or',
                   'title="Long Cross (BUY CALL)"', 'title="Short Cross (BUY PUT)"'):
        assert needed in text, needed
    assert len(re.findall(r"alertcondition\(", text)) == 8
    assert '"type": 2' not in text


def test_python_twin_matches_the_rule():
    data = bars()
    lite = calculate_uni_lite(data)
    got = calculate_cross_over(data)
    expected_long = [i for i in range(1, len(lite)) if series_crossover(
        lite[i - 1].long_speed, lite[i - 1].long_signal, lite[i].long_speed, lite[i].long_signal)]
    assert [i for i, b in enumerate(got) if b.long_cross] == expected_long and expected_long
    assert any(b.short_cross for b in got)


def test_filter_empty_means_all_and_a_value_keeps_only_that_side():
    data = bars()
    lite = calculate_uni_lite(data)
    every = [i for i, b in enumerate(calculate_cross_over(data)) if b.long_cross]
    above0 = [i for i, b in enumerate(calculate_cross_over(data, long=CrossFilter(value=0.0))) if b.long_cross]
    below0 = [i for i, b in enumerate(calculate_cross_over(data, long=CrossFilter(value=0.0, side="Below")))
              if b.long_cross]
    assert set(above0) | set(below0) <= set(every) and not set(above0) & set(below0)
    assert all(lite[i].long_speed > 0 for i in above0) and all(lite[i].long_speed < 0 for i in below0)
    off = calculate_cross_over(data, long=CrossFilter(enabled=False))
    assert not any(b.long_cross for b in off)
    with pytest.raises(ValueError):
        CrossFilter(side="Middle")
