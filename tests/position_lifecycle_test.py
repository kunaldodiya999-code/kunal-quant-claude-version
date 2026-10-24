"""
KUNAL QUANT
Position Lifecycle V1 Test
"""

from backtest.position_lifecycle import (
    ActivePosition,
    PositionLifecycleConfig,
    SignalAction,
    evaluate_signal,
)


STRATEGY_A = (
    "KTMI_LONG_SHORT_SPEED"
)

STRATEGY_B = (
    "KTMI_MOMENTUM_ONLY"
)


def test_empty_position_allows_entry():

    result = evaluate_signal(
        strategy_id=STRATEGY_A,
        direction="LONG",
        symbol="NSE:NIFTY24N2123350CE",
        active_positions=[],
    )

    assert result.action == SignalAction.ENTER

    assert result.reason == (
        "NO_ACTIVE_POSITION"
    )

    print(
        "PASS | Empty account -> ENTER"
    )


def test_same_strategy_same_direction_ignored():

    active = [
        ActivePosition(
            strategy_id=STRATEGY_A,
            direction="LONG",
            symbol="NSE:NIFTY24N2123350CE",
        )
    ]

    result = evaluate_signal(
        strategy_id=STRATEGY_A,
        direction="LONG",
        symbol="NSE:NIFTY24N2123350CE",
        active_positions=active,
    )

    assert result.action == SignalAction.IGNORE

    assert result.reason == (
        "SAME_STRATEGY_POSITION_ALREADY_OPEN"
    )

    print(
        "PASS | Same strategy + same direction -> IGNORE"
    )


def test_same_strategy_opposite_direction_ignored():

    active = [
        ActivePosition(
            strategy_id=STRATEGY_A,
            direction="LONG",
            symbol="NSE:NIFTY24N2123350CE",
        )
    ]

    result = evaluate_signal(
        strategy_id=STRATEGY_A,
        direction="SHORT",
        symbol="NSE:NIFTY24N2123350PE",
        active_positions=active,
    )

    assert result.action == SignalAction.IGNORE

    assert result.reason == (
        "SAME_STRATEGY_OPPOSITE_POSITION_ALREADY_OPEN"
    )

    print(
        "PASS | Same strategy + opposite direction -> IGNORE"
    )


def test_different_strategy_can_enter():

    active = [
        ActivePosition(
            strategy_id=STRATEGY_A,
            direction="LONG",
            symbol="NSE:NIFTY24N2123350CE",
        )
    ]

    result = evaluate_signal(
        strategy_id=STRATEGY_B,
        direction="LONG",
        symbol="NSE:NIFTY24N2123350CE",
        active_positions=active,
    )

    assert result.action == SignalAction.ENTER

    assert result.reason == (
        "DIFFERENT_STRATEGY_POSITION_ALLOWED"
    )

    print(
        "PASS | Strategy B can enter while Strategy A is open"
    )


def test_different_strategy_can_be_disabled():

    active = [
        ActivePosition(
            strategy_id=STRATEGY_A,
            direction="LONG",
            symbol="NSE:NIFTY24N2123350CE",
        )
    ]

    config = PositionLifecycleConfig(
        allow_different_strategy_positions=False
    )

    result = evaluate_signal(
        strategy_id=STRATEGY_B,
        direction="LONG",
        symbol="NSE:NIFTY24N2123350CE",
        active_positions=active,
        config=config,
    )

    assert result.action == SignalAction.IGNORE

    assert result.reason == (
        "ANOTHER_STRATEGY_POSITION_ALREADY_OPEN"
    )

    print(
        "PASS | Different-strategy entry can be disabled"
    )


def test_same_strategy_reentry_can_be_enabled():

    active = [
        ActivePosition(
            strategy_id=STRATEGY_A,
            direction="LONG",
            symbol="NSE:NIFTY24N2123350CE",
        )
    ]

    config = PositionLifecycleConfig(
        allow_same_strategy_reentry=True
    )

    result = evaluate_signal(
        strategy_id=STRATEGY_A,
        direction="LONG",
        symbol="NSE:NIFTY24N2123350CE",
        active_positions=active,
        config=config,
    )

    assert result.action == SignalAction.ENTER

    assert result.reason == (
        "SAME_STRATEGY_REENTRY_ALLOWED"
    )

    print(
        "PASS | Same-strategy re-entry configurable"
    )


def main():

    print()
    print("=" * 90)
    print(
        "KUNAL QUANT — POSITION LIFECYCLE V1 TEST"
    )
    print("=" * 90)

    test_empty_position_allows_entry()

    test_same_strategy_same_direction_ignored()

    test_same_strategy_opposite_direction_ignored()

    test_different_strategy_can_enter()

    test_different_strategy_can_be_disabled()

    test_same_strategy_reentry_can_be_enabled()

    print()
    print("=" * 90)
    print(
        "ALL POSITION LIFECYCLE V1 TESTS PASSED"
    )
    print("=" * 90)


if __name__ == "__main__":
    main()
    