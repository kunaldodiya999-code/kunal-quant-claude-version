"""Session controls: entry window, daily loss cap, forced exit and the kill switch."""
import csv
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from backtest.option_trade_lifecycle import OptionExitReason
from paper_trading.buyer_lifecycle import BuyerLifecycleConfig, BuyerOptionTradeLifecycle
from paper_trading.controls import HaltMode, SessionControls, SessionControlsConfig
from paper_trading.coordinator import PaperExecutionCoordinator
from paper_trading.engine import PaperStrategyId, PaperTradingEngine
from paper_trading.recorder import PaperTradeRecorder
from paper_trading.recovery import restore_engine_from_journal
from paper_trading.signals import PaperSignal

IST = ZoneInfo("Asia/Kolkata")
A = PaperStrategyId.STRATEGY_A
B = PaperStrategyId.STRATEGY_B


def at(h, m, s=0, day=21):
    return int(datetime(2026, 10, day, h, m, s, tzinfo=IST).timestamp())


def make_engine(directory):
    lifecycle = BuyerOptionTradeLifecycle(BuyerLifecycleConfig(allocation=15_000.0, lot_size=65))
    return PaperTradingEngine(recorder=PaperTradeRecorder(directory), lifecycle=lifecycle)


def enter(engine, strategy=A, ts=None, price=100.0):
    return engine.open_position(strategy_id=strategy, direction="LONG",
                                symbol="NSE:NIFTY2610024500CE", entry_price=price,
                                timestamp=ts or at(10, 0))


class NeverCalledAdapter:
    def prepare_entry(self, **kwargs):
        raise AssertionError("adapter must not run when controls block the entry")


class ControlsTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_config_is_validated(self):
        with self.assertRaises(ValueError):
            SessionControlsConfig.from_hhmm("15:00", "09:45", "15:10")
        with self.assertRaises(ValueError):
            SessionControlsConfig.from_hhmm("09:45", "15:20", "15:10")
        with self.assertRaises(ValueError):
            SessionControlsConfig.from_hhmm("09:45", "15:00", "15:10", max_daily_loss=0)
        with self.assertRaises(ValueError):
            SessionControlsConfig.from_hhmm("9h45", "15:00", "15:10")

    def test_entry_window_boundaries(self):
        c = SessionControls()
        self.assertIn("Before entry window", c.entry_block_reason(at(9, 44, 59)))
        self.assertIsNone(c.entry_block_reason(at(9, 45)))
        self.assertIsNone(c.entry_block_reason(at(14, 59, 59)))
        self.assertIn("After entry cutoff", c.entry_block_reason(at(15, 0)))

    def test_kill_switch_blocks_entries_and_survives_restart(self):
        c = SessionControls(journal_dir=self.dir)
        with self.assertRaises(ValueError):
            c.halt("  ")
        c.halt("manual stop", timestamp=at(11, 0))
        self.assertIn("halted", c.entry_block_reason(at(11, 1)).lower())
        again = SessionControls(journal_dir=self.dir)          # simulated restart
        self.assertTrue(again.halted)
        self.assertEqual(again.halt_reason, "manual stop")
        again.resume(timestamp=at(11, 5))
        self.assertIsNone(SessionControls(journal_dir=self.dir).entry_block_reason(at(11, 6)))
        with (self.dir / "controls_events.csv").open(newline="", encoding="utf-8") as h:
            self.assertEqual([r["event_type"] for r in csv.DictReader(h)], ["HALT", "RESUME"])

    def test_unreadable_state_file_fails_closed(self):
        (self.dir / "controls_state.json").write_text("{not json", encoding="utf-8")
        c = SessionControls(journal_dir=self.dir)
        self.assertTrue(c.halted)
        self.assertIn("unreadable", c.entry_block_reason(at(10, 0)))

    def test_daily_loss_cap_counts_only_todays_realised_trades(self):
        engine = make_engine(self.dir)
        controls = SessionControls(SessionControlsConfig(max_daily_loss=2_000.0))
        controls.bind(engine)
        yesterday = enter(engine, ts=at(10, 0, day=20))
        engine.force_close(A, timestamp=at(11, 0, day=20), price=50.0)   # big loss, but yesterday
        self.assertIsNone(controls.entry_block_reason(at(10, 0)))
        enter(engine, ts=at(10, 0))
        engine.process_option_candle(strategy_id=A, timestamp=at(10, 1), option_high=101.0,
                                     option_low=79.0, option_close=85.0,
                                     underlying_close=24500.0, kama_value=None)   # stop: -2,600
        self.assertEqual(round(controls.realized_pnl_today(at(10, 5))), -2600)
        self.assertIn("Daily loss limit", controls.entry_block_reason(at(10, 5)))
        self.assertIsNone(SessionControls().entry_block_reason(at(10, 5)), "no cap means no block")

    def test_forced_exit_closes_open_positions_and_is_journaled(self):
        engine = make_engine(self.dir)
        controls = SessionControls(journal_dir=self.dir)
        controls.bind(engine)
        opened = enter(engine)
        self.assertEqual(controls.close_due_positions(engine, timestamp=at(15, 9), prices={A: 120.0}).closed, ())
        result = controls.close_due_positions(engine, timestamp=at(15, 10), prices={A: 120.0})
        self.assertEqual(len(result.closed), 1)
        exit_event = result.closed[0][1]
        self.assertEqual(exit_event.reason, OptionExitReason.END_OF_DATA)
        self.assertEqual(exit_event.quantity, opened.position.quantity)
        self.assertAlmostEqual(opened.position.gross_pnl, (120.0 - 100.0) * opened.position.quantity)
        self.assertIsNone(engine.open_trade(A))
        restored = make_engine(self.dir)
        restore_engine_from_journal(restored, today=datetime(2026, 10, 21, 15, 20, tzinfo=IST))
        self.assertIsNone(restored.open_trade(A), "a force-closed trade stays closed after restart")

    def test_forced_exit_reports_positions_with_no_price(self):
        engine = make_engine(self.dir)
        controls = SessionControls(journal_dir=self.dir)
        controls.bind(engine)
        enter(engine, A)
        enter(engine, B)
        result = controls.close_due_positions(engine, timestamp=at(15, 11), prices={A: 90.0})
        self.assertEqual([s for s, _ in result.closed], [A])
        self.assertEqual(result.unpriced, (B,))
        self.assertIsNotNone(engine.open_trade(B), "unpriced position stays open and is reported")

    def test_flatten_halt_closes_early_but_block_only_does_not(self):
        engine = make_engine(self.dir)
        controls = SessionControls()
        controls.bind(engine)
        enter(engine)
        controls.halt("daily discipline", mode=HaltMode.BLOCK_ENTRIES)
        self.assertEqual(controls.close_due_positions(engine, timestamp=at(11, 0), prices={A: 95.0}).closed, ())
        controls.halt("daily discipline", mode=HaltMode.FLATTEN)
        result = controls.close_due_positions(engine, timestamp=at(11, 1), prices={A: 95.0})
        self.assertEqual(len(result.closed), 1)

    def test_force_close_validates_input(self):
        engine = make_engine(self.dir)
        enter(engine)
        for bad in (0.0, -5.0, float("nan")):
            with self.assertRaises(ValueError):
                engine.force_close(A, timestamp=at(11, 0), price=bad)
        with self.assertRaises(ValueError):
            engine.force_close(A, timestamp=at(10, 0), price=90.0)   # not after the entry
        self.assertIsNotNone(engine.force_close(A, timestamp=at(11, 0), price=90.0))
        self.assertIsNone(engine.force_close(A, timestamp=at(11, 1), price=90.0), "already closed")

    def test_coordinator_rejects_entries_outside_the_window_and_consumes_the_signal(self):
        engine = make_engine(self.dir)
        controls = SessionControls()
        controls.bind(engine)
        coordinator = PaperExecutionCoordinator(adapter=NeverCalledAdapter(), engine=engine, controls=controls)
        signal = PaperSignal(strategy_id=A, direction="LONG", timestamp=at(15, 2), index=9, reason="t")
        kwargs = dict(signal=signal, underlying_price=24500.0, option_quote={}, decision_timestamp=at(15, 3))
        first = coordinator.process_signal(**kwargs)
        self.assertIn("After entry cutoff", first.rejection_reason)
        self.assertIn("Duplicate", coordinator.process_signal(**kwargs).rejection_reason)


if __name__ == "__main__":
    unittest.main()
