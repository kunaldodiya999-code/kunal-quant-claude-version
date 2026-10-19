import unittest

from backtest.option_trade_lifecycle import (
    OptionExitReason,
    OptionTradeDirection,
)
from paper_trading.engine import (
    PaperEngineConfig,
    PaperStrategyId,
    PaperTradingEngine,
)


class PaperTradingEngineTests(unittest.TestCase):
    def test_strategies_have_independent_positions_and_logs(self):
        engine = PaperTradingEngine()
        a = engine.open_position(
            strategy_id=PaperStrategyId.STRATEGY_A,
            direction=OptionTradeDirection.LONG,
            symbol="NSE:NIFTY26000CE",
            entry_price=100.0,
            timestamp=100,
        )
        b = engine.open_position(
            strategy_id=PaperStrategyId.STRATEGY_B,
            direction=OptionTradeDirection.SHORT,
            symbol="NSE:NIFTY26000PE",
            entry_price=100.0,
            timestamp=101,
        )

        self.assertIsNotNone(a)
        self.assertIsNotNone(b)
        self.assertIsNot(a.position, b.position)
        self.assertEqual(len(engine.trades(PaperStrategyId.STRATEGY_A)), 1)
        self.assertEqual(len(engine.trades(PaperStrategyId.STRATEGY_B)), 1)
        self.assertEqual(len(engine.trades(PaperStrategyId.MODULE_CONFLUENCE)), 0)

    def test_disabled_strategy_cannot_open_position(self):
        engine = PaperTradingEngine(
            PaperEngineConfig(strategy_b_enabled=False)
        )
        result = engine.open_position(
            strategy_id=PaperStrategyId.STRATEGY_B,
            direction="LONG",
            symbol="NSE:NIFTY26000CE",
            entry_price=100.0,
            timestamp=100,
        )
        self.assertIsNone(result)
        self.assertEqual(engine.trades(PaperStrategyId.STRATEGY_B), ())

    def test_one_active_position_per_strategy(self):
        engine = PaperTradingEngine()
        first = engine.open_position(
            strategy_id=PaperStrategyId.STRATEGY_A,
            direction="LONG",
            symbol="NSE:NIFTY26000CE",
            entry_price=100.0,
            timestamp=100,
        )
        second = engine.open_position(
            strategy_id=PaperStrategyId.STRATEGY_A,
            direction="SHORT",
            symbol="NSE:NIFTY26000PE",
            entry_price=100.0,
            timestamp=101,
        )
        self.assertIsNotNone(first)
        self.assertIsNone(second)
        self.assertEqual(len(engine.trades(PaperStrategyId.STRATEGY_A)), 1)

    def test_exit_processing_only_changes_selected_strategy(self):
        engine = PaperTradingEngine()
        a = engine.open_position(
            strategy_id=PaperStrategyId.STRATEGY_A,
            direction="LONG",
            symbol="NSE:NIFTY26000CE",
            entry_price=100.0,
            timestamp=100,
        )
        b = engine.open_position(
            strategy_id=PaperStrategyId.STRATEGY_B,
            direction="LONG",
            symbol="NSE:NIFTY26000CE",
            entry_price=100.0,
            timestamp=100,
        )

        exits = engine.process_option_candle(
            strategy_id=PaperStrategyId.STRATEGY_A,
            timestamp=160,
            option_high=101.0,
            option_low=79.0,
            option_close=85.0,
            underlying_close=25000.0,
            kama_value=24900.0,
        )

        self.assertEqual(len(exits), 1)
        self.assertEqual(exits[0].reason, OptionExitReason.STOP_LOSS)
        self.assertTrue(a.closed)
        self.assertFalse(b.closed)
        self.assertEqual(len(a.exits), 1)
        self.assertEqual(len(b.exits), 0)

    def test_closed_strategy_can_open_a_new_trade(self):
        engine = PaperTradingEngine()
        engine.open_position(
            strategy_id=PaperStrategyId.STRATEGY_A,
            direction="LONG",
            symbol="NSE:NIFTY26000CE",
            entry_price=100.0,
            timestamp=100,
        )
        engine.process_option_candle(
            strategy_id=PaperStrategyId.STRATEGY_A,
            timestamp=160,
            option_high=101.0,
            option_low=79.0,
            option_close=85.0,
            underlying_close=25000.0,
            kama_value=24900.0,
        )
        next_trade = engine.open_position(
            strategy_id=PaperStrategyId.STRATEGY_A,
            direction="SHORT",
            symbol="NSE:NIFTY26000PE",
            entry_price=100.0,
            timestamp=220,
        )
        self.assertIsNotNone(next_trade)
        self.assertEqual(len(engine.trades(PaperStrategyId.STRATEGY_A)), 2)

    def test_unknown_strategy_is_rejected(self):
        engine = PaperTradingEngine()
        with self.assertRaises(ValueError):
            engine.open_position(
                strategy_id="UNKNOWN",
                direction="LONG",
                symbol="NSE:NIFTY26000CE",
                entry_price=100.0,
                timestamp=100,
            )


    def test_duplicate_or_out_of_order_option_candle_is_rejected(self):
        engine = PaperTradingEngine()
        engine.open_position(
            strategy_id=PaperStrategyId.STRATEGY_A,
            direction="LONG",
            symbol="NSE:NIFTY26000CE",
            entry_price=100.0,
            timestamp=100,
        )
        kwargs = dict(
            strategy_id=PaperStrategyId.STRATEGY_A,
            option_high=101.0,
            option_low=99.0,
            option_close=100.0,
            underlying_close=25000.0,
            kama_value=24900.0,
        )
        engine.process_option_candle(timestamp=160, **kwargs)
        with self.assertRaises(ValueError):
            engine.process_option_candle(timestamp=160, **kwargs)
        with self.assertRaises(ValueError):
            engine.process_option_candle(timestamp=150, **kwargs)

    def test_entry_timestamp_candle_is_not_processed(self):
        engine = PaperTradingEngine()
        engine.open_position(
            strategy_id=PaperStrategyId.STRATEGY_A,
            direction="LONG",
            symbol="NSE:NIFTY26000CE",
            entry_price=100.0,
            timestamp=100,
        )
        with self.assertRaises(ValueError):
            engine.process_option_candle(
                strategy_id=PaperStrategyId.STRATEGY_A,
                timestamp=100,
                option_high=101.0,
                option_low=99.0,
                option_close=100.0,
                underlying_close=25000.0,
                kama_value=24900.0,
            )

if __name__ == "__main__":
    unittest.main()
