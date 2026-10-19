from dataclasses import replace

from market_data.eligibility import eligible_bars
from market_data.resampling import DerivedBar


def make_bar(timestamp: int, complete: bool) -> DerivedBar:
    return DerivedBar(
        timestamp=timestamp,
        open=100,
        high=101,
        low=99,
        close=100.5,
        volume=10,
        open_interest=1000,
        resolution="3",
        expected_1m_candles=3,
        actual_1m_candles=3 if complete else 2,
        complete=complete,
    )


def test_only_complete_bars_are_eligible():
    bars = [make_bar(1, True), make_bar(2, False), make_bar(3, True)]

    eligible = eligible_bars(bars)

    assert [bar.timestamp for bar in eligible] == [1, 3]
    assert all(bar.resolution == "3" for bar in eligible)


def test_incomplete_bar_is_not_modified_or_filled():
    incomplete = make_bar(2, False)

    eligible = eligible_bars([incomplete])

    assert eligible == []
    assert incomplete.actual_1m_candles == 2
    assert not incomplete.complete
