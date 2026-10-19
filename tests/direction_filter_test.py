from strategies.direction_filter import (
    Direction,
    DirectionDecision,
    DirectionMode,
    DirectionReason,
    apply_direction_filter,
)


def main() -> None:

    print("=" * 78)
    print("KUNAL QUANT — DIRECTION FILTER TEST")
    print("=" * 78)

    test_cases = (
        (
            Direction.LONG,
            DirectionMode.BOTH,
            DirectionDecision.ALLOW,
            DirectionReason.BOTH_DIRECTIONS_ENABLED,
        ),
        (
            Direction.SHORT,
            DirectionMode.BOTH,
            DirectionDecision.ALLOW,
            DirectionReason.BOTH_DIRECTIONS_ENABLED,
        ),
        (
            Direction.LONG,
            DirectionMode.LONG_ONLY,
            DirectionDecision.ALLOW,
            DirectionReason.LONG_DIRECTION_ALLOWED,
        ),
        (
            Direction.SHORT,
            DirectionMode.LONG_ONLY,
            DirectionDecision.BLOCK,
            DirectionReason.SHORT_DIRECTION_DISABLED,
        ),
        (
            Direction.LONG,
            DirectionMode.SHORT_ONLY,
            DirectionDecision.BLOCK,
            DirectionReason.LONG_DIRECTION_DISABLED,
        ),
        (
            Direction.SHORT,
            DirectionMode.SHORT_ONLY,
            DirectionDecision.ALLOW,
            DirectionReason.SHORT_DIRECTION_ALLOWED,
        ),
    )

    passed = 0

    for (
        direction,
        mode,
        expected_decision,
        expected_reason,
    ) in test_cases:

        result = apply_direction_filter(
            direction,
            mode,
        )

        assert result.decision == expected_decision
        assert result.reason == expected_reason
        assert result.allowed == (
            expected_decision == DirectionDecision.ALLOW
        )

        print(
            f"PASS | "
            f"{direction.value:5s} | "
            f"{mode.value:10s} | "
            f"{result.decision.value:5s} | "
            f"{result.reason.value}"
        )

        passed += 1

    print()
    print(f"Total : {len(test_cases)}")
    print(f"Passed: {passed}")
    print(f"Failed: {len(test_cases) - passed}")

    assert passed == len(test_cases)

    print()
    print("ALL DIRECTION FILTER TESTS PASSED")


if __name__ == "__main__":
    main()