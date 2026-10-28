"""Owner 28 Oct 2026: FYERS Smart Charts have no 3-minute chart, so the FYERS KTMI scripts build N-minute candles
from a 1-minute chart. Here: a line-by-line Python copy of that Pine code must give EXACTLY the engine's arrows
(the engine = the KTMI Uni Lite we trade). On 2 months of real NIFTY 1-minute data it gave 125 / 125 arrows on
3-min and 71 / 71 on 5-min (28 Oct 2026); this test repeats it on sample prices."""

import math
import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from indicators.ktmi.universal import OHLCData
from indicators.ktmi_uni_lite import UNI_LITE_CORE, calculate_uni_lite
from market_data.resampling import Candle
from paper_trading.market_data_pipeline import bar_close_timestamp
from research.ktmi_accuracy import signal_bars

IST = ZoneInfo("Asia/Kolkata")
FOLDER = Path(__file__).resolve().parents[1] / "indicators" / "ktmi_uni_lite"
SCRIPTS = (FOLDER / "KTMI_Uni_Lite_FYERS_SmartScript.pine", FOLDER / "KTMI_Uni_Lite_FYERS_Arrows.pine")


class EmaOn:                                     # Pine emaOn(x, len, upd)
    def __init__(self, n):
        self.n, self.e, self.total, self.count = n, None, 0.0, 0

    def __call__(self, x, upd):
        if upd and x is not None:
            if self.e is None:
                self.count += 1
                self.total += x
                if self.count >= self.n:
                    self.e = self.total / self.n
            else:
                self.e = self.e + 2.0 / (self.n + 1) * (x - self.e)
        return self.e


class KtmiAgg:                                   # Pine ktmiAgg(src, 5, 9, invert, upd)
    def __init__(self, invert):
        self.e1, self.e2, self.e3, self.sig = EmaOn(5), EmaOn(5), EmaOn(5), EmaOn(9)
        self.prev = self.raw = None
        self.invert = invert

    def __call__(self, x, upd):
        e3 = self.e3(self.e2(self.e1(x, upd), upd), upd)
        if upd and e3 is not None:
            self.raw = 100.0 * (e3 - self.prev) / self.prev if self.prev not in (None, 0.0) else None
            if self.invert and self.raw is not None:
                self.raw = -self.raw
            self.prev = e3
        sig = self.sig(self.raw, upd)
        return (None if self.raw is None else self.raw * 100), (None if sig is None else sig * 100)


def script_arrows(minutes, n):
    """The FYERS script, bar by bar on a 1-minute chart: (candle close time, side) of every trade arrow."""
    long_m, short_m = KtmiAgg(False), KtmiAgg(True)
    key = high = low = prev_long = prev_short = None
    out = []
    for c in minutes:
        t = datetime.fromtimestamp(c.timestamp, IST)
        sess = t.hour * 60 + t.minute - 555
        inside = 0 <= sess <= 374
        bucket = (t.date(), math.floor(sess / n))
        if inside:
            if key != bucket:
                key, high, low = bucket, c.high, c.low
            else:
                high, low = max(high, c.high), min(low, c.low)
        done = inside and ((sess + 1) % n == 0 or sess == 374)
        ls, lg = long_m(high, done)
        ss, sg = short_m(low, done)
        # Pine: a comparison with na is false, so no arrow until the Signal line exists ("is not None" below)
        if done and prev_long is not None and ls is not None and prev_long <= 0.5 < ls and lg is not None and ls > lg and ls > 0:
            out.append((c.timestamp + 60, "LONG"))
        if done and prev_short is not None and ss is not None and prev_short <= 0.5 < ss and sg is not None and ss > sg and ss > 0:
            out.append((c.timestamp + 60, "SHORT"))
        if done:
            prev_long, prev_short = ls, ss
    return out


def engine_arrows(minutes, n):
    bars = signal_bars(minutes, n)
    values = calculate_uni_lite([OHLCData(b.open, b.high, b.low, b.close) for b in bars], UNI_LITE_CORE)
    out = []
    for b, v in zip(bars, values):
        if v.long_buy:
            out.append((bar_close_timestamp(b.timestamp, n), "LONG"))
        if v.short_buy:
            out.append((bar_close_timestamp(b.timestamp, n), "SHORT"))
    return out


def sample_minutes(days=(19, 20, 21, 22, 23)):
    out = []
    for d in days:
        start = int(datetime(2026, 10, d, 9, 15, tzinfo=IST).timestamp())
        for i in range(375):
            p = 22000 + 60 * math.sin(i / 25 + d) + 25 * math.sin(i / 7) + 3 * d
            out.append(Candle(start + 60 * i, p, p + 4 + (i % 5), p - 4 - (i % 3), p + 1.5 * math.cos(i / 3), 0))
    return out


@pytest.mark.parametrize("n", [3, 5])
def test_script_copy_gives_exactly_the_engines_arrows(n):
    minutes = sample_minutes()
    ours, theirs = script_arrows(minutes, n), engine_arrows(minutes, n)
    assert len(theirs) >= 5
    assert ours == theirs


def _flat(path):
    return re.sub(r"\s+", " ", re.sub(r"//[^\n]*", "", path.read_text(encoding="utf-8")))


@pytest.mark.parametrize("path", SCRIPTS, ids=lambda p: p.stem)
def test_both_fyers_scripts_contain_the_tested_code(path):
    text = _flat(path)
    for line in ("useAgg = candleMinutes > 1 and timeframe.isminutes and timeframe.multiplier == 1",
                 "sessMin = hour * 60 + minute - 555", "inSession = sessMin >= 0 and sessMin <= 374",
                 "math.floor(sessMin / candleMinutes)",
                 "done = useAgg and inSession and ((sessMin + 1) % candleMinutes == 0 or sessMin == 374)",
                 "if count >= len e := total / len else e := e + 2.0 / (len + 1) * (x - e)",
                 "raw := not na(prevE3) and prevE3 != 0.0 ? 100.0 * (e3 - prevE3) / prevE3 : na",
                 "raw := invert and not na(raw) ? -raw : raw", "sig = emaOn(raw, signalLen, upd)",
                 "pLong := aLongSpeed", 'input.int(3, "Candle size in minutes'):
        assert line in text, line
    assert "pLong <= longBuyTrigger and aLongSpeed > longBuyTrigger" in text or \
        "prev <= trig and spd > trig and spd > sig and spd > 0" in text
