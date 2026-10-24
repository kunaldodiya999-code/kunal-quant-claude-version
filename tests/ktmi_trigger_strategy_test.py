"""
Kunal Quant — KTMI Trigger Strategy Tests

Tests the NEW strategy trigger layer only.

The existing KTMI calculation engine is deliberately not modified
or retested here.
"""

from __future__ import annotations

from strategies.ktmi_trigger_strategy import (
    KTMITriggerStrategyConfig,
    TriggerDirection,
    TriggerStrategyId,
    crossed_down,
    crossed_up,
    evaluate_strategy_a,
    evaluate_strategy_b,
    evaluate_ktmi_trigger_strategies,
)


# =====================================================================
# CONFIG
# =====================================================================


CONFIG = KTMITriggerStrategyConfig(
    long_short_speed_enabled=True,
    long_speed_trigger=0.50,
    short_speed_trigger=0.50,
    momentum_only_enabled=True,
    momentum_long_trigger=0.49,
    momentum_short_trigger=-0.49,
)


# =====================================================================
# BASIC CROSSING TESTS
# =====================================================================


def test_crossed_up():

    assert crossed_up(
        0.49,
        0.50,
        0.50,
    )

    assert crossed_up(
        0.49,
        0.51,
        0.50,
    )

    assert not crossed_up(
        0.50,
        0.55,
        0.50,
    )

    assert not crossed_up(
        0.55,
        0.50,
        0.50,
    )

    print("PASS | crossed_up")


def test_crossed_down():

    assert crossed_down(
        -0.48,
        -0.49,
        -0.49,
    )

    assert crossed_down(
        -0.48,
        -0.50,
        -0.49,
    )

    assert not crossed_down(
        -0.49,
        -0.60,
        -0.49,
    )

    assert not crossed_down(
        -0.60,
        -0.49,
        -0.49,
    )

    print("PASS | crossed_down")


# =====================================================================
# STRATEGY A — LONG SPEED
# =====================================================================


def test_strategy_a_long_cross():

    events = evaluate_strategy_a(
        previous_long_speed=0.49,
        current_long_speed=0.50,
        previous_short_speed=0.20,
        current_short_speed=0.20,
        config=CONFIG,
    )

    assert len(events) == 1

    event = events[0]

    assert event.strategy_id == TriggerStrategyId.LONG_SHORT_SPEED
    assert event.direction == TriggerDirection.LONG
    assert event.previous_value == 0.49
    assert event.current_value == 0.50
    assert event.trigger_value == 0.50

    print("PASS | Strategy A LONG crossing")


def test_strategy_a_long_no_repeat():

    events = evaluate_strategy_a(
        previous_long_speed=0.50,
        current_long_speed=0.55,
        previous_short_speed=0.20,
        current_short_speed=0.20,
        config=CONFIG,
    )

    assert len(events) == 0

    print("PASS | Strategy A LONG no repeated signal")


def test_strategy_a_long_rearm():

    # Cross below first.
    events_reset = evaluate_strategy_a(
        previous_long_speed=0.70,
        current_long_speed=0.49,
        previous_short_speed=0.20,
        current_short_speed=0.20,
        config=CONFIG,
    )

    assert len(events_reset) == 0

    # Cross upward again.
    events = evaluate_strategy_a(
        previous_long_speed=0.49,
        current_long_speed=0.50,
        previous_short_speed=0.20,
        current_short_speed=0.20,
        config=CONFIG,
    )

    assert len(events) == 1
    assert events[0].direction == TriggerDirection.LONG

    print("PASS | Strategy A LONG re-arm")


# =====================================================================
# STRATEGY A — SHORT SPEED
# =====================================================================


def test_strategy_a_short_cross():

    events = evaluate_strategy_a(
        previous_long_speed=0.20,
        current_long_speed=0.20,
        previous_short_speed=0.49,
        current_short_speed=0.50,
        config=CONFIG,
    )

    assert len(events) == 1

    event = events[0]

    assert event.strategy_id == TriggerStrategyId.LONG_SHORT_SPEED
    assert event.direction == TriggerDirection.SHORT
    assert event.previous_value == 0.49
    assert event.current_value == 0.50
    assert event.trigger_value == 0.50

    print("PASS | Strategy A SHORT crossing")


def test_strategy_a_short_no_repeat():

    events = evaluate_strategy_a(
        previous_long_speed=0.20,
        current_long_speed=0.20,
        previous_short_speed=0.50,
        current_short_speed=0.60,
        config=CONFIG,
    )

    assert len(events) == 0

    print("PASS | Strategy A SHORT no repeated signal")


# =====================================================================
# STRATEGY B — MOMENTUM LONG
# =====================================================================


def test_strategy_b_long_cross():

    events = evaluate_strategy_b(
        previous_momentum_speed=0.48,
        current_momentum_speed=0.49,
        config=CONFIG,
    )

    assert len(events) == 1

    event = events[0]

    assert event.strategy_id == TriggerStrategyId.MOMENTUM_ONLY
    assert event.direction == TriggerDirection.LONG
    assert event.previous_value == 0.48
    assert event.current_value == 0.49
    assert event.trigger_value == 0.49

    print("PASS | Strategy B LONG crossing")


def test_strategy_b_long_no_repeat():

    events = evaluate_strategy_b(
        previous_momentum_speed=0.49,
        current_momentum_speed=0.60,
        config=CONFIG,
    )

    assert len(events) == 0

    print("PASS | Strategy B LONG no repeated signal")


def test_strategy_b_long_rearm():

    # Move back below trigger.
    events_reset = evaluate_strategy_b(
        previous_momentum_speed=0.60,
        current_momentum_speed=0.48,
        config=CONFIG,
    )

    assert len(events_reset) == 0

    # Cross again.
    events = evaluate_strategy_b(
        previous_momentum_speed=0.48,
        current_momentum_speed=0.49,
        config=CONFIG,
    )

    assert len(events) == 1
    assert events[0].direction == TriggerDirection.LONG

    print("PASS | Strategy B LONG re-arm")


# =====================================================================
# STRATEGY B — MOMENTUM SHORT
# =====================================================================


def test_strategy_b_short_cross():

    events = evaluate_strategy_b(
        previous_momentum_speed=-0.48,
        current_momentum_speed=-0.49,
        config=CONFIG,
    )

    assert len(events) == 1

    event = events[0]

    assert event.strategy_id == TriggerStrategyId.MOMENTUM_ONLY
    assert event.direction == TriggerDirection.SHORT
    assert event.previous_value == -0.48
    assert event.current_value == -0.49
    assert event.trigger_value == -0.49

    print("PASS | Strategy B SHORT crossing")


def test_strategy_b_short_no_repeat():

    events = evaluate_strategy_b(
        previous_momentum_speed=-0.49,
        current_momentum_speed=-0.60,
        config=CONFIG,
    )

    assert len(events) == 0

    print("PASS | Strategy B SHORT no repeated signal")


def test_strategy_b_short_rearm():

    # Move back above trigger.
    events_reset = evaluate_strategy_b(
        previous_momentum_speed=-0.60,
        current_momentum_speed=-0.48,
        config=CONFIG,
    )

    assert len(events_reset) == 0

    # Cross again.
    events = evaluate_strategy_b(
        previous_momentum_speed=-0.48,
        current_momentum_speed=-0.49,
        config=CONFIG,
    )

    assert len(events) == 1
    assert events[0].direction == TriggerDirection.SHORT

    print("PASS | Strategy B SHORT re-arm")


# =====================================================================
# SAME CANDLE — BOTH STRATEGIES
# =====================================================================


def test_both_strategies_same_candle():

    events = evaluate_ktmi_trigger_strategies(
        previous_momentum_speed=0.48,
        current_momentum_speed=0.49,
        previous_long_speed=0.49,
        current_long_speed=0.50,
        previous_short_speed=0.20,
        current_short_speed=0.20,
        config=CONFIG,
    )

    assert len(events) == 2

    strategy_ids = {
        event.strategy_id
        for event in events
    }

    assert TriggerStrategyId.LONG_SHORT_SPEED in strategy_ids
    assert TriggerStrategyId.MOMENTUM_ONLY in strategy_ids

    directions = {
        event.direction
        for event in events
    }

    assert TriggerDirection.LONG in directions

    print("PASS | Strategy A + B can trigger independently")


# =====================================================================
# STRATEGY DISABLE TEST
# =====================================================================


def test_strategy_disable():

    disabled = KTMITriggerStrategyConfig(
        long_short_speed_enabled=False,
        momentum_only_enabled=False,
    )

    events = evaluate_ktmi_trigger_strategies(
        previous_momentum_speed=0.48,
        current_momentum_speed=0.49,
        previous_long_speed=0.49,
        current_long_speed=0.50,
        previous_short_speed=0.49,
        current_short_speed=0.50,
        config=disabled,
    )

    assert len(events) == 0

    print("PASS | Strategy enable/disable")


# =====================================================================
# MAIN
# =====================================================================


def main():

    print()
    print("=" * 78)
    print("KUNAL QUANT — KTMI TRIGGER STRATEGY TEST")
    print("=" * 78)

    test_crossed_up()
    test_crossed_down()

    test_strategy_a_long_cross()
    test_strategy_a_long_no_repeat()
    test_strategy_a_long_rearm()

    test_strategy_a_short_cross()
    test_strategy_a_short_no_repeat()

    test_strategy_b_long_cross()
    test_strategy_b_long_no_repeat()
    test_strategy_b_long_rearm()

    test_strategy_b_short_cross()
    test_strategy_b_short_no_repeat()
    test_strategy_b_short_rearm()

    test_both_strategies_same_candle()

    test_strategy_disable()

    print()
    print("=" * 78)
    print("ALL KTMI TRIGGER STRATEGY TESTS PASSED")
    print("=" * 78)


if __name__ == "__main__":
    main()