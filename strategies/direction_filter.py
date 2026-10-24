"""
Manual directional filter for Kunal Quant.

This module does not modify KTMI calculations.

It controls whether a strategy is allowed to take:
    BOTH directions
    LONG only
    SHORT only

The filter returns an explicit decision and reason so that
Backtest, Paper, and Live modes can audit why a signal was
accepted or blocked.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Direction(str, Enum):
    """Trading direction."""

    LONG = "LONG"
    SHORT = "SHORT"


class DirectionMode(str, Enum):
    """Allowed trading-direction modes."""

    BOTH = "BOTH"
    LONG_ONLY = "LONG_ONLY"
    SHORT_ONLY = "SHORT_ONLY"


class DirectionDecision(str, Enum):
    """Result of applying the directional filter."""

    ALLOW = "ALLOW"
    BLOCK = "BLOCK"


class DirectionReason(str, Enum):
    """Explicit reason for the directional decision."""

    BOTH_DIRECTIONS_ENABLED = "BOTH_DIRECTIONS_ENABLED"
    LONG_DIRECTION_ALLOWED = "LONG_DIRECTION_ALLOWED"
    SHORT_DIRECTION_ALLOWED = "SHORT_DIRECTION_ALLOWED"

    LONG_DIRECTION_DISABLED = "LONG_DIRECTION_DISABLED"
    SHORT_DIRECTION_DISABLED = "SHORT_DIRECTION_DISABLED"


@dataclass(frozen=True)
class DirectionFilterResult:
    """Result returned by the directional filter."""

    direction: Direction
    mode: DirectionMode
    decision: DirectionDecision
    reason: DirectionReason

    @property
    def allowed(self) -> bool:
        """Return True when the direction is allowed."""

        return self.decision == DirectionDecision.ALLOW


def apply_direction_filter(
    direction: Direction,
    mode: DirectionMode = DirectionMode.BOTH,
) -> DirectionFilterResult:
    """
    Apply the configured manual directional bias.

    Parameters
    ----------
    direction:
        Requested trading direction.

    mode:
        User-selected directional mode.

    Returns
    -------
    DirectionFilterResult
        Explicit allow/block decision with reason.
    """

    if mode == DirectionMode.BOTH:

        return DirectionFilterResult(
            direction=direction,
            mode=mode,
            decision=DirectionDecision.ALLOW,
            reason=DirectionReason.BOTH_DIRECTIONS_ENABLED,
        )

    if (
        mode == DirectionMode.LONG_ONLY
        and direction == Direction.LONG
    ):

        return DirectionFilterResult(
            direction=direction,
            mode=mode,
            decision=DirectionDecision.ALLOW,
            reason=DirectionReason.LONG_DIRECTION_ALLOWED,
        )

    if (
        mode == DirectionMode.SHORT_ONLY
        and direction == Direction.SHORT
    ):

        return DirectionFilterResult(
            direction=direction,
            mode=mode,
            decision=DirectionDecision.ALLOW,
            reason=DirectionReason.SHORT_DIRECTION_ALLOWED,
        )

    if direction == Direction.LONG:

        return DirectionFilterResult(
            direction=direction,
            mode=mode,
            decision=DirectionDecision.BLOCK,
            reason=DirectionReason.LONG_DIRECTION_DISABLED,
        )

    return DirectionFilterResult(
        direction=direction,
        mode=mode,
        decision=DirectionDecision.BLOCK,
        reason=DirectionReason.SHORT_DIRECTION_DISABLED,
    )


__all__ = [
    "Direction",
    "DirectionDecision",
    "DirectionFilterResult",
    "DirectionMode",
    "DirectionReason",
    "apply_direction_filter",
]