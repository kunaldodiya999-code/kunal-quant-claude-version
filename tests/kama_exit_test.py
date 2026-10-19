"""
Kunal Quant — KAMA Exit Engine Test V2.
"""

from __future__ import annotations

from backtest.models import ExitReason, OpenPosition
from indicators.kama_trend_follower.universal import KAMAResult
from strategies.exits.kama_exit import KAMAExitEvaluator


def make_kama_result(
    kama: float | None,
) -> KAMAResult:

    return KAMAResult(
        kama=kama,
        kama_direction=1,
        kama_percentage_change=0.5,
        kama_bull=True,
        kama_bear=False,
        kama_sideways=False,
        ma50=100.0,
        ma100=100.0,
        ma200=100.0,
    )


def make_position(
    direction: str,
) -> OpenPosition:

    return OpenPosition(
        direction=direction,
        entry_timestamp=1,
        entry_price=100.0,
        quantity=1,
    )


def main() -> None:

    print("=" * 78)
    print("KUNAL QUANT — KAMA EXIT ENGINE TEST V2")
    print("=" * 78)

    evaluator = KAMAExitEvaluator()

    passed = 0

    # ---------------------------------------------------------
    # Test 1 — LONG close above KAMA → HOLD
    # ---------------------------------------------------------

    result = evaluator.evaluate(
        position=make_position("LONG"),
        timestamp=2,
        close_price=105.0,
        indicator_data=make_kama_result(100.0),
    )

    assert result.should_exit is False
    assert result.reason == ExitReason.MANUAL

    print("PASS | LONG above KAMA → HOLD")
    passed += 1

    # ---------------------------------------------------------
    # Test 2 — LONG close below KAMA → EXIT
    # ---------------------------------------------------------

    result = evaluator.evaluate(
        position=make_position("LONG"),
        timestamp=2,
        close_price=95.0,
        indicator_data=make_kama_result(100.0),
    )

    assert result.should_exit is True
    assert result.reason == ExitReason.KAMA_LONG_CLOSE_BELOW

    print("PASS | LONG below KAMA → EXIT")
    passed += 1

    # ---------------------------------------------------------
    # Test 3 — LONG close equal KAMA → HOLD
    # ---------------------------------------------------------

    result = evaluator.evaluate(
        position=make_position("LONG"),
        timestamp=2,
        close_price=100.0,
        indicator_data=make_kama_result(100.0),
    )

    assert result.should_exit is False

    print("PASS | LONG equal KAMA → HOLD")
    passed += 1

    # ---------------------------------------------------------
    # Test 4 — SHORT close below KAMA → HOLD
    # ---------------------------------------------------------

    result = evaluator.evaluate(
        position=make_position("SHORT"),
        timestamp=2,
        close_price=95.0,
        indicator_data=make_kama_result(100.0),
    )

    assert result.should_exit is False
    assert result.reason == ExitReason.MANUAL

    print("PASS | SHORT below KAMA → HOLD")
    passed += 1

    # ---------------------------------------------------------
    # Test 5 — SHORT close above KAMA → EXIT
    # ---------------------------------------------------------

    result = evaluator.evaluate(
        position=make_position("SHORT"),
        timestamp=2,
        close_price=105.0,
        indicator_data=make_kama_result(100.0),
    )

    assert result.should_exit is True
    assert result.reason == ExitReason.KAMA_SHORT_CLOSE_ABOVE

    print("PASS | SHORT above KAMA → EXIT")
    passed += 1

    # ---------------------------------------------------------
    # Test 6 — SHORT equal KAMA → HOLD
    # ---------------------------------------------------------

    result = evaluator.evaluate(
        position=make_position("SHORT"),
        timestamp=2,
        close_price=100.0,
        indicator_data=make_kama_result(100.0),
    )

    assert result.should_exit is False

    print("PASS | SHORT equal KAMA → HOLD")
    passed += 1

    # ---------------------------------------------------------
    # Test 7 — KAMA unavailable → HOLD
    # ---------------------------------------------------------

    result = evaluator.evaluate(
        position=make_position("LONG"),
        timestamp=2,
        close_price=95.0,
        indicator_data=make_kama_result(None),
    )

    assert result.should_exit is False
    assert result.reason == ExitReason.MANUAL

    print("PASS | KAMA unavailable → HOLD")
    passed += 1

    print()
    print("Total :", 7)
    print("Passed:", passed)
    print("Failed:", 7 - passed)

    assert passed == 7

    print()
    print("ALL KAMA EXIT ENGINE TESTS PASSED")


if __name__ == "__main__":
    main()