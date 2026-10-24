"""Switchable exits: trailing-stop checkboxes, tighter-stop-wins, fills, restart parity."""
import csv
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from backtest.option_trade_lifecycle import OptionExitReason
from paper_trading.buyer_lifecycle import BuyerLifecycleConfig, BuyerOptionTradeLifecycle
from paper_trading.engine import PaperStrategyId, PaperTradingEngine
from paper_trading.exit_manager import DEFAULT_TSL, ExitManager, ExitRules, TSL_METHODS
from paper_trading.recorder import PaperTradeRecorder
from paper_trading.recovery import restore_engine_from_journal
from paper_trading.tsl_shadow_lab import OptionCandle, TslShadowLab

A = PaperStrategyId.STRATEGY_A
SYM = "NSE:NIFTY2610024500CE"
T0 = 1_792_000_000
CHAND = "chandelier_atr9_mult1.5"
ST_A = "supertrend_atr5_factor1.0"
ST_B = "supertrend_atr7_factor1.5"
PSAR_A = "psar_start0.02_inc0.02_max0.20"
PSAR_B = "psar_start0.04_inc0.04_max0.10"

# Entry 100. Candle i has close 100+i, high 101+i, low 98+i (true range 3 every bar).
CLIMB = [(99 + i, 101 + i, 98 + i, 100 + i) for i in range(1, 13)]
DROP = CLIMB + [(111.5, 112.0, 105.0, 106.0)]       # sharp drop on candle 13
GAP = CLIMB + [(100.0, 101.0, 98.0, 99.0)]          # candle 13 gaps far below every stop
WIDE = [(100, 112, 88, 100)] * 10 + [(95, 96, 60, 65)]   # huge ranges, then a crash on candle 11


def candles(path):
    return [OptionCandle(T0 + 60 * i, o, h, l, c) for i, (o, h, l, c) in enumerate(path, 1)]


def make_engine(directory):
    lifecycle = BuyerOptionTradeLifecycle(BuyerLifecycleConfig(allocation=25_000.0, lot_size=50, stop_loss_pct=0.20))
    return PaperTradingEngine(recorder=PaperTradeRecorder(directory), lifecycle=lifecycle)


class ExitManagerTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.engine = make_engine(self.dir)
        self.lab = TslShadowLab(self.dir / "lab")
        self.manager = ExitManager(self.engine, self.lab, journal_dir=self.dir)
        self.engine.open_position(strategy_id=A, direction="LONG", symbol=SYM,
                                  entry_price=100.0, timestamp=T0)

    def tearDown(self):
        self._tmp.cleanup()

    def run_path(self, path, manager=None, **kwargs):
        decisions = []
        for candle in candles(path):
            decisions += (manager or self.manager).on_option_candle(symbol=SYM, candle=candle, **kwargs)
        return decisions

    def trade(self):
        return self.engine.trades(A)[0]

    def events(self):
        path = self.dir / "exit_events.csv"
        if not path.exists():
            return []
        with path.open(newline="", encoding="utf-8") as h:
            return list(csv.DictReader(h))

    # ---- catalogue and defaults ---------------------------------------
    def test_catalogue_matches_the_shadow_lab_and_default_is_chandelier(self):
        self.assertEqual(set(TSL_METHODS), set(TslShadowLab.CANDIDATES))
        self.assertEqual(ExitRules().active_tsl, DEFAULT_TSL)
        self.assertEqual(DEFAULT_TSL, (CHAND,))
        self.assertTrue(ExitRules().partial_target)
        self.assertFalse(ExitRules().kama_exit)

    def test_bad_rules_are_refused(self):
        with self.assertRaises(ValueError):
            ExitRules(active_tsl=("made_up",))
        with self.assertRaises(ValueError):
            ExitRules(active_tsl=(CHAND, CHAND))
        with self.assertRaises(ValueError):
            self.manager.set_rules(active_tsl=["nope"])
        self.assertEqual(self.manager.rules.active_tsl, DEFAULT_TSL, "a refused change changes nothing")

    # ---- trailing stop drives the exit --------------------------------
    def test_chandelier_exit_fills_at_the_hand_calculated_stop(self):
        decisions = self.run_path(DROP)
        # highest high of the last 9 bars = 113; ATR = 3; stop = 113 - 1.5 * 3 = 108.5
        trade = self.trade()
        self.assertTrue(trade.closed)
        exit_event = trade.exits[-1]
        self.assertEqual((exit_event.price, exit_event.reason), (108.5, OptionExitReason.STOP_LOSS))
        self.assertAlmostEqual(trade.position.gross_pnl, 8.5 * 250)
        self.assertEqual([d.kind for d in decisions], ["TSL_STOP"])
        logged = [e for e in self.events() if e["event_type"] == "TSL_EXIT"]
        self.assertIn("Chandelier", logged[0]["detail"])

    def test_gap_below_the_stop_fills_at_the_open(self):
        self.run_path(GAP)
        self.assertEqual(self.trade().exits[-1].price, 100.0)

    def test_initial_stop_wins_when_it_is_tighter_than_the_trailing_stop(self):
        decisions = self.run_path(WIDE)        # chandelier 76 is looser than the initial stop at 80
        exit_event = self.trade().exits[-1]
        self.assertEqual(exit_event.price, 80.0)
        self.assertEqual([d.kind for d in decisions], ["LIFECYCLE"])
        self.assertFalse([e for e in self.events() if e["event_type"] == "TSL_EXIT"])

    def test_nothing_ticked_leaves_only_the_initial_stop(self):
        self.manager.set_rules(active_tsl=[])
        self.run_path(DROP)
        self.assertFalse(self.trade().closed)

    def test_the_highest_ticked_stop_fills_when_several_are_hit_together(self):
        self.manager.set_rules(active_tsl=[CHAND, ST_B])      # fills would be 108.5 and 107.0
        self.run_path(DROP)
        self.assertEqual(self.trade().exits[-1].price, 108.5)

    def test_parabolic_sar_flip_exits_at_the_candle_close(self):
        self.manager.set_rules(active_tsl=[PSAR_B])
        decisions = self.run_path(DROP)
        self.assertEqual(self.trade().exits[-1].price, 106.0)
        self.assertEqual([d.kind for d in decisions], ["SAR_FLIP"])

    # ---- switching ----------------------------------------------------
    def test_switching_method_mid_trade_takes_effect_on_the_next_candle(self):
        self.run_path(CLIMB)                                  # 12 candles under Chandelier
        self.manager.set_rules(active_tsl=[ST_B], timestamp=T0 + 721)
        self.manager.on_option_candle(symbol=SYM, candle=candles(DROP)[-1])
        self.assertEqual(self.trade().exits[-1].price, 107.0)     # Supertrend B's level, no warm-up needed
        change = [e for e in self.events() if e["event_type"] == "RULES_CHANGED"]
        self.assertIn("supertrend_atr7_factor1.5", change[0]["detail"])

    def test_a_method_that_already_stopped_out_in_the_shadow_run_cannot_drive_the_trade(self):
        self.run_path(WIDE[:5])                               # Parabolic SAR A and B flip out at candle 3
        self.manager.set_rules(active_tsl=[PSAR_A])
        self.assertEqual(self.manager.spent_methods(A), (PSAR_A,))
        for candle in candles(WIDE)[5:10]:
            self.manager.on_option_candle(symbol=SYM, candle=candle)
        self.assertFalse(self.trade().closed, "a spent method must not close the live trade")
        self.manager.on_option_candle(symbol=SYM, candle=candles(WIDE)[10])   # the crash candle
        self.assertEqual(self.trade().exits[-1].price, 80.0, "the initial stop still protects the trade")
        self.assertFalse([e for e in self.events() if e["event_type"] == "TSL_EXIT"])

    def test_a_method_ticked_from_the_start_can_exit_early(self):
        self.manager.set_rules(active_tsl=[PSAR_A])
        self.run_path(WIDE[:5])
        self.assertTrue(self.trade().closed)
        self.assertEqual(self.trade().exits[-1].price, 88.0)

    # ---- other checkboxes ---------------------------------------------
    def test_partial_target_checkbox(self):
        spike = [(100.0, 165.0, 95.0, 150.0)]
        self.run_path(spike)
        self.assertEqual(self.trade().exits[0].reason, OptionExitReason.TARGET_3R)
        self.setUp()
        self.manager.set_rules(partial_target=False)
        self.run_path(spike)
        self.assertEqual(self.trade().exits, [])

    def test_kama_exit_checkbox(self):
        flat = [(100.0, 102.0, 99.0, 101.0)]
        self.run_path(flat, underlying_close=24400.0, kama_value=24500.0)
        self.assertFalse(self.trade().closed, "KAMA exit is off by default")
        self.setUp()
        self.manager.set_rules(kama_exit=True)
        self.run_path(flat, underlying_close=24400.0, kama_value=24500.0)
        self.assertEqual(self.trade().exits[-1].reason, OptionExitReason.KAMA_EXIT)

    def test_saved_choice_survives_a_restart_and_a_damaged_file_resets_with_a_log(self):
        self.manager.set_rules(active_tsl=[PSAR_A, ST_A], partial_target=False)
        again = ExitManager(make_engine(self.dir / "x"), TslShadowLab(self.dir / "lab2"),
                            rules=ExitRules(), journal_dir=self.dir)
        self.assertEqual(again.rules.active_tsl, (PSAR_A, ST_A))
        self.assertFalse(again.rules.partial_target)
        (self.dir / "exit_rules.json").write_text("{broken", encoding="utf-8")
        reset = ExitManager(make_engine(self.dir / "y"), TslShadowLab(self.dir / "lab3"),
                            rules=ExitRules(), journal_dir=self.dir)
        self.assertEqual(reset.rules, ExitRules())
        self.assertIn("RULES_RESET", [e["event_type"] for e in self.events()])

    # ---- robustness ---------------------------------------------------
    def test_repeating_a_candle_or_another_symbol_does_nothing(self):
        decisions = self.run_path(DROP)
        self.assertEqual(len(decisions), 1)
        again = self.manager.on_option_candle(symbol=SYM, candle=candles(DROP)[-1])
        self.assertEqual(again, [])
        other = ExitManager(make_engine(self.dir / "o"), TslShadowLab(self.dir / "lab4"))
        other.engine.open_position(strategy_id=A, direction="LONG", symbol=SYM, entry_price=100.0, timestamp=T0)
        self.assertEqual(other.on_option_candle(symbol="NSE:OTHER", candle=candles(DROP)[-1]), [])

    def test_restart_mid_trade_rebuilds_trailing_state_and_exits_identically(self):
        self.run_path(CLIMB)                                          # 12 candles, still open
        fresh = make_engine(self.dir)
        restore_engine_from_journal(fresh, today=datetime(2026, 10, 21, 10, 0, tzinfo=ZoneInfo("Asia/Kolkata")))
        self.assertIsNotNone(fresh.open_trade(A))
        manager = ExitManager(fresh, TslShadowLab(self.dir / "lab_restart"), journal_dir=self.dir)
        replayed = manager.catch_up(symbol=SYM, candles=candles(DROP))   # 12 old + 1 new
        self.assertEqual(replayed, 13)
        closed = fresh.trades(A)[0]
        self.assertTrue(closed.closed)
        self.assertEqual(closed.exits[-1].price, 108.5, "same fill as an uninterrupted run")


if __name__ == "__main__":
    unittest.main()
