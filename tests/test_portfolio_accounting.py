from backtest.portfolio_accounting import build_equity_curve


def test_equity_curve_uses_net_pnl_and_tracks_drawdown():
    result = build_equity_curve(
        initial_capital=100_000,
        trades=(
            (3, 2_000, 100),
            (1, -1_000, 50),
            (2, 3_000, 100),
        ),
    )

    assert result.initial_capital == 100_000
    assert result.gross_pnl == 4_000
    assert result.total_costs == 250
    assert result.net_pnl == 3_750
    assert result.ending_equity == 103_750
    assert result.peak_equity == 103_750
    assert result.max_drawdown == 1_050
    assert round(result.max_drawdown_pct, 6) == round(1050 / 100000 * 100, 6)
    assert result.wins == 2
    assert result.losses == 1
    assert round(result.win_rate_pct, 6) == round(2 / 3 * 100, 6)

    assert [point.timestamp for point in result.equity_curve] == [1, 2, 3]
    assert [point.equity for point in result.equity_curve] == [
        98_950,
        101_850,
        103_750,
    ]


def test_equity_curve_rejects_non_positive_initial_capital():
    try:
        build_equity_curve(initial_capital=0, trades=())
    except ValueError as exc:
        assert str(exc) == "initial_capital must be positive"
    else:
        raise AssertionError("expected ValueError")
