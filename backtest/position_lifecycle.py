"""
KUNAL QUANT
Position Lifecycle V1

Purpose
-------
Controls whether a new strategy signal is allowed to create
a position while another position is active.

This is deliberately separate from:

    KTMI
    Strategy A/B
    Risk Engine
    Trade Management
    Backtest Engine

The layer only decides:

    ENTER
    IGNORE

Strategy A and Strategy B remain independent.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


# =====================================================================
# ENUMS
# =====================================================================


class SignalAction(str, Enum):

    ENTER = "ENTER"

    IGNORE = "IGNORE"


# =====================================================================
# CONFIG
# =====================================================================


@dataclass(frozen=True)
class PositionLifecycleConfig:

    # Allow only one position for each strategy at a time.
    one_position_per_strategy: bool = True

    # Do not allow the same strategy to stack another position.
    allow_same_strategy_reentry: bool = False

    # Different strategies may independently hold positions.
    allow_different_strategy_positions: bool = True

    # Opposite signal from the same strategy does not automatically
    # reverse the existing position.
    allow_same_strategy_reversal: bool = False


DEFAULT_POSITION_LIFECYCLE_CONFIG = (
    PositionLifecycleConfig()
)


# =====================================================================
# ACTIVE POSITION
# =====================================================================


@dataclass(frozen=True)
class ActivePosition:

    strategy_id: str

    direction: str

    symbol: str


# =====================================================================
# DECISION
# =====================================================================


@dataclass(frozen=True)
class PositionDecision:

    action: SignalAction

    reason: str


# =====================================================================
# DECISION ENGINE
# =====================================================================


def evaluate_signal(
    *,
    strategy_id: str,
    direction: str,
    symbol: str,
    active_positions: list[ActivePosition],
    config: PositionLifecycleConfig = (
        DEFAULT_POSITION_LIFECYCLE_CONFIG
    ),
) -> PositionDecision:

    strategy_id = strategy_id.upper()
    direction = direction.upper()

    # -------------------------------------------------------------
    # Check positions belonging to this strategy
    # -------------------------------------------------------------

    same_strategy = [

        position

        for position in active_positions

        if position.strategy_id.upper()
        == strategy_id
    ]

    # -------------------------------------------------------------
    # Same strategy already has a position
    # -------------------------------------------------------------

    if same_strategy:

        existing = same_strategy[0]

        # Same direction
        if existing.direction.upper() == direction:

            if config.allow_same_strategy_reentry:

                return PositionDecision(
                    action=SignalAction.ENTER,
                    reason=(
                        "SAME_STRATEGY_REENTRY_ALLOWED"
                    ),
                )

            return PositionDecision(
                action=SignalAction.IGNORE,
                reason=(
                    "SAME_STRATEGY_POSITION_ALREADY_OPEN"
                ),
            )

        # Opposite direction
        if config.allow_same_strategy_reversal:

            return PositionDecision(
                action=SignalAction.ENTER,
                reason=(
                    "SAME_STRATEGY_REVERSAL_ALLOWED"
                ),
            )

        return PositionDecision(
            action=SignalAction.IGNORE,
            reason=(
                "SAME_STRATEGY_OPPOSITE_POSITION_ALREADY_OPEN"
            ),
        )

    # -------------------------------------------------------------
    # Different strategy already has positions
    # -------------------------------------------------------------

    if active_positions:

        if config.allow_different_strategy_positions:

            return PositionDecision(
                action=SignalAction.ENTER,
                reason=(
                    "DIFFERENT_STRATEGY_POSITION_ALLOWED"
                ),
            )

        return PositionDecision(
            action=SignalAction.IGNORE,
            reason=(
                "ANOTHER_STRATEGY_POSITION_ALREADY_OPEN"
            ),
        )

    # -------------------------------------------------------------
    # No active position
    # -------------------------------------------------------------

    return PositionDecision(
        action=SignalAction.ENTER,
        reason="NO_ACTIVE_POSITION",
    )