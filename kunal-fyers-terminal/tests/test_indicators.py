"""BBP_NM line by line (owner's Pine v1 code), VWAP with futures volume, candles from 09:15, KTMI lock."""

import hashlib
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from terminal.candles import Candle, close_time, finished, parse_history, resample
from terminal.indicators import bbp_nm, vwap

IST = ZoneInfo("Asia/Kolkata")
T0 = int(datetime(2026, 10, 28, 9, 15, tzinfo=IST).timestamp())


def test_bbp_nm_follows_the_pine_formula():
    closes = [10, 12, 11, 15, 14, 13, 16, 12, 11, 12, 13]
    out = bbp_nm(closes, window=10)
    assert out[8] == (None, None, None)                       # fewer than 10 bars: na
    # bar 9 (close 12): highest 16 is 3 bars back, lowest 10 is 9 bars back
    bear, bull, direction = out[9]
    assert bear == pytest.approx(-((16 - 12) + (16 - 12) / -3))
    assert bull == pytest.approx((12 - 10) + (12 - 10) / -9)
    assert direction == pytest.approx(2 * bull + 2 * bear)
    # a bar that IS the highest close: (h - c) / 0 -> na, like Pine
    rising = list(range(1, 15))
    assert bbp_nm(rising, window=10)[-1][0] is None and bbp_nm(rising, window=10)[-1][2] is None


def test_vwap_uses_the_given_volume_and_restarts_each_day():
    cs = [Candle(T0, 100, 102, 98, 101), Candle(T0 + 60, 101, 104, 100, 103)]
    v = vwap(cs, [10, 30])
    assert v[0] == pytest.approx((102 + 98 + 101) / 3)
    assert v[1] == pytest.approx(((102 + 98 + 101) / 3 * 10 + (104 + 100 + 103) / 3 * 30) / 40)
    next_day = Candle(T0 + 86400, 50, 50, 50, 50)
    assert vwap(cs + [next_day], [10, 30, 5])[-1] == pytest.approx(50)


def test_three_minute_candles_start_at_0915_and_only_finished_ones_count():
    mins = [Candle(T0 + 60 * i, 100 + i, 101 + i, 99 + i, 100.5 + i, 10) for i in range(7)]
    bars = resample(mins, 3)
    assert [b.ts - T0 for b in bars] == [0, 180, 360]
    assert (bars[0].open, bars[0].high, bars[0].low, bars[0].close, bars[0].volume) == (100, 103, 99, 102.5, 30)
    assert close_time(bars[0].ts, 3) == T0 + 180
    assert [b.ts for b in finished(bars, 3, now=T0 + 400)] == [T0, T0 + 180]   # 09:21 candle still open


def test_parse_history_reports_fyers_errors():
    assert parse_history({"s": "ok", "candles": [[T0, 1, 2, 0.5, 1.5, 9]]})[0].volume == 9
    with pytest.raises(ValueError):
        parse_history({"s": "error", "message": "invalid token"})


def test_ktmi_uni_lite_copy_is_the_locked_original():
    from indicators.ktmi_uni_lite.config import LOCKED_PINE_FILE, LOCKED_PINE_SHA256
    data = (Path(__file__).resolve().parents[1] / "indicators" / "ktmi_uni_lite" / LOCKED_PINE_FILE).read_bytes()
    assert hashlib.sha256(data.replace(b"\r\n", b"\n")).hexdigest() == LOCKED_PINE_SHA256
