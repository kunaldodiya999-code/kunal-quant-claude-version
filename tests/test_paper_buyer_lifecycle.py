import unittest

from backtest.option_trade_lifecycle import OptionExitReason, OptionTradeDirection
from paper_trading.buyer_lifecycle import BuyerLifecycleConfig, BuyerOptionTradeLifecycle


class BuyerOptionTradeLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.lifecycle = BuyerOptionTradeLifecycle(
            BuyerLifecycleConfig(allocation=15000, lot_size=25, stop_loss_pct=.20, target_rr=3)
        )

    def test_short_signal_is_bought_pe_with_long_premium_stop_target_and_pnl(self):
        p = self.lifecycle.create_position(
            strategy_id="KTMI_LONG_SHORT_SPEED", direction=OptionTradeDirection.SHORT,
            symbol="NSE:NIFTY2610025000PE", entry_price=100,
        )
        self.assertEqual(p.stop_loss, 80)
        self.assertEqual(p.target, 160)
        self.assertEqual(p.quantity, 150)
        exits = self.lifecycle.process_candle(
            position=p, timestamp=200, option_high=105, option_low=79,
            option_close=82, underlying_close=25000, kama_value=25100,
        )
        self.assertEqual(exits[0].reason, OptionExitReason.STOP_LOSS)
        self.assertEqual(exits[0].pnl, -3000)

    def test_target_partially_exits_bought_ce_and_leaves_lot(self):
        p = self.lifecycle.create_position(
            strategy_id="A", direction=OptionTradeDirection.LONG,
            symbol="NSE:NIFTY2610025000CE", entry_price=100,
        )
        exits = self.lifecycle.process_candle(
            position=p, timestamp=200, option_high=161, option_low=99,
            option_close=158, underlying_close=25000, kama_value=24900,
        )
        self.assertEqual(exits[0].reason, OptionExitReason.TARGET_3R)
        self.assertEqual(exits[0].price, 160)
        self.assertEqual(p.remaining_lots, 2)
        self.assertFalse(p.closed)

    def test_kama_exit_uses_underlying_direction_but_premium_pnl(self):
        p = self.lifecycle.create_position(
            strategy_id="B", direction=OptionTradeDirection.SHORT,
            symbol="NSE:NIFTY2610025000PE", entry_price=100,
        )
        exits = self.lifecycle.process_candle(
            position=p, timestamp=200, option_high=110, option_low=101,
            option_close=108, underlying_close=25200, kama_value=25100,
        )
        self.assertEqual(exits[0].reason, OptionExitReason.KAMA_EXIT)
        self.assertEqual(exits[0].pnl, 8 * p.quantity)

    def test_stop_wins_when_stop_and_target_both_touched(self):
        p = self.lifecycle.create_position(
            strategy_id="A", direction=OptionTradeDirection.LONG,
            symbol="NSE:NIFTY2610025000CE", entry_price=100,
        )
        exits = self.lifecycle.process_candle(
            position=p, timestamp=200, option_high=170, option_low=79,
            option_close=120, underlying_close=25000, kama_value=24900,
        )
        self.assertEqual(len(exits), 1)
        self.assertEqual(exits[0].reason, OptionExitReason.STOP_LOSS)

    def test_rejects_unaffordable_lot_and_bad_prices(self):
        with self.assertRaises(ValueError):
            self.lifecycle.create_position(
                strategy_id="A", direction=OptionTradeDirection.LONG,
                symbol="CE", entry_price=1000,
            )
        with self.assertRaises(ValueError):
            self.lifecycle.create_position(
                strategy_id="A", direction=OptionTradeDirection.LONG,
                symbol="CE", entry_price=float("nan"),
            )


if __name__ == "__main__":
    unittest.main()
