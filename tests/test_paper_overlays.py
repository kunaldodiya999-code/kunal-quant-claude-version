"""Chart data for the entry / stop / target box and the long and short entry markers."""
import json
import tempfile
import unittest
from pathlib import Path

from paper_trading.buyer_lifecycle import BuyerLifecycleConfig, BuyerOptionTradeLifecycle
from paper_trading.engine import PaperStrategyId, PaperTradingEngine
from paper_trading.exit_manager import ExitManager
from paper_trading.overlays import trade_overlay, trade_overlays
from paper_trading.recorder import PaperTradeRecorder
from paper_trading.tsl_shadow_lab import OptionCandle, TslShadowLab

A, B = PaperStrategyId.STRATEGY_A, PaperStrategyId.STRATEGY_B
T0 = 1_792_000_000
CE, PE = "NSE:NIFTY2610024500CE", "NSE:NIFTY2610024500PE"
CLIMB = [(99 + i, 101 + i, 98 + i, 100 + i) for i in range(1, 13)]


class OverlayTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        lifecycle = BuyerOptionTradeLifecycle(BuyerLifecycleConfig(allocation=25_000.0, lot_size=65))
        self.engine = PaperTradingEngine(recorder=PaperTradeRecorder(self.dir), lifecycle=lifecycle)
        self.manager = ExitManager(self.engine, TslShadowLab(self.dir / "lab"), journal_dir=self.dir)

    def tearDown(self):
        self._tmp.cleanup()

    def open(self, strategy, direction, symbol, price=100.0, ts=T0):
        return self.engine.open_position(strategy_id=strategy, direction=direction, symbol=symbol,
                                         entry_price=price, timestamp=ts)

    def test_long_entry_marker_and_box_levels_for_a_bought_call(self):
        self.open(A, "LONG", CE)
        o = trade_overlays(self.engine, self.manager)[0]
        self.assertEqual(o["marker"], {"time": T0, "side": "LONG", "label": "LONG CE"})
        self.assertEqual((o["status"], o["entry_price"], o["lots"], o["quantity"]), ("OPEN", 100.0, 3, 195))
        self.assertAlmostEqual(o["initial_stop"], 70.0)        # 30% below the premium paid
        self.assertAlmostEqual(o["target"], 160.0)             # 2R partial target (owner default)
        self.assertEqual(o["reward_to_risk"], 2.0)
        self.assertAlmostEqual(o["max_loss_at_initial_stop"], 30.0 * 195)
        self.assertIsNone(o["exit_time"])

    def test_short_entry_marker_is_a_bought_put_with_stop_below_and_target_above(self):
        self.open(B, "SHORT", PE)
        o = trade_overlay(self.engine.open_trade(B), self.manager)
        self.assertEqual(o["marker"]["side"], "SHORT")
        self.assertEqual((o["instrument"], o["marker"]["label"]), ("PE", "SHORT PE"))
        self.assertLess(o["initial_stop"], o["entry_price"])
        self.assertGreater(o["target"], o["entry_price"])

    def test_effective_stop_is_the_tighter_of_initial_and_the_option_chart_tsl(self):
        self.manager.store.update(tsl_timeframe="1", partial_enabled=False, tsl_source="OPTION")
        self.open(A, "LONG", CE)
        for i, (op, hi, lo, cl) in enumerate(CLIMB, 1):
            self.manager.on_option_candle(symbol=CE, candle=OptionCandle(T0 + 60 * i, op, hi, lo, cl))
        o = trade_overlay(self.engine.open_trade(A), self.manager)
        self.assertEqual(o["status"], "OPEN")
        # everget Chandelier: highest close of 9 candles 112 - 1.5 x ATR 3 = 107.5
        self.assertAlmostEqual(o["tsl"]["tsl_stop"], 107.5)
        self.assertAlmostEqual(o["effective_stop"], 107.5)      # above the initial 70
        self.assertAlmostEqual(o["initial_stop"], 70.0)
        self.assertEqual(len(o["tsl_comparison"]), 6)            # every method shown side by side

    def test_closed_trade_carries_its_exit_for_the_box_right_edge(self):
        self.open(A, "LONG", CE)
        self.engine.force_close(A, timestamp=T0 + 600, price=130.0)
        o = trade_overlays(self.engine, self.manager)[0]
        self.assertEqual((o["status"], o["exit_time"], o["exit_price"]), ("CLOSED", T0 + 600, 130.0))
        self.assertIsNone(o["effective_stop"])
        self.assertAlmostEqual(o["gross_pnl"], 30.0 * 195)

    def test_overlays_are_oldest_first_and_json_serialisable(self):
        self.open(B, "SHORT", PE, ts=T0 + 300)
        self.open(A, "LONG", CE, ts=T0)
        items = trade_overlays(self.engine, self.manager)
        self.assertEqual([i["entry_time"] for i in items], [T0, T0 + 300])
        json.dumps(items)

    def test_works_without_an_exit_manager(self):
        self.open(A, "LONG", CE)
        o = trade_overlays(self.engine)[0]
        self.assertEqual((o["tsl"], o["tsl_comparison"]), ({}, {}))
        self.assertAlmostEqual(o["effective_stop"], 70.0)


if __name__ == "__main__":
    unittest.main()
