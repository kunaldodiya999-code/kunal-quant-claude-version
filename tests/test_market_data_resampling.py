from datetime import datetime
from zoneinfo import ZoneInfo

from market_data.resampling import Candle, aggregate_day, aggregate_regular_session


TZ = ZoneInfo("Asia/Kolkata")


def ts(value: str) -> int:
    return int(datetime.fromisoformat(value).replace(tzinfo=TZ).timestamp())


def candles_for(start: str, count: int) -> list[Candle]:
    base = ts(start)
    return [
        Candle(base + i * 60, 100 + i, 101 + i, 99 + i, 100.5 + i, 10, 1000 + i)
        for i in range(count)
    ]


def full_session() -> list[Candle]:
    return candles_for("2026-09-23T09:15:00", 375)


def test_complete_3m_bar():
    bars = aggregate_day(candles_for("2026-09-23T09:15:00", 3), 3)
    assert len(bars) == 1
    assert bars[0].complete
    assert bars[0].open == 100
    assert bars[0].high == 103
    assert bars[0].low == 99
    assert bars[0].close == 102.5
    assert bars[0].volume == 30


def test_missing_minute_is_incomplete_not_filled():
    candles = candles_for("2026-09-23T09:15:00", 6)
    candles.pop(1)
    bars = aggregate_day(candles, 3)
    assert len(bars) == 2
    assert not bars[0].complete
    assert bars[0].actual_1m_candles == 2
    assert bars[1].complete


def test_five_minute_complete_bar():
    bars = aggregate_day(candles_for("2026-09-23T09:15:00", 5), 5)
    assert len(bars) == 1
    assert bars[0].complete
    assert bars[0].actual_1m_candles == 5


def test_four_minute_gap_excludes_day():
    candles = full_session()
    del candles[100:104]
    bars = aggregate_regular_session(candles, 3)
    assert bars == []


def test_three_minute_gap_keeps_day_without_fabrication():
    candles = full_session()
    del candles[100:103]
    bars = aggregate_regular_session(candles, 5)
    assert bars
    incomplete = [bar for bar in bars if not bar.complete]
    assert incomplete
    assert incomplete[0].actual_1m_candles == 2
