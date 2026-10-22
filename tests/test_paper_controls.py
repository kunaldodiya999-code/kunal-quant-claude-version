"""Segments, entry windows, forced exit, daily loss limit and the 12-hour kill switch."""
import csv
import tempfile
import unittest
from datetime import datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

from backtest.option_trade_lifecycle import OptionExitReason
from paper_trading.buyer_lifecycle import BuyerLifecycleConfig, BuyerOptionTradeLifecycle
from paper_trading.controls import (
    ALL_SEGMENTS, Segment, SegmentRules, SessionControls, SessionControlsConfig,
)
from paper_trading.coordinator import PaperExecutionCoordinator
from paper_trading.engine import PaperStrategyId, PaperTradingEngine
from paper_trading.recorder import PaperTradeRecorder
from paper_trading.recovery import restore_engine_from_journal
from paper_trading.signals import PaperSignal

IST = ZoneInfo("Asia/Kolkata")
A, B = PaperStrategyId.STRATEGY_A, PaperStrategyId.STRATEGY_B
FNO, EQ, CUR, COM = Segment.FNO, Segment.EQUITY, Segment.CURRENCY, Segment.COMMODITY
HOUR = 3600


def at(h, m, s=0, day=21):
    return int(datetime(2026, 10, day, h, m, s, tzinfo=IST).timestamp())


def make_engine(directory):
    lifecycle = BuyerOptionTradeLifecycle(BuyerLifecycleConfig(allocation=15_000.0, lot_size=65))
    return PaperTradingEngine(recorder=PaperTradeRecorder(directory), lifecycle=lifecycle)


def enter(engine, strategy=A, ts=None, price=100.0):
    return engine.open_position(strategy_id=strategy, direction="LONG",
                                symbol="NSE:NIFTY2610024500CE", entry_price=price,
                                timestamp=ts or at(10, 0))


def stop_out(engine, strategy=A, ts=None):
    engine.process_option_candle(strategy_id=strategy, timestamp=ts or at(10, 1), option_high=101.0,
                                 option_low=79.0, option_close=85.0, underlying_close=24500.0,
                                 kama_value=None)    # stop at 80 on 130 qty = -2,600


class ProbeAdapter:
    def prepare_entry(self, **kwargs):
        raise ValueError("adapter reached")      # coordinator turns ValueError into a rejection


class ConfigTests(unittest.TestCase):
    def test_defaults_match_owner_rules(self):
        rules = SessionControlsConfig().rules
        self.assertEqual(str(rules[FNO].entry_start), "09:30:00")
        self.assertEqual(str(rules[FNO].entry_end), "15:00:00")
        self.assertEqual(str(rules[FNO].force_exit), "15:10:00")
        self.assertIsNone(rules[COM].force_exit)
        self.assertIsNone(rules[CUR].force_exit)
        self.assertIsNone(SessionControlsConfig().daily_loss_limit, "loss cap is off by default")

    def test_invalid_config_is_rejected(self):
        bad = [
            lambda: SessionControlsConfig.from_hhmm("15:00", "09:30", "15:10"),
            lambda: SessionControlsConfig.from_hhmm("09:30", "15:20", "15:10"),
            lambda: SessionControlsConfig.from_hhmm("9h30", "15:00", "15:10"),
            lambda: SessionControlsConfig(max_daily_loss_amount=0),
            lambda: SessionControlsConfig(max_daily_loss_pct=5),                 # no capital
            lambda: SessionControlsConfig(capital=50_000, max_daily_loss_pct=150),
            lambda: SessionControlsConfig(kill_hours=0),
            lambda: SegmentRules(force_exit=time(9, 30)),
        ]
        for build in bad:
            with self.assertRaises(ValueError):
                build()

    def test_loss_limit_amount_percent_or_both_stricter_wins(self):
        self.assertEqual(SessionControlsConfig(max_daily_loss_amount=3000).daily_loss_limit, 3000)
        self.assertEqual(SessionControlsConfig(capital=50_000, max_daily_loss_pct=4).daily_loss_limit, 2000)
        both = SessionControlsConfig(capital=50_000, max_daily_loss_amount=3000, max_daily_loss_pct=4)
        self.assertEqual(both.daily_loss_limit, 2000)
        both = SessionControlsConfig(capital=50_000, max_daily_loss_amount=1500, max_daily_loss_pct=4)
        self.assertEqual(both.daily_loss_limit, 1500)


class EntryWindowTests(unittest.TestCase):
    def test_fno_window_boundaries(self):
        c = SessionControls()
        self.assertIn("Before entry window", c.entry_block_reason(at(9, 29, 59), FNO))
        self.assertIsNone(c.entry_block_reason(at(9, 30), FNO))
        self.assertIsNone(c.entry_block_reason(at(14, 59, 59), FNO))
        self.assertIn("After entry cutoff", c.entry_block_reason(at(15, 0), FNO))

    def test_window_is_configurable(self):
        c = SessionControls(SessionControlsConfig.from_hhmm("09:45", "14:30", "14:40"))
        self.assertIn("Before entry window", c.entry_block_reason(at(9, 40), FNO))
        self.assertIsNone(c.entry_block_reason(at(9, 45), FNO))
        self.assertIn("After entry cutoff", c.entry_block_reason(at(14, 30), FNO))

    def test_commodity_and_currency_have_no_fno_cutoff(self):
        c = SessionControls()
        for segment in (COM, CUR):
            self.assertIsNone(c.entry_block_reason(at(16, 30), segment))
            self.assertIsNone(c.entry_block_reason(at(22, 45), segment))
        self.assertIn("After entry cutoff", c.entry_block_reason(at(16, 30), EQ))


class KillSwitchTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_kill_selected_segments_only_for_twelve_hours(self):
        c = SessionControls(journal_dir=self.dir)
        t0 = at(11, 0)
        c.kill([FNO], timestamp=t0)
        self.assertIn("Kill switch active for NSE & BSE F&O", c.entry_block_reason(t0 + 60, FNO))
        self.assertIsNone(c.entry_block_reason(at(11, 1), COM), "other segments keep trading")
        self.assertIsNone(c.entry_block_reason(at(11, 1), EQ))
        self.assertIn("Kill switch", c.entry_block_reason(t0 + 12 * HOUR - 1, FNO))
        self.assertEqual(c.active_kills(t0 + 12 * HOUR), {})
        self.assertEqual(list(c.active_kills(t0 + 12 * HOUR - 1)), [FNO])

    def test_kill_all_and_multi_select(self):
        c = SessionControls()
        t0 = at(11, 0)
        c.kill(ALL_SEGMENTS, timestamp=t0)
        for segment in Segment:
            self.assertIn("Kill switch", c.entry_block_reason(t0 + 5, segment))
        d = SessionControls()
        d.kill(["FNO", "COMMODITY"], timestamp=t0)
        self.assertIn("Kill switch", d.entry_block_reason(t0 + 5, FNO))
        self.assertIn("Kill switch", d.entry_block_reason(t0 + 5, COM))
        self.assertIsNone(d.entry_block_reason(t0 + 5, CUR))

    def test_a_kill_cannot_be_shortened_only_extended(self):
        c = SessionControls()
        t0 = at(11, 0)
        c.kill([FNO], timestamp=t0)
        first_end = c.active_kills(t0)[FNO]
        c.kill([COM], timestamp=t0 + HOUR)                    # a later kill of another segment
        self.assertEqual(c.active_kills(t0 + HOUR)[FNO], first_end)
        self.assertEqual(c.active_kills(t0 + HOUR)[COM], t0 + 13 * HOUR)
        c.kill([FNO], timestamp=t0 + 2 * HOUR)                # re-kill extends
        self.assertEqual(c.active_kills(t0 + 2 * HOUR)[FNO], t0 + 14 * HOUR)
        c.kill([FNO], timestamp=t0 - 5 * HOUR)                # a clock that jumps back must not shorten it
        self.assertEqual(c.active_kills(t0 + 2 * HOUR)[FNO], t0 + 14 * HOUR)

    def test_bad_selections_are_refused(self):
        c = SessionControls()
        with self.assertRaises(ValueError):
            c.kill([], timestamp=at(11, 0))
        with self.assertRaises(ValueError):
            c.kill(["NSE_EQUITY"], timestamp=at(11, 0))

    def test_kill_survives_restart_and_is_logged(self):
        SessionControls(journal_dir=self.dir).kill([FNO, EQ], timestamp=at(11, 0))
        again = SessionControls(journal_dir=self.dir)         # simulated restart
        self.assertIn("Kill switch", again.entry_block_reason(at(11, 30), EQ))
        self.assertIsNone(again.entry_block_reason(at(11, 30), COM))
        with (self.dir / "controls_events.csv").open(newline="", encoding="utf-8") as h:
            rows = list(csv.DictReader(h))
        self.assertEqual([r["event_type"] for r in rows], ["KILL"])
        self.assertIn("Equity", rows[0]["detail"])

    def test_unreadable_state_fails_closed(self):
        (self.dir / "controls_state.json").write_text("{not json", encoding="utf-8")
        c = SessionControls(journal_dir=self.dir)
        for segment in Segment:
            self.assertIn("unreadable", c.entry_block_reason(at(10, 0), segment))

    def test_kill_leaves_open_positions_alone(self):
        engine = make_engine(self.dir)
        c = SessionControls(journal_dir=self.dir)
        c.bind(engine)
        enter(engine)
        c.kill(ALL_SEGMENTS, timestamp=at(11, 0))
        self.assertIsNotNone(engine.open_trade(A))
        self.assertEqual(c.close_due_positions(engine, timestamp=at(11, 1), prices={A: 90.0}).closed, ())


class DailyLossTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.engine = make_engine(Path(self._tmp.name))

    def tearDown(self):
        self._tmp.cleanup()

    def _controls(self, **kwargs):
        c = SessionControls(SessionControlsConfig(**kwargs))
        c.bind(self.engine)
        return c

    def test_off_by_default_even_after_a_loss(self):
        c = self._controls()
        enter(self.engine); stop_out(self.engine)
        self.assertIsNone(c.entry_block_reason(at(10, 5), FNO))

    def test_absolute_amount_blocks_at_the_limit(self):
        c = self._controls(max_daily_loss_amount=2_000.0)
        enter(self.engine); stop_out(self.engine)
        self.assertEqual(round(c.realized_pnl_today(at(10, 5))), -2600)
        self.assertIn("Daily loss limit", c.entry_block_reason(at(10, 5), FNO))

    def test_percent_of_capital_blocks_at_the_limit(self):
        c = self._controls(capital=50_000.0, max_daily_loss_pct=5.0)     # 2,500
        enter(self.engine); stop_out(self.engine)
        self.assertIn("Daily loss limit", c.entry_block_reason(at(10, 5), FNO))
        roomy = self._controls(capital=50_000.0, max_daily_loss_pct=6.0)  # 3,000 > 2,600 loss
        self.assertIsNone(roomy.entry_block_reason(at(10, 5), FNO))

    def test_only_todays_trades_count(self):
        c = self._controls(max_daily_loss_amount=2_000.0)
        enter(self.engine, ts=at(10, 0, day=20))
        self.engine.force_close(A, timestamp=at(11, 0, day=20), price=50.0)
        self.assertIsNone(c.entry_block_reason(at(10, 5), FNO))


class ForcedExitTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_fno_position_is_closed_at_1510_and_stays_closed_after_restart(self):
        engine = make_engine(self.dir)
        c = SessionControls(journal_dir=self.dir)
        c.bind(engine)
        opened = enter(engine)
        self.assertEqual(c.close_due_positions(engine, timestamp=at(15, 9), prices={A: 120.0}).closed, ())
        result = c.close_due_positions(engine, timestamp=at(15, 10), prices={A: 120.0})
        event = result.closed[0][1]
        self.assertEqual(event.reason, OptionExitReason.END_OF_DATA)
        self.assertAlmostEqual(opened.position.gross_pnl, 20.0 * opened.position.quantity)
        restored = make_engine(self.dir)
        restore_engine_from_journal(restored, today=datetime(2026, 10, 21, 15, 20, tzinfo=IST))
        self.assertIsNone(restored.open_trade(A))

    def test_commodity_position_is_never_force_exited(self):
        engine = make_engine(self.dir)
        c = SessionControls(journal_dir=self.dir)
        c.bind(engine)
        enter(engine, A)          # F&O
        enter(engine, B)          # pretend this strategy trades commodity
        seg = lambda s: COM if s == B else FNO
        result = c.close_due_positions(engine, timestamp=at(15, 30), prices={A: 90.0, B: 90.0}, segment_of=seg)
        self.assertEqual([s for s, _ in result.closed], [A])
        self.assertIsNotNone(engine.open_trade(B), "commodity position stays open")
        late = c.close_due_positions(engine, timestamp=at(22, 50), prices={B: 90.0}, segment_of=seg)
        self.assertEqual(late.closed, ())

    def test_unpriced_fno_position_is_reported_not_hidden(self):
        engine = make_engine(self.dir)
        c = SessionControls(journal_dir=self.dir)
        c.bind(engine)
        enter(engine, A); enter(engine, B)
        result = c.close_due_positions(engine, timestamp=at(15, 11), prices={A: 90.0})
        self.assertEqual([s for s, _ in result.closed], [A])
        self.assertEqual(result.unpriced, (B,))
        self.assertIsNotNone(engine.open_trade(B))

    def test_force_close_validates_input(self):
        engine = make_engine(self.dir)
        enter(engine)
        for bad in (0.0, -5.0, float("nan")):
            with self.assertRaises(ValueError):
                engine.force_close(A, timestamp=at(11, 0), price=bad)
        with self.assertRaises(ValueError):
            engine.force_close(A, timestamp=at(10, 0), price=90.0)
        self.assertIsNotNone(engine.force_close(A, timestamp=at(11, 0), price=90.0))
        self.assertIsNone(engine.force_close(A, timestamp=at(11, 1), price=90.0))


class CoordinatorTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.engine = make_engine(Path(self._tmp.name))

    def tearDown(self):
        self._tmp.cleanup()

    def _attempt(self, coordinator, decision):
        signal = PaperSignal(strategy_id=A, direction="LONG", timestamp=decision - 120, index=9, reason="t")
        return coordinator.process_signal(signal=signal, underlying_price=24500.0, option_quote={},
                                          decision_timestamp=decision)

    def test_entry_after_cutoff_is_rejected_and_the_signal_is_consumed(self):
        c = SessionControls(); c.bind(self.engine)
        coordinator = PaperExecutionCoordinator(adapter=ProbeAdapter(), engine=self.engine, controls=c)
        first = self._attempt(coordinator, at(15, 3))
        self.assertIn("After entry cutoff", first.rejection_reason)
        self.assertIn("Duplicate", self._attempt(coordinator, at(15, 3)).rejection_reason)

    def test_inside_the_window_the_adapter_is_reached(self):
        c = SessionControls(); c.bind(self.engine)
        coordinator = PaperExecutionCoordinator(adapter=ProbeAdapter(), engine=self.engine, controls=c)
        self.assertEqual(self._attempt(coordinator, at(10, 3)).rejection_reason, "adapter reached")

    def test_kill_switch_blocks_only_the_killed_segment(self):
        c = SessionControls(); c.bind(self.engine)
        c.kill([COM], timestamp=at(10, 0))
        fno = PaperExecutionCoordinator(adapter=ProbeAdapter(), engine=self.engine, controls=c)
        self.assertEqual(self._attempt(fno, at(10, 3)).rejection_reason, "adapter reached")
        c.kill([FNO], timestamp=at(10, 5))
        again = PaperExecutionCoordinator(adapter=ProbeAdapter(), engine=self.engine, controls=c)
        self.assertIn("Kill switch active for NSE & BSE F&O", self._attempt(again, at(10, 6)).rejection_reason)


if __name__ == "__main__":
    unittest.main()
