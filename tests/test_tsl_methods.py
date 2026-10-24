"""TSL maths: hand-calculated values following the TradingView scripts line by line."""

import pytest

from market_data.resampling import Candle
from paper_trading.tsl_methods import (
    PRESETS, StopPoint, atr, chandelier, method_stops, psar, rma, supertrend, true_range,
)

# o, h, l, c
ROWS = [(10, 11, 9, 10), (10, 12, 10, 11.5), (11.5, 13, 11, 12.5), (12.5, 12.6, 10.5, 10.8), (10.8, 11, 8.9, 9)]
BARS = [Candle(60 * i, *r, 0) for i, r in enumerate(ROWS)]


def approx(values):
    return [None if v is None else pytest.approx(v) for v in values]


def test_true_range_and_rma_like_tradingview():
    assert true_range(BARS) == approx([2, 2, 2, 2.1, 2.1])
    assert rma([1, 2, 3, 4], 2) == approx([None, 1.5, 2.25, 3.125])        # SMA seed, then Wilder
    assert atr(BARS, 2) == approx([None, 2, 2, 2.05, 2.075])


def test_chandelier_everget():
    longs, shorts, dirs = chandelier(BARS, length=2, mult=1.0, use_close=True)
    assert longs == approx([None, 9.5, 10.5, 10.5, 10.5])                  # never loosens while close stays above
    assert shorts == approx([None, 12, 12, 12.85, 11.075])
    assert dirs == [1, 1, 1, 1, -1]                                         # close 9 fell below 10.5
    highs, _, _ = chandelier(BARS, length=2, mult=1.0, use_close=False)    # extremums from highs
    assert highs[2] == pytest.approx(13 - 2)


def test_supertrend_tradingview():
    st, dirs, lowers, uppers = supertrend(BARS, atr_length=2, factor=1.0)
    assert lowers == approx([None, 9, 10, 10, 10])
    assert uppers == approx([None, 13, 13, 13, 12.025])
    assert dirs == [None, 1, 1, 1, 1] and st == approx([None, 13, 13, 13, 12.025])


def test_parabolic_sar_tradingview():
    sars, below = psar(BARS, 0.02, 0.02, 0.20)
    assert sars == approx([None, 9.0, 9.0, 9.16, 13.0])
    assert below == [None, True, True, True, False]                        # flipped on the last candle


def test_stops_for_long_and_short_sides():
    long_psar = method_stops("PSAR", {"start": 0.02, "increment": 0.02, "maximum": 0.2}, BARS, "LONG")
    assert long_psar[3] == StopPoint(pytest.approx(9.16)) and long_psar[4] == StopPoint(None, True)
    short_psar = method_stops("PSAR", {}, BARS, "SHORT")
    assert short_psar[4] == StopPoint(pytest.approx(13.0)) and short_psar[3].stop is None
    assert not short_psar[3].against                                       # never protected the short: no flip
    st_long = method_stops("SUPERTREND", {"atr_length": 2, "factor": 1.0}, BARS, "LONG")
    st_short = method_stops("SUPERTREND", {"atr_length": 2, "factor": 1.0}, BARS, "SHORT")
    assert st_long[4].stop == pytest.approx(10) and st_short[4].stop == pytest.approx(12.025)
    ch_short = method_stops("CHANDELIER", {"length": 2, "mult": 1.0}, BARS, "SHORT")
    assert ch_short[4].stop == pytest.approx(11.075)


def test_point_trail_from_the_hft_document():
    # entry 100 -> close 125: +25 profit, 10-point buffer protects +15 (115)
    bars = [Candle(0, 100, 101, 99, 110, 0), Candle(60, 110, 126, 109, 125, 0), Candle(120, 125, 140, 124, 139, 0)]
    stops = method_stops("POINTS", {"buffer": 10, "min_lock": 15}, bars, "LONG", entry_price=100)
    assert [p.stop for p in stops] == [None, 115, 129]
    short = method_stops("POINTS", {"buffer": 10, "min_lock": 15},
                         [Candle(0, 100, 101, 80, 80, 0)], "SHORT", entry_price=100)
    assert short[0].stop == 85                                               # mirror: min(80 + 10, 100 - 15)


def test_presets_hold_the_owner_values():
    assert PRESETS["CHANDELIER_9_1.5"] == ("CHANDELIER", {"length": 9, "mult": 1.5, "use_close": True})
    assert PRESETS["SUPERTREND_5_1.0"][1] == {"atr_length": 5, "factor": 1.0}
    assert PRESETS["SUPERTREND_7_1.5"][1] == {"atr_length": 7, "factor": 1.5}
    assert PRESETS["PSAR_0.02_0.02_0.20"][1] == {"start": 0.02, "increment": 0.02, "maximum": 0.20}
    assert PRESETS["PSAR_0.04_0.04_0.10"][1] == {"start": 0.04, "increment": 0.04, "maximum": 0.10}
    with pytest.raises(ValueError):
        method_stops("DONCHIAN", {}, BARS)                                  # excluded by the owner
