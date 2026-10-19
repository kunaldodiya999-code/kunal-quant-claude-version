from dataclasses import replace

from indicators.ktmi.signals import KTMISignalResult
from strategies.direction_filter import DirectionMode
from strategies.ktmi_strategy import (
    KTMIEntryConfig,
    StrategyAction,
    StrategyReason,
    evaluate_ktmi_entry,
)


def make_signals(**overrides) -> KTMISignalResult:
    """Create a controlled KTMI signal row for testing."""

    values = {
        "momentum_buy": False,
        "long_buy": False,
        "short_buy": False,

        "momentum_sell": False,
        "long_sell": False,
        "short_sell": False,

        "bullish_confluence": False,
        "bearish_confluence": False,

        "enabled_count": 3,
        "bullish_count": 0,
        "bearish_count": 0,
    }

    values.update(overrides)

    return KTMISignalResult(**values)


def main() -> None:

    print("=" * 78)
    print("KUNAL QUANT — KTMI STRATEGY TEST")
    print("=" * 78)

    passed = 0

    # 1. No signal.
    result = evaluate_ktmi_entry(
        make_signals(),
        KTMIEntryConfig(),
    )

    assert result.action == StrategyAction.NO_ENTRY
    assert result.reason == StrategyReason.NO_SIGNAL

    print("PASS | No signal → NO_ENTRY")
    passed += 1

    # 2. LONG signal.
    result = evaluate_ktmi_entry(
        make_signals(momentum_buy=True),
        KTMIEntryConfig(),
    )

    assert result.action == StrategyAction.LONG
    assert result.direction_filter is not None
    assert result.direction_filter.allowed

    print("PASS | LONG signal + BOTH → LONG")
    passed += 1

    # 3. SHORT signal.
    result = evaluate_ktmi_entry(
        make_signals(momentum_sell=True),
        KTMIEntryConfig(),
    )

    assert result.action == StrategyAction.SHORT
    assert result.direction_filter is not None
    assert result.direction_filter.allowed

    print("PASS | SHORT signal + BOTH → SHORT")
    passed += 1

    # 4. LONG_ONLY blocks SHORT.
    result = evaluate_ktmi_entry(
        make_signals(momentum_sell=True),
        KTMIEntryConfig(
            direction_mode=DirectionMode.LONG_ONLY,
        ),
    )

    assert result.action == StrategyAction.NO_ENTRY
    assert result.direction is not None
    assert result.reason == StrategyReason.SHORT_SIGNAL_BLOCKED

    print("PASS | SHORT signal + LONG_ONLY → BLOCK")
    passed += 1

    # 5. SHORT_ONLY blocks LONG.
    result = evaluate_ktmi_entry(
        make_signals(momentum_buy=True),
        KTMIEntryConfig(
            direction_mode=DirectionMode.SHORT_ONLY,
        ),
    )

    assert result.action == StrategyAction.NO_ENTRY
    assert result.direction is not None
    assert result.reason == StrategyReason.LONG_SIGNAL_BLOCKED

    print("PASS | LONG signal + SHORT_ONLY → BLOCK")
    passed += 1

    # 6. Bullish confluence can be used as an entry.
    result = evaluate_ktmi_entry(
        make_signals(
            bullish_confluence=True,
        ),
        KTMIEntryConfig(),
    )

    assert result.action == StrategyAction.LONG

    print("PASS | Bullish confluence → LONG")
    passed += 1

    # 7. Bearish confluence can be used as an entry.
    result = evaluate_ktmi_entry(
        make_signals(
            bearish_confluence=True,
        ),
        KTMIEntryConfig(),
    )

    assert result.action == StrategyAction.SHORT

    print("PASS | Bearish confluence → SHORT")
    passed += 1

    # 8. Require bullish confluence.
    result = evaluate_ktmi_entry(
        make_signals(
            momentum_buy=True,
            bullish_confluence=False,
        ),
        KTMIEntryConfig(
            require_bullish_confluence=True,
        ),
    )

    assert result.action == StrategyAction.NO_ENTRY

    print("PASS | Required bullish confluence → NO_ENTRY")
    passed += 1

    # 9. Require bullish confluence and receive it.
    result = evaluate_ktmi_entry(
        make_signals(
            momentum_buy=True,
            bullish_confluence=True,
        ),
        KTMIEntryConfig(
            require_bullish_confluence=True,
        ),
    )

    assert result.action == StrategyAction.LONG

    print("PASS | Required bullish confluence → LONG")
    passed += 1

    # 10. Both directions simultaneously.
    result = evaluate_ktmi_entry(
        make_signals(
            momentum_buy=True,
            momentum_sell=True,
        ),
        KTMIEntryConfig(),
    )

    assert result.action == StrategyAction.NO_ENTRY
    assert (
        result.reason
        == StrategyReason.MULTIPLE_DIRECTION_SIGNALS
    )

    print(
        "PASS | Conflicting directions → NO_ENTRY"
    )
    passed += 1

    print()
    print(f"Total : 10")
    print(f"Passed: {passed}")
    print(f"Failed: {10 - passed}")

    assert passed == 10

    print()
    print("ALL KTMI STRATEGY TESTS PASSED")


if __name__ == "__main__":
    main()