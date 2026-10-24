"""Generic exit evaluator interface."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from backtest.models import ExitReason, OpenPosition


@dataclass(frozen=True)
class ExitEvaluation:
    """Result returned by an exit evaluator."""

    should_exit: bool
    reason: ExitReason


class ExitEvaluator(Protocol):
    """Protocol for strategy-specific exit evaluators."""

    def evaluate(
        self,
        position: OpenPosition,
        timestamp: int,
        close_price: float,
        indicator_data: object,
    ) -> ExitEvaluation:
        ...