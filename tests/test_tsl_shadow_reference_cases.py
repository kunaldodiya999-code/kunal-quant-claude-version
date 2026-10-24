from paper_trading.tsl_shadow_lab import OptionCandle, TslShadowLab, _Candidate


def _bars_with_old_spike():
    bars = [
        OptionCandle(timestamp=60, open=149.5, high=150.0, low=149.0, close=149.5),
    ]
    # Keep later candles in a lower range; the first high must age out of the
    # 9-candle Chandelier high-water lookback.
    for i in range(1, 10):
        low = 100.0 + i * 0.1
        high = low + 1.0
        bars.append(
            OptionCandle(
                timestamp=(i + 1) * 60,
                open=low + 0.2,
                high=high,
                low=low,
                close=low + 0.5,
            )
        )
    return bars


def test_chandelier_uses_rolling_nine_bar_high_not_lifetime_high():
    lab = TslShadowLab.__new__(TslShadowLab)
    bars = _bars_with_old_spike()
    candidate = _Candidate("chandelier_atr9_mult1.5")

    stop = lab._candidate_stop(candidate.name, bars, candidate)
    atr = lab._atr_wilder(bars, 9)
    expected_rolling_high = max(bar.high for bar in bars[-9:]) - 1.5 * atr
    incorrect_lifetime_high = max(bar.high for bar in bars) - 1.5 * atr

    assert stop == expected_rolling_high
    assert stop < incorrect_lifetime_high


def test_chandelier_stop_never_moves_down_after_ratchet():
    lab = TslShadowLab.__new__(TslShadowLab)
    bars = _bars_with_old_spike()
    candidate = _Candidate("chandelier_atr9_mult1.5", stop=500.0)

    stop = lab._candidate_stop(candidate.name, bars, candidate)

    assert stop == 500.0
