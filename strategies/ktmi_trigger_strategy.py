"""
Kunal Quant — KTMI Trigger Strategy

Purpose:
    Convert the already-calculated KTMI Speed values into
    independent strategy entry events.

IMPORTANT:
    - Does NOT modify KTMI calculations.
    - Does NOT modify indicators/ktmi/signals.py.
    - Does NOT use the existing module/confluence strategy logic.
    - Uses TradingView-style crossing semantics.
    - Generates one event per crossing.
    - Re-arms only after the Speed crosses back through the trigger.

STRATEGY A
----------
Long Speed crosses UP through +0.50 -> LONG
Short Speed crosses UP through +0.50 -> SHORT

STRATEGY B
----------
Momentum Speed crosses UP through +0.49 -> LONG
Momentum Speed crosses DOWN through -0.49 -> SHORT
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional


# =====================================================================
# ENUMS
# =====================================================================


class TriggerStrategyId(str, Enum):
    LONG_SHORT_SPEED = "KTMI_LONG_SHORT_SPEED"
    MOMENTUM_ONLY = "KTMI_MOMENTUM_ONLY"


class TriggerDirection(str, Enum):
    LONG = "LONG"
    SHORT = "SHORT"


# =====================================================================
# CONFIGURATION
# =====================================================================


@dataclass(frozen=True)
class KTMITriggerStrategyConfig:
    """
    Configuration for the two independent KTMI trigger strategies.
    """

    # ---------------------------------------------------------------
    # Strategy A
    # ---------------------------------------------------------------

    long_short_speed_enabled: bool = True

    long_speed_trigger: float = 0.50
    short_speed_trigger: float = 0.50

    # ---------------------------------------------------------------
    # Strategy B
    # ---------------------------------------------------------------

    momentum_only_enabled: bool = True

    momentum_long_trigger: float = 0.49
    momentum_short_trigger: float = -0.49


DEFAULT_KTMI_TRIGGER_CONFIG = KTMITriggerStrategyConfig()


# =====================================================================
# SIGNAL EVENT
# =====================================================================


@dataclass(frozen=True)
class KTMITriggerEvent:
    """
    One independent KTMI strategy trigger event.
    """

    strategy_id: TriggerStrategyId
    direction: TriggerDirection

    previous_value: float
    current_value: float
    trigger_value: float

    index: int = -1
    timestamp: Optional[int] = None

    @property
    def strategy_name(self) -> str:
        return self.strategy_id.value

    @property
    def direction_name(self) -> str:
        return self.direction.value


# =====================================================================
# CROSSING HELPERS
# =====================================================================


def crossed_up(
    previous_value: Optional[float],
    current_value: Optional[float],
    trigger: float,
) -> bool:
    """
    TradingView-style upward crossing.

    The current value may equal the trigger.

    Example:
        0.49 -> 0.50  = TRUE
        0.49 -> 0.51  = TRUE
        0.50 -> 0.55  = FALSE
        0.55 -> 0.50  = FALSE

    Previous value must be strictly below the trigger.
    """

    if previous_value is None or current_value is None:
        return False

    return (
        previous_value < trigger
        and current_value >= trigger
    )


def crossed_down(
    previous_value: Optional[float],
    current_value: Optional[float],
    trigger: float,
) -> bool:
    """
    TradingView-style downward crossing.

    The current value may equal the trigger.

    Example:
        -0.48 -> -0.49 = TRUE
        -0.48 -> -0.50 = TRUE
        -0.49 -> -0.60 = FALSE
        -0.60 -> -0.49 = FALSE

    Previous value must be strictly above the trigger.
    """

    if previous_value is None or current_value is None:
        return False

    return (
        previous_value > trigger
        and current_value <= trigger
    )


# =====================================================================
# SINGLE STRATEGY A EVALUATION
# =====================================================================


def evaluate_strategy_a(
    previous_long_speed: Optional[float],
    current_long_speed: Optional[float],
    previous_short_speed: Optional[float],
    current_short_speed: Optional[float],
    config: KTMITriggerStrategyConfig = DEFAULT_KTMI_TRIGGER_CONFIG,
    *,
    index: int = -1,
    timestamp: Optional[int] = None,
) -> list[KTMITriggerEvent]:
    """
    Evaluate Strategy A.

    LONG:
        Long Speed crosses UP through +0.50.

    SHORT:
        Short Speed crosses UP through +0.50.

    Both can theoretically trigger on the same candle.
    """

    if not config.long_short_speed_enabled:
        return []

    events: list[KTMITriggerEvent] = []

    # ---------------------------------------------------------------
    # LONG
    # ---------------------------------------------------------------

    if crossed_up(
        previous_long_speed,
        current_long_speed,
        config.long_speed_trigger,
    ):
        events.append(
            KTMITriggerEvent(
                strategy_id=TriggerStrategyId.LONG_SHORT_SPEED,
                direction=TriggerDirection.LONG,
                previous_value=float(previous_long_speed),
                current_value=float(current_long_speed),
                trigger_value=config.long_speed_trigger,
                index=index,
                timestamp=timestamp,
            )
        )

    # ---------------------------------------------------------------
    # SHORT
    # ---------------------------------------------------------------

    if crossed_up(
        previous_short_speed,
        current_short_speed,
        config.short_speed_trigger,
    ):
        events.append(
            KTMITriggerEvent(
                strategy_id=TriggerStrategyId.LONG_SHORT_SPEED,
                direction=TriggerDirection.SHORT,
                previous_value=float(previous_short_speed),
                current_value=float(current_short_speed),
                trigger_value=config.short_speed_trigger,
                index=index,
                timestamp=timestamp,
            )
        )

    return events


# =====================================================================
# SINGLE STRATEGY B EVALUATION
# =====================================================================


def evaluate_strategy_b(
    previous_momentum_speed: Optional[float],
    current_momentum_speed: Optional[float],
    config: KTMITriggerStrategyConfig = DEFAULT_KTMI_TRIGGER_CONFIG,
    *,
    index: int = -1,
    timestamp: Optional[int] = None,
) -> list[KTMITriggerEvent]:
    """
    Evaluate Strategy B.

    LONG:
        Momentum Speed crosses UP through +0.49.

    SHORT:
        Momentum Speed crosses DOWN through -0.49.
    """

    if not config.momentum_only_enabled:
        return []

    events: list[KTMITriggerEvent] = []

    # ---------------------------------------------------------------
    # LONG
    # ---------------------------------------------------------------

    if crossed_up(
        previous_momentum_speed,
        current_momentum_speed,
        config.momentum_long_trigger,
    ):
        events.append(
            KTMITriggerEvent(
                strategy_id=TriggerStrategyId.MOMENTUM_ONLY,
                direction=TriggerDirection.LONG,
                previous_value=float(previous_momentum_speed),
                current_value=float(current_momentum_speed),
                trigger_value=config.momentum_long_trigger,
                index=index,
                timestamp=timestamp,
            )
        )

    # ---------------------------------------------------------------
    # SHORT
    # ---------------------------------------------------------------

    if crossed_down(
        previous_momentum_speed,
        current_momentum_speed,
        config.momentum_short_trigger,
    ):
        events.append(
            KTMITriggerEvent(
                strategy_id=TriggerStrategyId.MOMENTUM_ONLY,
                direction=TriggerDirection.SHORT,
                previous_value=float(previous_momentum_speed),
                current_value=float(current_momentum_speed),
                trigger_value=config.momentum_short_trigger,
                index=index,
                timestamp=timestamp,
            )
        )

    return events


# =====================================================================
# COMBINED EVALUATION
# =====================================================================


def evaluate_ktmi_trigger_strategies(
    previous_momentum_speed: Optional[float],
    current_momentum_speed: Optional[float],
    previous_long_speed: Optional[float],
    current_long_speed: Optional[float],
    previous_short_speed: Optional[float],
    current_short_speed: Optional[float],
    config: KTMITriggerStrategyConfig = DEFAULT_KTMI_TRIGGER_CONFIG,
    *,
    index: int = -1,
    timestamp: Optional[int] = None,
) -> list[KTMITriggerEvent]:
    """
    Evaluate both independent KTMI strategies.

    Strategy A and Strategy B remain separate.

    If both trigger on the same candle, BOTH events are returned.
    """

    events: list[KTMITriggerEvent] = []

    events.extend(
        evaluate_strategy_a(
            previous_long_speed=previous_long_speed,
            current_long_speed=current_long_speed,
            previous_short_speed=previous_short_speed,
            current_short_speed=current_short_speed,
            config=config,
            index=index,
            timestamp=timestamp,
        )
    )

    events.extend(
        evaluate_strategy_b(
            previous_momentum_speed=previous_momentum_speed,
            current_momentum_speed=current_momentum_speed,
            config=config,
            index=index,
            timestamp=timestamp,
        )
    )

    return events