import unittest
from enum import Enum
from types import SimpleNamespace
from unittest.mock import patch

from indicators.ktmi.universal import OHLCData
from paper_trading.engine import PaperEngineConfig, PaperStrategyId
from paper_trading.signals import evaluate_latest_paper_signals
from strategies.ktmi_trigger_strategy import (
    KTMITriggerEvent,
    TriggerDirection,
    TriggerStrategyId,
)


def bar(timestamp, close=100.0):
    return SimpleNamespace(
        timestamp=timestamp,
        open=close,
        high=close + 1,
        low=close - 1,
        close=close,
    )


class PaperSignalRouterTests(unittest.TestCase):
    @patch("paper_trading.signals.evaluate_series")
    @patch("paper_trading.signals.evaluate_ktmi_trigger_strategies")
    @patch("paper_trading.signals.calculate_ktmi")
    def test_maps_latest_strategy_a_and_b_events(
        self, calculate_ktmi, evaluate_triggers, evaluate_series
    ):
        module_no_entry = SimpleNamespace(
            decision=SimpleNamespace(
                action=SimpleNamespace(value="NO_ENTRY"),
                direction=None,
                reason=SimpleNamespace(value="NO_SIGNAL"),
            )
        )
        evaluate_series.return_value = [module_no_entry, module_no_entry]
        module_values = SimpleNamespace(speed=0.0)
        module_result = SimpleNamespace(
            momentum=module_values,
            long_momentum=module_values,
            short_momentum=module_values,
        )
        calculate_ktmi.return_value = [module_result, module_result]
        evaluate_triggers.return_value = [
            KTMITriggerEvent(
                strategy_id=TriggerStrategyId.LONG_SHORT_SPEED,
                direction=TriggerDirection.LONG,
                previous_value=0.4,
                current_value=0.6,
                trigger_value=0.5,
                index=1,
                timestamp=160,
            ),
            KTMITriggerEvent(
                strategy_id=TriggerStrategyId.MOMENTUM_ONLY,
                direction=TriggerDirection.SHORT,
                previous_value=0.0,
                current_value=-0.6,
                trigger_value=-0.49,
                index=1,
                timestamp=160,
            ),
        ]
        config = PaperEngineConfig(module_confluence_enabled=False)

        signals = evaluate_latest_paper_signals(
            [bar(100), bar(160)],
            paper_config=config,
        )

        self.assertEqual(
            [(s.strategy_id, s.direction, s.timestamp) for s in signals],
            [
                (PaperStrategyId.STRATEGY_A, "LONG", 160),
                (PaperStrategyId.STRATEGY_B, "SHORT", 160),
            ],
        )
        self.assertEqual([s.index for s in signals], [1, 1])

    @patch("paper_trading.signals.evaluate_series")
    @patch("paper_trading.signals.evaluate_ktmi_trigger_strategies")
    @patch("paper_trading.signals.calculate_ktmi")
    def test_disabled_strategy_signal_is_filtered(
        self, calculate_ktmi, evaluate_triggers, evaluate_series
    ):
        module_values = SimpleNamespace(speed=0.0)
        result = SimpleNamespace(
            momentum=module_values,
            long_momentum=module_values,
            short_momentum=module_values,
        )
        calculate_ktmi.return_value = [result, result]
        evaluate_triggers.return_value = [
            KTMITriggerEvent(
                strategy_id=TriggerStrategyId.LONG_SHORT_SPEED,
                direction=TriggerDirection.LONG,
                previous_value=0.4,
                current_value=0.6,
                trigger_value=0.5,
                index=1,
                timestamp=160,
            )
        ]
        evaluate_series.return_value = []
        config = PaperEngineConfig(
            strategy_a_enabled=False,
            module_confluence_enabled=False,
        )

        signals = evaluate_latest_paper_signals(
            [bar(100), bar(160)],
            paper_config=config,
        )
        self.assertEqual(signals, [])

    @patch("paper_trading.signals.evaluate_series")
    def test_module_confluence_decision_is_routed(self, evaluate_series):
        evaluate_series.return_value = [
            SimpleNamespace(
                decision=SimpleNamespace(
                    action=SimpleNamespace(value="LONG"),
                    direction=SimpleNamespace(value="LONG"),
                    reason=SimpleNamespace(value="LONG_SIGNAL"),
                )
            )
        ]

        signals = evaluate_latest_paper_signals([bar(100)])
        self.assertEqual(len(signals), 1)
        self.assertEqual(signals[0].strategy_id, PaperStrategyId.MODULE_CONFLUENCE)
        self.assertEqual(signals[0].direction, "LONG")
        self.assertEqual(signals[0].reason, "LONG_SIGNAL")

    def test_out_of_order_bars_are_rejected(self):
        with self.assertRaises(ValueError):
            evaluate_latest_paper_signals([bar(160), bar(100)])

    @patch("paper_trading.signals.evaluate_series")
    def test_single_bar_skips_crossing_strategies(self, evaluate_series):
        evaluate_series.return_value = []
        signals = evaluate_latest_paper_signals(
            [bar(100)],
            paper_config=PaperEngineConfig(module_confluence_enabled=False),
        )
        self.assertEqual(signals, [])

    def test_empty_history_returns_no_signals(self):
        self.assertEqual(evaluate_latest_paper_signals([]), [])


if __name__ == "__main__":
    unittest.main()
