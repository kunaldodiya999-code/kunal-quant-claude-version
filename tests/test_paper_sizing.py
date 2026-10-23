"""Allocation and lot sizing: hard budget ceiling, whole lots, two-way synced inputs."""
import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from paper_trading.account import PaperAccount
from paper_trading.buyer_lifecycle import BuyerLifecycleConfig, BuyerOptionTradeLifecycle
from paper_trading.costs import OptionCostModel
from paper_trading.coordinator import PaperExecutionCoordinator
from paper_trading.engine import PaperStrategyId, PaperTradingEngine
from paper_trading.recorder import PaperTradeRecorder
from paper_trading.signals import PaperSignal
from paper_trading.sizing import (
    PERCENT_PRESETS, AllocationSetting, AllocationStore, amount_from_percent,
    calculate_lots, percent_from_amount, sizing_warning,
)

IST = ZoneInfo("Asia/Kolkata")
A = PaperStrategyId.STRATEGY_A
T0 = int(datetime(2026, 10, 21, 10, 0, tzinfo=IST).timestamp())
SYM = "NSE:NIFTY2610024500CE"


class LotMathTests(unittest.TestCase):
    def test_owner_example_25_percent_of_one_lakh(self):
        budget = amount_from_percent(100_000.0, 25)
        self.assertEqual(budget, 25_000.0)
        r = calculate_lots(budget, 100.0, 65)
        self.assertEqual(r.cost_per_lot, 6_500.0)
        self.assertEqual((r.lots, r.quantity), (3, 195))
        self.assertEqual(r.deployed, 19_500.0)
        self.assertEqual(r.unallocated, 5_500.0)
        self.assertTrue(r.tradable)

    def test_budget_is_a_hard_ceiling_for_every_budget(self):
        for budget in range(0, 60_000, 250):
            r = calculate_lots(float(budget), 100.0, 65)
            self.assertLessEqual(r.deployed, budget)
            self.assertLess(budget - r.deployed, r.cost_per_lot)     # one more lot would not fit

    def test_exact_multiple_buys_exactly_that_many_lots(self):
        self.assertEqual(calculate_lots(6_500.0, 100.0, 65).lots, 1)
        self.assertEqual(calculate_lots(6_499.99, 100.0, 65).lots, 0)
        # Plain float division (402.5 // (16.10 * 25)) returns 0 lots here; the right answer is 1.
        self.assertEqual(int(402.5 // (16.10 * 25)), 0)
        self.assertEqual(calculate_lots(402.50, 16.10, 25).lots, 1)

    def test_budget_below_one_lot_gives_a_clear_warning_and_is_not_tradable(self):
        r = calculate_lots(5_000.0, 100.0, 65)
        self.assertFalse(r.tradable)
        self.assertEqual(r.deployed, 0.0)
        text = sizing_warning(r)
        for expected in ("Trade not taken", "5,000.00", "6,500.00", "short by Rs 1,500.00", "65 units"):
            self.assertIn(expected, text)
        self.assertIsNone(sizing_warning(calculate_lots(6_500.0, 100.0, 65)))

    def test_invalid_inputs_are_refused(self):
        for args in ((-1, 100.0, 65), (1000, 0.0, 65), (1000, float("nan"), 65), (1000, 100.0, 0)):
            with self.assertRaises(ValueError):
                calculate_lots(*args)


class TwoWaySyncTests(unittest.TestCase):
    def test_presets_are_ten_to_one_hundred(self):
        self.assertEqual(PERCENT_PRESETS, (10, 20, 30, 40, 50, 60, 70, 80, 90, 100))

    def test_percent_to_amount_and_back(self):
        self.assertEqual(amount_from_percent(100_000.0, 80), 80_000.0)
        self.assertEqual(percent_from_amount(100_000.0, 80_000.0), 80.0)
        for percent in PERCENT_PRESETS:
            amount = amount_from_percent(100_000.0, percent)
            self.assertEqual(percent_from_amount(100_000.0, amount), float(percent))

    def test_odd_amounts_round_to_two_decimals(self):
        self.assertEqual(percent_from_amount(100_000.0, 33_333.0), 33.33)
        self.assertEqual(amount_from_percent(95_000.0, 12.5), 11_875.0)

    def test_bad_values_are_refused(self):
        for bad in (lambda: percent_from_amount(100_000.0, 100_001.0),
                    lambda: percent_from_amount(100_000.0, 0),
                    lambda: amount_from_percent(100_000.0, 0),
                    lambda: amount_from_percent(100_000.0, 101),
                    lambda: amount_from_percent(0, 50)):
            with self.assertRaises(ValueError):
                bad()

    def test_view_shows_both_inputs_in_either_mode(self):
        by_percent = AllocationSetting.from_percent(80).view(100_000.0)
        self.assertEqual((by_percent["mode"], by_percent["percent"], by_percent["amount"]), ("PERCENT", 80, 80_000.0))
        by_amount = AllocationSetting.from_amount(80_000.0).view(100_000.0)
        self.assertEqual((by_amount["mode"], by_amount["percent"], by_amount["amount"]), ("AMOUNT", 80.0, 80_000.0))
        over = AllocationSetting.from_amount(150_000.0).view(100_000.0)
        self.assertTrue(over["over_balance"])

    def test_percent_follows_the_balance_but_an_amount_stays_fixed(self):
        pct, amt = AllocationSetting.from_percent(25), AllocationSetting.from_amount(25_000.0)
        self.assertEqual(pct.budget(balance=100_000.0, available_cash=100_000.0).budget, 25_000.0)
        self.assertEqual(pct.budget(balance=80_000.0, available_cash=80_000.0).budget, 20_000.0)
        self.assertEqual(amt.budget(balance=80_000.0, available_cash=80_000.0).budget, 25_000.0)

    def test_budget_is_capped_by_balance_and_by_free_cash(self):
        decision = AllocationSetting.from_percent(80).budget(balance=100_000.0, available_cash=50_000.0)
        self.assertEqual((decision.requested, decision.budget, decision.limited_by), (80_000.0, 50_000.0, "cash"))
        decision = AllocationSetting.from_amount(150_000.0).budget(balance=100_000.0, available_cash=100_000.0)
        self.assertEqual((decision.budget, decision.limited_by), (100_000.0, "balance"))
        self.assertEqual(AllocationSetting.from_percent(50).budget(balance=1_000.0, available_cash=-5.0).budget, 0.0)

    def test_invalid_settings(self):
        for bad in (lambda: AllocationSetting.from_percent(0), lambda: AllocationSetting.from_percent(101),
                    lambda: AllocationSetting.from_amount(-1), lambda: AllocationSetting("OTHER", 1)):
            with self.assertRaises(ValueError):
                bad()

    def test_choice_persists_and_a_damaged_file_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = AllocationStore(AllocationSetting.from_amount(15_000.0), journal_dir=tmp)
            store.set(AllocationSetting.from_percent(40))
            again = AllocationStore(AllocationSetting.from_amount(15_000.0), journal_dir=tmp)
            self.assertEqual(again.setting, AllocationSetting.from_percent(40))
            (Path(tmp) / "allocation.json").write_text("{nope", encoding="utf-8")
            with self.assertRaises(ValueError):
                AllocationStore(AllocationSetting.from_amount(15_000.0), journal_dir=tmp)


class EngineSizingTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        lifecycle = BuyerOptionTradeLifecycle(BuyerLifecycleConfig(allocation=15_000.0, lot_size=65))
        self.engine = PaperTradingEngine(recorder=PaperTradeRecorder(self.dir), lifecycle=lifecycle)
        self.account = PaperAccount(self.engine, starting_capital=100_000.0, cost_model=OptionCostModel.zero())
        self.store = AllocationStore(AllocationSetting.from_percent(25))
        self.engine.allocation_provider = lambda *, timestamp, entry_price: self._budget(timestamp)

    def tearDown(self):
        self._tmp.cleanup()

    def _budget(self, timestamp):
        snap = self.account.snapshot(timestamp)
        return self.store.setting.budget(balance=snap.balance, available_cash=snap.available_cash).budget

    def open(self, strategy=A, price=100.0, direction="LONG"):
        return self.engine.open_position(strategy_id=strategy, direction=direction, symbol=SYM,
                                         entry_price=price, timestamp=T0)

    def test_entry_uses_the_chosen_allocation_not_the_lifecycle_default(self):
        trade = self.open()
        self.assertEqual((trade.position.lots, trade.position.quantity), (3, 195))
        snap = self.account.snapshot(T0 + 1, {A: 100.0})
        self.assertEqual(snap.deployed, 19_500.0)
        self.assertEqual(snap.available_cash, 80_500.0)
        self.assertEqual(snap.balance, 100_000.0)

    def test_changing_the_setting_changes_the_next_entry(self):
        self.store.set(AllocationSetting.from_percent(50))
        self.assertEqual(self.open().position.lots, 7)          # 50,000 // 6,500
        self.store.set(AllocationSetting.from_amount(13_000.0))
        self.assertEqual(self.open(PaperStrategyId.STRATEGY_B).position.lots, 2)

    def test_second_entry_is_limited_by_cash_already_deployed(self):
        self.store.set(AllocationSetting.from_percent(80))      # asks for 80,000 each time
        first = self.open()
        self.assertEqual(first.position.lots, 12)               # 80,000 // 6,500 = 12 lots = 78,000
        second = self.open(PaperStrategyId.STRATEGY_B)          # only 22,000 is still free
        self.assertEqual(second.position.lots, 3)               # 22,000 // 6,500
        snap = self.account.snapshot(T0 + 1, {A: 100.0, PaperStrategyId.STRATEGY_B: 100.0})
        self.assertEqual(snap.deployed, 97_500.0)
        self.assertEqual(snap.available_cash, 2_500.0)
        with self.assertRaises(ValueError) as caught:           # 2,500 cannot buy another lot
            self.engine.open_position(strategy_id=PaperStrategyId.MODULE_CONFLUENCE, direction="LONG",
                                      symbol=SYM, entry_price=100.0, timestamp=T0 + 120)
        self.assertEqual(len(self.engine.all_trades()), 2, "the refused entry left no half-open trade")

    def test_budget_below_one_lot_refuses_the_trade_with_a_clear_message(self):
        self.store.set(AllocationSetting.from_amount(6_000.0))
        with self.assertRaises(ValueError) as caught:
            self.open()
        self.assertIn("cannot buy one lot", str(caught.exception))
        self.assertIn("short by Rs 500.00", str(caught.exception))
        self.assertEqual(self.engine.all_trades(), ())

    def test_defaults_30_percent_stop_below_entry_for_calls_and_puts(self):
        self.assertEqual(BuyerLifecycleConfig().stop_loss_pct, 0.30)
        call = self.open(direction="LONG")
        put = self.open(PaperStrategyId.STRATEGY_B, direction="SHORT")
        for trade in (call, put):
            self.assertAlmostEqual(trade.position.stop_loss, 70.0)      # 30% below the premium paid
            self.assertAlmostEqual(trade.position.target, 190.0)        # 3R on that risk
            self.assertLess(trade.position.stop_loss, trade.position.entry_price,
                            "a bought put loses when its premium falls, so its stop is below entry")


class RejectionJournalTests(unittest.TestCase):
    def test_a_refused_entry_is_journaled_with_the_reason(self):
        with tempfile.TemporaryDirectory() as tmp:
            lifecycle = BuyerOptionTradeLifecycle(BuyerLifecycleConfig(allocation=15_000.0, lot_size=65))
            engine = PaperTradingEngine(recorder=PaperTradeRecorder(tmp), lifecycle=lifecycle)

            class TooSmall:
                def prepare_entry(self, **kwargs):
                    raise ValueError(sizing_warning(calculate_lots(5_000.0, 100.0, 65)))

            coordinator = PaperExecutionCoordinator(adapter=TooSmall(), engine=engine)
            signal = PaperSignal(strategy_id=A, direction="LONG", timestamp=T0 - 180, index=4, reason="t")
            attempt = coordinator.process_signal(signal=signal, underlying_price=24500.0, option_quote={},
                                                 decision_timestamp=T0)
            self.assertIsNone(attempt.trade)
            rows = (Path(tmp) / "rejections.csv").read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(rows), 2)
            self.assertIn("cannot buy one lot", rows[1])
            coordinator.process_signal(signal=signal, underlying_price=24500.0, option_quote={},
                                       decision_timestamp=T0)       # duplicate: not journaled again
            self.assertEqual(len((Path(tmp) / "rejections.csv").read_text(encoding="utf-8").splitlines()), 2)


if __name__ == "__main__":
    unittest.main()
