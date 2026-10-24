import math
import random
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from backtest.opening_breakout_v2_indicators import (
    V2IndicatorProvider,
    bollinger_bands,
    dmi,
    session_vwap,
)
from backtest.opening_breakout_v2_signal_engine import SignalSeries, scan_series
from indicators.ktmi.universal import OHLCData, calculate_ktmi
from research.opening_breakout_1m_v2 import Candle, V2Config

IST = ZoneInfo("Asia/Kolkata")


def _ts(day: int, hour: int, minute: int) -> int:
    return int(datetime(2026, 9, day, hour, minute, tzinfo=IST).timestamp())


def _random_walk(count: int = 400, seed: int = 7) -> list[Candle]:
    rng = random.Random(seed)
    candles = []
    price = 25000.0
    start = _ts(1, 9, 15)
    for index in range(count):
        open_price = price
        close = open_price + rng.uniform(-15, 15)
        high = max(open_price, close) + rng.uniform(0, 8)
        low = min(open_price, close) - rng.uniform(0, 8)
        candles.append(Candle(start + 60 * index, open_price, high, low, close))
        price = close
    return candles


def _pandas_dmi(candles, length, smoothing):
    """Independent TradingView ta.dmi reference using pandas."""
    pd = pytest.importorskip("pandas")
    df = pd.DataFrame([c.__dict__ for c in candles])
    up = df.high.diff()
    down = -df.low.diff()
    plus_dm = ((up > down) & (up > 0)) * up
    minus_dm = ((down > up) & (down > 0)) * down
    tr = pd.concat(
        [
            df.high - df.low,
            (df.high - df.close.shift()).abs(),
            (df.low - df.close.shift()).abs(),
        ],
        axis=1,
    ).max(axis=1)
    tr.iloc[0] = float("nan")
    plus_dm.iloc[0] = float("nan")
    minus_dm.iloc[0] = float("nan")

    def rma(series, n):
        values = series.to_numpy(dtype=float)
        out = [float("nan")] * len(values)
        valid = [i for i, v in enumerate(values) if not math.isnan(v)]
        seed_end = valid[n - 1]
        out[seed_end] = sum(values[valid[0]:seed_end + 1]) / n
        for i in range(seed_end + 1, len(values)):
            out[i] = (out[i - 1] * (n - 1) + values[i]) / n
        return pd.Series(out)

    str_ = rma(tr, length)
    plus = 100 * rma(plus_dm, length) / str_
    minus = 100 * rma(minus_dm, length) / str_
    total = (plus + minus).replace(0, 1)
    adx = 100 * rma((plus - minus).abs() / total, smoothing)
    return plus, minus, adx


def test_dmi_matches_independent_tradingview_reference():
    candles = _random_walk()
    plus, minus, adx = dmi(candles, 14, 14)
    ref_plus, ref_minus, ref_adx = _pandas_dmi(candles, 14, 14)

    assert plus[13] is None and plus[14] is not None
    assert adx[26] is None and adx[27] is not None
    for index in range(27, len(candles)):
        assert plus[index] == pytest.approx(ref_plus[index], rel=1e-9)
        assert minus[index] == pytest.approx(ref_minus[index], rel=1e-9)
        assert adx[index] == pytest.approx(ref_adx[index], rel=1e-9)


def test_bollinger_matches_pandas_population_stdev():
    pd = pytest.importorskip("pandas")
    closes = [c.close for c in _random_walk(120)]
    upper, lower = bollinger_bands(closes, 20, 2.0)
    series = pd.Series(closes)
    basis = series.rolling(20).mean()
    deviation = series.rolling(20).std(ddof=0)

    assert upper[18] is None
    for index in range(19, len(closes)):
        assert upper[index] == pytest.approx(basis[index] + 2 * deviation[index])
        assert lower[index] == pytest.approx(basis[index] - 2 * deviation[index])


def test_vwap_resets_each_session_and_refuses_zero_volume():
    day1 = [Candle(_ts(1, 9, 15), 10, 12, 9, 11), Candle(_ts(1, 9, 16), 11, 14, 11, 13)]
    day2 = [Candle(_ts(2, 9, 15), 20, 21, 19, 20), Candle(_ts(2, 9, 16), 20, 22, 20, 21)]
    vwap = session_vwap(day1 + day2, [100, 300, 0, 50])

    tp = [(c.high + c.low + c.close) / 3 for c in day1 + day2]
    assert vwap[0] == pytest.approx(tp[0])
    assert vwap[1] == pytest.approx((tp[0] * 100 + tp[1] * 300) / 400)
    assert vwap[2] is None  # no volume yet in session 2: no fabricated VWAP
    assert vwap[3] == pytest.approx(tp[3])  # day-1 volume not carried over


def test_snapshots_are_causal_under_truncation():
    candles = _random_walk(300)
    volumes = [100 + i for i in range(len(candles))]
    config = V2Config()
    full = V2IndicatorProvider(candles, config=config, volumes=volumes)
    cut = 180
    partial = V2IndicatorProvider(candles[:cut], config=config, volumes=volumes[:cut])

    for candle in candles[:cut]:
        assert partial(candle.timestamp, candle) == full(candle.timestamp, candle)


def test_ktmi_fields_map_to_locked_ktmi_modules():
    candles = _random_walk(200)
    provider = V2IndicatorProvider(candles, config=V2Config())
    reference = calculate_ktmi([OHLCData(c.open, c.high, c.low, c.close) for c in candles])

    for candle, result in zip(candles, reference):
        snap = provider(candle.timestamp, candle)
        assert snap.ktmi_momentum_speed == result.momentum.speed
        assert snap.ktmi_buying_speed == result.long_momentum.speed
        assert snap.ktmi_selling_speed == result.short_momentum.speed


def test_unknown_timestamp_fails_closed():
    candles = _random_walk(50)
    provider = V2IndicatorProvider(candles, config=V2Config())
    assert provider(1, candles[0]).vwap is None


def test_above_vwap_trigger_fires_only_with_real_indicator_values():
    setup = Candle(_ts(3, 9, 15), 100, 101, 100, 100.5)
    below = Candle(_ts(3, 9, 16), 100.5, 100.6, 99, 99.2)
    above = Candle(_ts(3, 9, 17), 99.2, 104, 99.1, 103.8)
    candles = [setup, below, above]
    config = V2Config(selected_triggers=("ABOVE_VWAP",), filter_open_low=True)
    series = SignalSeries("NIFTY", "CE", 0, 1, tuple(candles))

    provider = V2IndicatorProvider(candles, config=config, volumes=[1000, 1000, 1000])
    _, events = scan_series(series, config, provider)
    assert len(events) == 1
    assert events[0].trigger_timestamp == above.timestamp

    no_volume = V2IndicatorProvider(candles, config=config)
    _, events = scan_series(series, config, no_volume)
    assert events == ()
