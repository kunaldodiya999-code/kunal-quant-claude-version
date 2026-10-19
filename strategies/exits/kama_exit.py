"""KAMA-based exit evaluator.

This module contains only the KAMA exit rule.

It does not:
- generate entries
- calculate KAMA
- calculate position size
- modify KTMI
- define stop loss
- define target
- define trailing stop
"""

from __future__ import annotations

from backtest.exit_evaluator import ExitEvaluation
from backtest.models import (
    ExitReason,
    OpenPosition,
)


class KAMAExitEvaluator:
    """Evaluate completed-candle KAMA exits."""

    def evaluate(
        self,
        position: OpenPosition,
        timestamp: int,
        close_price: float,
        indicator_data: object,
    ) -> ExitEvaluation:
        """Evaluate the KAMA exit condition.

        The evaluator intentionally reads the KAMA value from the
        supplied indicator result rather than recalculating KAMA.

        This keeps:
            KAMA calculation
        separate from:
            KAMA exit logic
        """

        # ---------------------------------------------------------
        # Obtain KAMA value.
        # ---------------------------------------------------------
        #
        # KAMAResult exposes:
        #
        #     .kama
        #
        # We use getattr() here so the exit evaluator remains
        # decoupled from the concrete indicator-result class.
        #

        kama = getattr(
            indicator_data,
            "kama",
            None,
        )

        # No usable KAMA value.
        if kama is None:
            return ExitEvaluation(
                should_exit=False,
                reason=ExitReason.MANUAL,
            )

        # ---------------------------------------------------------
        # LONG
        # ---------------------------------------------------------
        #
        # User's defined candidate exit rule:
        #
        # LONG / CE / BUY:
        # completed candle closes BELOW KAMA
        #

        if position.direction == "LONG":

            if close_price < kama:
                return ExitEvaluation(
                    should_exit=True,
                    reason=(
                        ExitReason
                        .KAMA_LONG_CLOSE_BELOW
                    ),
                )

            return ExitEvaluation(
                should_exit=False,
                reason=ExitReason.MANUAL,
            )

        # ---------------------------------------------------------
        # SHORT
        # ---------------------------------------------------------
        #
        # SHORT / PE / SELL:
        # completed candle closes ABOVE KAMA
        #

        if position.direction == "SHORT":

            if close_price > kama:
                return ExitEvaluation(
                    should_exit=True,
                    reason=(
                        ExitReason
                        .KAMA_SHORT_CLOSE_ABOVE
                    ),
                )

            return ExitEvaluation(
                should_exit=False,
                reason=ExitReason.MANUAL,
            )

        # ---------------------------------------------------------
        # Unsupported direction
        # ---------------------------------------------------------

        return ExitEvaluation(
            should_exit=False,
            reason=ExitReason.MANUAL,
        )