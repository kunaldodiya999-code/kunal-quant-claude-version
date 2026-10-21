"""Restart recovery: open positions and seen signals come back from the journal."""
import csv
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from backtest.option_trade_lifecycle import OptionExitReason
from paper_trading.buyer_lifecycle import BuyerLifecycleConfig, BuyerOptionTradeLifecycle
from paper_trading.coordinator import PaperExecutionCoordinator
from paper_trading.engine import PaperStrategyId, PaperTradingEngine
from paper_trading.recorder import PaperTradeRecorder
from paper_trading.recovery import (
    RecoveryError, load_seen_signal_keys, restore_engine_from_journal, restore_from_journal,
)
from paper_trading.signals import PaperSignal

IST = ZoneInfo("Asia/Kolkata")
A = PaperStrategyId.STRATEGY_A
ENTRY_TS = int(datetime(2026, 10, 21, 10, 0, tzinfo=IST).timestamp())


def make_engine(directory):
    lifecycle = BuyerOptionTradeLifecycle(BuyerLifecycleConfig(allocation=15_000.0, lot_size=65))
    return PaperTradingEngine(recorder=PaperTradeRecorder(directory), lifecycle=lifecycle)


def open_trade(engine, direction="LONG", price=100.0):
    return engine.open_position(
        strategy_id=A, direction=direction, symbol="NSE:NIFTY2610024500CE",
        entry_price=price, timestamp=ENTRY_TS,
    )


def candle(engine, ts, high, low, close, underlying=24500.0, kama=None):
    return engine.process_option_candle(
        strategy_id=A, timestamp=ts, option_high=high, option_low=low,
        option_close=close, underlying_close=underlying, kama_value=kama,
    )


class StubAdapter:
    def prepare_entry(self, **kwargs):
        raise AssertionError("adapter must not be reached for a restored duplicate")


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.today = datetime(2026, 10, 21, 11, 0, tzinfo=IST)

    def tearDown(self):
        self._tmp.cleanup()

    def test_open_position_survives_restart_and_blocks_duplicate_entry(self):
        first = make_engine(self.dir)
        original = open_trade(first)
        second = make_engine(self.dir)
        report = restore_engine_from_journal(second, today=self.today)
        restored = second.open_trade(A)
        self.assertIsNotNone(restored)
        self.assertEqual(len(report.open_trade_ids), 1)
        self.assertEqual(restored.position.quantity, original.position.quantity)
        self.assertEqual(restored.position.stop_loss, original.position.stop_loss)
        self.assertEqual(restored.position.target, original.position.target)
        self.assertEqual(restored.entry_timestamp, ENTRY_TS)
        self.assertIsNone(open_trade(second), "a second entry must be refused")

    def test_partial_exit_state_is_restored_and_trade_can_finish(self):
        first = make_engine(self.dir)
        trade = open_trade(first)                       # entry 100, stop 80, target 160
        exits = candle(first, ENTRY_TS + 60, 165.0, 95.0, 150.0)
        self.assertEqual(exits[0].reason, OptionExitReason.TARGET_3R)
        second = make_engine(self.dir)
        restore_engine_from_journal(second, today=self.today)
        restored = second.open_trade(A)
        self.assertTrue(restored.position.partial_exit_done)
        self.assertEqual(restored.position.remaining_lots, trade.position.remaining_lots)
        self.assertAlmostEqual(restored.position.gross_pnl, trade.position.gross_pnl)
        self.assertEqual(restored.last_processed_timestamp, ENTRY_TS + 60)
        with self.assertRaises(ValueError):             # an already-processed candle cannot be replayed
            candle(second, ENTRY_TS + 60, 120.0, 90.0, 100.0)
        stop = candle(second, ENTRY_TS + 120, 120.0, 79.0, 85.0)
        self.assertEqual(stop[0].reason, OptionExitReason.STOP_LOSS)
        self.assertIsNone(second.open_trade(A))

    def test_put_buyer_direction_is_preserved(self):
        first = make_engine(self.dir)
        open_trade(first, direction="SHORT")
        second = make_engine(self.dir)
        restore_engine_from_journal(second, today=self.today)
        restored = second.open_trade(A)
        self.assertEqual(restored.position.direction.value, "SHORT")
        self.assertEqual(restored.position.stop_loss, 80.0)   # below entry: premium is long

    def test_closed_trade_is_history_not_an_open_position(self):
        first = make_engine(self.dir)
        open_trade(first)
        candle(first, ENTRY_TS + 60, 101.0, 79.0, 85.0)  # stop loss
        second = make_engine(self.dir)
        report = restore_engine_from_journal(second, today=self.today)
        self.assertEqual(len(report.closed_trade_ids), 1)
        self.assertIsNone(second.open_trade(A))
        self.assertEqual(len(second.trades(A)), 1)
        self.assertIsNotNone(open_trade(second), "a new entry is allowed after a closed trade")

    def test_open_trade_from_an_earlier_day_is_flagged_stale(self):
        first = make_engine(self.dir)
        open_trade(first)
        second = make_engine(self.dir)
        tomorrow = datetime(2026, 10, 22, 9, 20, tzinfo=IST)
        report = restore_engine_from_journal(second, today=tomorrow)
        self.assertEqual(len(report.stale_open_trade_ids), 1)

    def test_empty_journal_restores_nothing(self):
        report = restore_engine_from_journal(make_engine(self.dir), today=self.today)
        self.assertEqual(report.trades_restored, 0)

    def test_restore_refuses_a_non_fresh_engine(self):
        engine = make_engine(self.dir)
        open_trade(engine)
        with self.assertRaises(RecoveryError):
            restore_engine_from_journal(engine, today=self.today)

    def _rewrite(self, mutate):
        path = self.dir / "trade_events.csv"
        with path.open(newline="", encoding="utf-8") as h:
            rows = list(csv.DictReader(h))
            fields = list(rows[0].keys())
        rows = mutate(rows)
        with path.open("w", newline="", encoding="utf-8") as h:
            writer = csv.DictWriter(h, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)

    def test_corrupt_journal_is_rejected_and_installs_nothing(self):
        first = make_engine(self.dir)
        open_trade(first)
        candle(first, ENTRY_TS + 60, 165.0, 95.0, 150.0)
        self._rewrite(lambda rows: [dict(r, gross_pnl="999") if r["event_type"] == "EXIT" else r for r in rows])
        second = make_engine(self.dir)
        with self.assertRaises(RecoveryError):
            restore_engine_from_journal(second, today=self.today)
        self.assertEqual(second.all_trades(), ())
        self.assertEqual(second.active_positions, {})

    def test_two_open_trades_for_one_strategy_is_rejected(self):
        first = make_engine(self.dir)
        open_trade(first)
        def duplicate(rows):
            clone = dict(rows[0], trade_id="KTMI_LONG_SHORT_SPEED:1:OTHER", entry_timestamp="1")
            return rows + [clone]
        self._rewrite(duplicate)
        with self.assertRaises(RecoveryError):
            restore_engine_from_journal(make_engine(self.dir), today=self.today)

    def test_exit_without_entry_is_rejected(self):
        first = make_engine(self.dir)
        open_trade(first)
        candle(first, ENTRY_TS + 60, 165.0, 95.0, 150.0)
        self._rewrite(lambda rows: rows[1:])
        with self.assertRaises(RecoveryError):
            restore_engine_from_journal(make_engine(self.dir), today=self.today)

    def test_seen_signals_are_restored_and_never_re_entered(self):
        recorder = PaperTradeRecorder(self.dir)
        signal = PaperSignal(strategy_id=A, direction="LONG", timestamp=ENTRY_TS - 180,
                             index=57, reason="test")
        recorder.record_signal(signal, symbol="NSE:NIFTY50-INDEX")
        self.assertEqual(load_seen_signal_keys(recorder.signals_path),
                         {(A.value, "LONG", ENTRY_TS - 180)})
        engine = make_engine(self.dir)
        coordinator = PaperExecutionCoordinator(adapter=StubAdapter(), engine=engine)
        report = restore_from_journal(engine, coordinator, today=self.today)
        self.assertEqual(report.signals_restored, 1)
        # same bar, different index after the history was rebuilt: still a duplicate
        replay = PaperSignal(strategy_id=A, direction="LONG", timestamp=ENTRY_TS - 180,
                             index=3, reason="test")
        attempt = coordinator.process_signal(
            signal=replay, underlying_price=24500.0, option_quote={},
            decision_timestamp=ENTRY_TS,
        )
        self.assertIsNone(attempt.trade)
        self.assertIn("before restart", attempt.rejection_reason)


if __name__ == "__main__":
    unittest.main()
