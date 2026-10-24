"""Chart indicator maths (dashboard/static/kq_indicators.js) checked against plain Python.

Runs the JavaScript with Node.js; skipped on a PC without Node (the chart itself runs in the browser).
"""

import json
import math
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "dashboard" / "static" / "kq_indicators.js"
NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="Node.js not installed")


def run(call: str, **data):
    script = f"const K = require({json.dumps(str(JS))}); const D = {json.dumps(data)}; " \
             f"process.stdout.write(JSON.stringify({call}));"
    out = subprocess.run([NODE, "-e", script], capture_output=True, text=True, timeout=60, check=True)
    return json.loads(out.stdout)


DAY = 86400


def frame(closes, *, start=10 * DAY + 9 * 3600 + 15 * 60, step=60, vols=None, spread=2.0):
    n = len(closes)
    opens = [closes[0]] + closes[:-1]
    return {"t": [start + i * step for i in range(n)], "o": opens,
            "h": [max(o, c) + spread for o, c in zip(opens, closes)],
            "l": [min(o, c) - spread for o, c in zip(opens, closes)],
            "c": closes, "v": vols or [100 + (i * 37) % 50 for i in range(n)]}


CLOSES = [22000 + 40 * math.sin(i / 7) + i * 0.8 for i in range(120)]


def close_to(a, b, tol=1e-6):
    return a is None and b is None or (a is not None and b is not None and abs(a - b) <= tol * max(1, abs(b)))


def test_vwap_and_its_three_standard_deviation_bands():
    # two sessions: the second one must start again from zero
    f = frame(CLOSES[:60])
    second = frame(CLOSES[60:], start=11 * DAY + 9 * 3600 + 15 * 60)
    f = {k: f[k] + second[k] for k in f}
    got = run("K.vwap(D.f, {band1: true, band2: true, band3: true})", f=f)
    sv = svv = v = 0
    for i in range(len(f["t"])):
        if i == 60:
            sv = svv = v = 0
        src = (f["h"][i] + f["l"][i] + f["c"][i]) / 3
        sv += src * f["v"][i]; svv += src * src * f["v"][i]; v += f["v"][i]
        mid = sv / v
        sd = math.sqrt(max(svv / v - mid * mid, 0))
        assert close_to(got["vwap"][i], mid)
        for b, mult in enumerate((1, 2, 3)):
            assert close_to(got["upper"][b][i], mid + mult * sd) and close_to(got["lower"][b][i], mid - mult * sd)
    assert got["equalWeights"] is False
    off = run("K.vwap(D.f, {})", f=f)                                     # defaults: band 1 only
    assert off["upper"][1][10] is None and off["upper"][0][10] is not None


def test_vwap_without_volume_uses_equal_weights():
    f = frame(CLOSES[:30], vols=[0] * 30)
    got = run("K.vwap(D.f, {})", f=f)
    srcs = [(h + l + c) / 3 for h, l, c in zip(f["h"], f["l"], f["c"])]
    assert got["equalWeights"] is True and close_to(got["vwap"][29], sum(srcs) / 30)


@pytest.mark.parametrize("ma", ["SMA", "EMA"])
def test_bollinger_bands(ma):
    f = frame(CLOSES)
    got = run(f"K.bollinger(D.f, {{length: 20, mult: 2, maType: '{ma}'}})", f=f)
    c = f["c"]
    ema = None
    for i in range(len(c)):
        if i < 19:
            assert got["basis"][i] is None
            continue
        window = c[i - 19:i + 1]
        mean = sum(window) / 20
        sd = math.sqrt(sum((x - mean) ** 2 for x in window) / 20)
        if ma == "SMA":
            basis = mean
        else:
            ema = mean if ema is None else 2 / 21 * c[i] + (1 - 2 / 21) * ema
            basis = ema
        assert close_to(got["basis"][i], basis) and close_to(got["upper"][i], basis + 2 * sd)
        assert close_to(got["lower"][i], basis - 2 * sd)


def test_volume_profile_poc_value_area_high_low():
    f = {"t": [0, 60, 120], "o": [100, 108, 107], "h": [110, 112, 109], "l": [100, 106, 104],
         "c": [108, 107, 105], "v": [100, 50, 30]}
    got = run("K.volumeProfile(D.f, 0, 2, {rowSize: 12, valueArea: 70})", f=f)
    lo, hi, rows = 100, 112, 12
    step = (hi - lo) / rows
    up, down = [0.0] * rows, [0.0] * rows
    for o, h, l, c, v in zip(f["o"], f["h"], f["l"], f["c"], f["v"]):
        for r in range(rows):
            a, b = lo + r * step, lo + (r + 1) * step
            share = max(0.0, min(h, b) - max(l, a)) / (h - l)
            (up if c >= o else down)[r] += v * share
    totals = [u + d for u, d in zip(up, down)]
    poc = max(range(rows), key=lambda r: (totals[r], -r))
    lo_r = hi_r = poc
    total = totals[poc]
    while total < 0.7 * sum(totals):
        above = totals[hi_r + 1] if hi_r < rows - 1 else -1
        below = totals[lo_r - 1] if lo_r > 0 else -1
        if above >= below:
            hi_r += 1; total += above
        else:
            lo_r -= 1; total += below
    assert (got["high"], got["low"], got["rows"]) == (112, 100, 12) and got["byTime"] is False
    assert close_to(got["poc"], lo + (poc + 0.5) * step)
    assert close_to(got["vah"], lo + (hi_r + 1) * step) and close_to(got["val"], lo + lo_r * step)
    assert close_to(got["totalVolume"], 180)
    ticks = run("K.volumeProfile(D.f, 0, 2, {rowsLayout: 'Ticks Per Row', rowSize: 20, tickSize: 0.05})", f=f)
    assert ticks["rows"] == 12                                          # 12 points / (20 x 0.05)
    no_vol = run("K.volumeProfile(D.f, 0, 2, {developingPoc: true})", f=dict(f, v=[0, 0, 0]))
    assert no_vol["byTime"] is True and len(no_vol["developing"]) == 3


def test_smart_money_concepts_finds_breaks_order_blocks_and_gaps():
    # rise, pull back, break the high (bullish BOS), then fall through the low (bearish CHoCH)
    path = ([100 + i * 2 for i in range(10)] + [118 - i * 2 for i in range(6)] + [108 + i * 3 for i in range(10)]
            + [135 - i * 4 for i in range(14)])
    f = frame(path, spread=0.5)
    got = run("K.smc(D.f, {internalLength: 3, swingLength: 5, internalOB: true, fvg: true, fvgAutoThreshold: false})",
              f=f)
    labels = [(e["label"], e["bull"]) for e in sorted(got["structures"], key=lambda e: e["to"])]
    assert ("BOS", True) in labels or ("CHoCH", True) in labels
    first_bull = next(i for i, (_, bull) in enumerate(labels) if bull)
    assert any(label == "CHoCH" and not bull for label, bull in labels[first_bull:])
    assert got["strongWeak"] is not None
    # a clear three-candle gap up that is never filled
    gap = {"t": [0, 60, 120, 180], "o": [100, 101, 112, 116], "h": [102, 113, 117, 120],
           "l": [99, 100, 110, 114], "c": [101, 112, 116, 119], "v": [1, 1, 1, 1]}
    fvg = run("K.smc(D.f, {fvg: true, fvgAutoThreshold: false, swingLength: 3, internalLength: 2})", f=gap)["fvgs"]
    assert {"idx": 1, "top": 110, "bottom": 102, "bull": True, "end": None} in fvg


def test_smart_money_previous_day_levels_trend_and_range_filter():
    day1 = frame([100 + i for i in range(20)], start=10 * DAY + 9 * 3600 + 15 * 60)      # high 119+2, low 100-2
    day2 = frame([110 - i for i in range(20)], start=11 * DAY + 9 * 3600 + 15 * 60)
    f = {k: day1[k] + day2[k] for k in day1}
    got = run("K.smc(D.f, {dailyLevels: true, internalLength: 3, swingLength: 5})", f=f)
    levels = {lv["label"]: (lv["price"], lv["from"]) for lv in got["levels"]}
    assert levels == {"PDH": (max(day1["h"]), 20), "PDL": (min(day1["l"]), 20)}
    assert len(got["trend"]) == 40 and set(got["trend"]) <= {-1, 0, 1}
    assert run("K.smc(D.f, {obFilter: 'Cumulative Mean Range'})", f=f)["levels"] == []   # levels off by default
    defaults = run("K.SMC_DEFAULTS")
    assert defaults["showLabels"] is False and run("K.VP_DEFAULTS")["showLabels"] is False   # owner: no titles
