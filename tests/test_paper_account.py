"""Net liquidation value: starting balance + realised + unrealised - costs."""
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from paper_trading.account import PaperAccount
from paper_trading.buyer_lifecycle import BuyerLifecycleConfig, BuyerOptionTradeLifecycle
from paper_trading.costs import OptionCostModel
from paper_trading.engine import PaperStrategyId, PaperTradingEngine
from paper_trading.recorder import PaperTradeRecorder
from paper_trading.recovery import restore_engine_from_journal

IST = ZoneInfo("Asia/Kolkata")
A, B = PaperStrategyId.STRATEGY_A, PaperStrategyId.STRATEGY_B


def at(h, m, day=21):
    return int(datetime(2026, 10, day, h, m, tzinfo=IST).timestamp())


def engine_for(directory):
    lifecycle = BuyerOptionTradeLifecycle(BuyerLifecycleConfig(allocation=25_000.0, lot_size=50))
    return PaperTradingEngine(recorder=PaperTradeRecorder(directory), lifecycle=lifecycle)


def enter(engine, strategy, ts, price=100.0):
    return engine.open_position(strategy_id=strategy, direction="LONG", symbol="NSE:NIFTY2610024500CE",
                                entry_price=price, timestamp=ts)


def stop_out(engine, strategy, ts):
    engine.process_option_candle(strategy_id=strategy, timestamp=ts, option_high=101.0, option_low=79.0,
                                 option_close=85.0, underlying_close=24500.0, kama_value=None)


class AccountTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.engine = engine_for(self.dir)

    def tearDown(self):
        self._tmp.cleanup()

    def account(self, cost=None):
        return PaperAccount(self.engine, starting_capital=100_000.0,
                            cost_model=cost or OptionCostModel.zero())

    def test_fresh_account_equals_starting_capital(self):
        snap = self.account().snapshot(at(10, 0))
        self.assertEqual((snap.equity, snap.day_pnl, snap.opening_equity), (100_000.0, 0.0, 100_000.0))

    def test_owner_example_95000_balance_plus_25000_open_profit_is_120000(self):
        enter(self.engine, A, at(10, 0)); stop_out(self.engine, A, at(10, 1))   # realised -5,000
        enter(self.engine, B, at(10, 2))                                        # 250 units at 100
        snap = self.account().snapshot(at(10, 3), {B: 200.0})                   # +25,000 running
        self.assertEqual(snap.realized_pnl, -5_000.0)
        self.assertEqual(snap.unrealized_pnl, 25_000.0)
        self.assertEqual(snap.equity, 120_000.0)
        self.assertEqual(snap.day_pnl, 20_000.0)

    def test_open_loss_lowers_equity_live(self):
        enter(self.engine, A, at(10, 0))
        acct = self.account()
        self.assertEqual(acct.snapshot(at(10, 1), {A: 90.0}).equity, 97_500.0)
        self.assertEqual(acct.snapshot(at(10, 2), {A: 110.0}).equity, 102_500.0)

    def test_missing_mark_is_reported_not_valued_at_zero(self):
        enter(self.engine, A, at(10, 0))
        snap = self.account().snapshot(at(10, 1), {})
        self.assertEqual(snap.marks_missing, (A,))
        for bad in (0.0, -1.0, float("nan")):
            self.assertEqual(self.account().snapshot(at(10, 1), {A: bad}).marks_missing, (A,))

    def test_costs_match_hand_calculation_and_reduce_equity(self):
        model = OptionCostModel()
        buy = model.order_cost(side="BUY", price=100.0, quantity=250)
        sell = model.order_cost(side="SELL", price=80.0, quantity=250)
        # BUY 25,000 turnover: 20 + 8.8825 + 0.025 + GST 5.20335 + stamp 0.75 = 34.86085
        self.assertAlmostEqual(buy, 34.86085, places=4)
        # SELL 20,000 turnover: 20 + 7.106 + 0.02 + GST 4.88268 + STT 30 = 62.00868
        self.assertAlmostEqual(sell, 62.00868, places=4)
        enter(self.engine, A, at(10, 0)); stop_out(self.engine, A, at(10, 1))
        snap = self.account(model).snapshot(at(10, 5))
        self.assertAlmostEqual(snap.costs, buy + sell, places=4)
        self.assertAlmostEqual(snap.equity, 100_000.0 - 5_000.0 - buy - sell, places=4)

    def test_open_trade_counts_only_its_entry_cost(self):
        model = OptionCostModel()
        enter(self.engine, A, at(10, 0))
        snap = self.account(model).snapshot(at(10, 1), {A: 100.0})
        self.assertAlmostEqual(snap.costs, model.order_cost(side="BUY", price=100.0, quantity=250), places=4)

    def test_opening_balance_rolls_forward_net_of_costs(self):
        model = OptionCostModel()
        enter(self.engine, A, at(10, 0, day=20)); stop_out(self.engine, A, at(10, 1, day=20))
        yesterday_net = -5_000.0 - model.order_cost(side="BUY", price=100.0, quantity=250) \
                                 - model.order_cost(side="SELL", price=80.0, quantity=250)
        snap = self.account(model).snapshot(at(10, 0))                  # next day
        self.assertAlmostEqual(snap.opening_equity, 100_000.0 + yesterday_net, places=4)
        self.assertAlmostEqual(snap.day_pnl, 0.0, places=6)

    def test_partial_profit_taking_is_realised_and_the_rest_marked(self):
        enter(self.engine, A, at(10, 0))
        self.engine.process_option_candle(strategy_id=A, timestamp=at(10, 1), option_high=165.0,
                                          option_low=95.0, option_close=150.0, underlying_close=24500.0,
                                          kama_value=None)               # 3R: half out at 160
        snap = self.account().snapshot(at(10, 2), {A: 150.0})
        record = self.engine.open_trade(A)
        self.assertGreater(snap.realized_pnl, 0)
        expected_unrealized = (150.0 - 100.0) * record.position.remaining_quantity
        self.assertAlmostEqual(snap.unrealized_pnl, expected_unrealized)

    def test_equity_is_identical_after_a_restart(self):
        enter(self.engine, A, at(10, 0)); stop_out(self.engine, A, at(10, 1))
        enter(self.engine, B, at(10, 2))
        before = self.account(OptionCostModel()).snapshot(at(10, 3), {B: 120.0})
        fresh = engine_for(self.dir)
        restore_engine_from_journal(fresh, today=datetime(2026, 10, 21, 10, 5, tzinfo=IST))
        after = PaperAccount(fresh, starting_capital=100_000.0, cost_model=OptionCostModel()
                             ).snapshot(at(10, 3), {B: 120.0})
        self.assertAlmostEqual(before.equity, after.equity, places=6)
        self.assertAlmostEqual(before.day_pnl, after.day_pnl, places=6)

    def test_invalid_inputs(self):
        with self.assertRaises(ValueError):
            PaperAccount(self.engine, starting_capital=0)
        with self.assertRaises(ValueError):
            OptionCostModel(brokerage_per_order=-1)
        with self.assertRaises(ValueError):
            OptionCostModel().order_cost(side="HOLD", price=1.0, quantity=1)


if __name__ == "__main__":
    unittest.main()
