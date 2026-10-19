from backtest.opening_breakout_v2_multi_session import (
    group_candles_by_session,
)
from research.opening_breakout_1m_v2 import Candle


def test_group_candles_by_session_isolates_setup_candles():
    candles = [
        Candle(1720000000, 1, 2, 0, 1),
        Candle(1720000060, 1, 3, 1, 2),
        Candle(1720086400, 10, 11, 9, 10),
        Candle(1720086460, 10, 12, 9, 11),
    ]

    sessions = group_candles_by_session(candles)

    assert len(sessions) == 2
    assert [c.timestamp for c in sessions[0][1]] == [1720000000, 1720000060]
    assert [c.timestamp for c in sessions[1][1]] == [1720086400, 1720086460]
    assert sessions[0][1][0].high == 2
    assert sessions[1][1][0].high == 11
