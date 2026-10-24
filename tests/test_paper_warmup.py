"""Morning warm-up: KTMI sees earlier sessions' history before live ticks."""

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from market_data.resampling import Candle, aggregate_day
from paper_trading.market_data_pipeline import PaperMarketDataPipeline
from paper_trading.warmup import fetch_minute_history, parse_history_candles, warmup_calendar_days

IST = ZoneInfo("Asia/Kolkata")
SYMBOL = "NSE:NIFTY50-INDEX"


def ts(day, hour, minute):
    return int(datetime(2026, 10, day, hour, minute, tzinfo=IST).timestamp())


def session_minutes(day, until=(15, 29)):
    start, last = ts(day, 9, 15), ts(day, *until)
    return [Candle(t, 100 + i % 7, 101 + i % 7, 99 + i % 7, 100.5 + i % 5)
            for i, t in enumerate(range(start, last + 60, 60))]


def tick(timestamp, ltp):
    return {"symbol": SYMBOL, "last_traded_time": timestamp + 5, "ltp": ltp, "type": "sf"}


@pytest.mark.parametrize("resolution", [1, 3, 5, 15, 60])
def test_first_live_bar_is_evaluated_with_the_full_history(resolution):
    seen = []

    def evaluator(bars, *, paper_config):
        seen.append(list(bars))
        return []

    # Friday 23 Oct full day + Monday 26 Oct up to 10:00 (started late).
    history = session_minutes(23) + session_minutes(26, until=(9, 59))
    pipeline = PaperMarketDataPipeline(resolution_minutes=resolution, signal_evaluator=evaluator)
    seeded = pipeline.seed_history(SYMBOL, history)
    assert seeded > 0
    assert seen == []                                   # history never produces signals

    # Live ticks for 10:00 .. until the next bar of this timeframe closes.
    t = ts(26, 10, 0)
    while not seen:
        pipeline.on_message(tick(t, 101))
        t += 60
        assert t < ts(26, 12, 0)

    expected = []
    for day in (23, 26):
        minutes = [c for c in history if datetime.fromtimestamp(c.timestamp, IST).day == day]
        live = [c.timestamp for c in minutes]
        if resolution == 1:
            expected += live
        else:
            expected += [b.timestamp for b in aggregate_day(minutes, resolution) if b.complete]
    got = [bar.timestamp for bar in seen[0]]
    assert got[: len(expected)] == expected             # every earlier bar, in order
    assert got[-1] > expected[-1]                       # plus the new live bar


def test_seed_after_live_ticks_is_refused():
    pipeline = PaperMarketDataPipeline(resolution_minutes=3, signal_evaluator=lambda b, **k: [])
    pipeline.on_message(tick(ts(26, 9, 15), 100))
    pipeline.on_message(tick(ts(26, 9, 16), 100))
    with pytest.raises(RuntimeError):
        pipeline.seed_history(SYMBOL, session_minutes(23))


def test_warmup_days_cover_about_300_bars_for_every_timeframe():
    assert warmup_calendar_days(1) >= 5                   # Monday still reaches Friday
    assert warmup_calendar_days(3) >= 5
    assert warmup_calendar_days(60) >= 43 * 7 // 5        # 7 bars a day -> ~43 trading days


class FakeClient:
    def __init__(self, candles):
        self.candles = candles
        self.calls = []

    def history(self, symbol, *, resolution, range_from, range_to):
        self.calls.append((range_from, range_to))
        lo = int(datetime.combine(date.fromisoformat(range_from), datetime.min.time(), IST).timestamp())
        hi = int(datetime.combine(date.fromisoformat(range_to) + timedelta(days=1), datetime.min.time(), IST).timestamp())
        return {"s": "ok", "candles": [[c.timestamp, c.open, c.high, c.low, c.close, 0]
                                       for c in self.candles if lo <= c.timestamp < hi]}


def test_fetch_uses_chunks_and_drops_the_forming_minute():
    candles = session_minutes(23) + session_minutes(26, until=(10, 5))
    client = FakeClient(candles)
    now = datetime(2026, 10, 26, 10, 5, 30, tzinfo=IST)       # 10:05 minute still forming
    got = fetch_minute_history(client, SYMBOL, resolution_minutes=60, now=now)
    assert got[-1].timestamp == ts(26, 10, 4)
    assert len(client.calls) >= 2                             # 60m needs ~2 months: chunked
    assert all(r[0] <= r[1] for r in client.calls)


def test_bad_history_response_is_a_clear_error():
    with pytest.raises(ValueError, match="candles"):
        parse_history_candles({"s": "error"})
