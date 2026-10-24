import csv
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from backtest.option_trade_lifecycle import OptionExitReason
from paper_trading.engine import PaperTradingEngine, PaperStrategyId
from paper_trading.market_data_pipeline import PaperMarketDataPipeline
from paper_trading.recorder import PaperTradeRecorder
from paper_trading.signals import PaperSignal


TZ = ZoneInfo("Asia/Kolkata")


class PaperTradeRecorderTests(unittest.TestCase):
    def test_pipeline_persists_emitted_signal(self):
        with tempfile.TemporaryDirectory() as directory:
            recorder = PaperTradeRecorder(directory)
            emitted = []

            def evaluator(bars, *, paper_config):
                signal = PaperSignal(
                    strategy_id=PaperStrategyId.STRATEGY_A,
                    direction="LONG",
                    timestamp=bars[-1].timestamp,
                    index=len(bars) - 1,
                    reason="TEST_SIGNAL",
                )
                emitted.append(signal)
                return [signal]

            pipeline = PaperMarketDataPipeline(
                resolution_minutes=1,
                signal_evaluator=evaluator,
                recorder=recorder,
            )
            start = int(datetime(2026, 10, 12, 9, 15, tzinfo=TZ).timestamp())
            pipeline.on_message({
                "symbol": "NSE:NIFTY50-INDEX",
                "last_traded_time": start + 5,
                "ltp": 100.0,
            })
            pipeline.on_message({
                "symbol": "NSE:NIFTY50-INDEX",
                "last_traded_time": start + 65,
                "ltp": 101.0,
            })

            with recorder.signals_path.open(newline="", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))

            self.assertEqual(len(emitted), 1)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["symbol"], "NSE:NIFTY50-INDEX")
            self.assertEqual(rows[0]["strategy_id"], PaperStrategyId.STRATEGY_A.value)
            self.assertEqual(rows[0]["direction"], "LONG")
            self.assertEqual(rows[0]["reason"], "TEST_SIGNAL")

    def test_engine_persists_entry_and_stop_loss_exit(self):
        with tempfile.TemporaryDirectory() as directory:
            recorder = PaperTradeRecorder(directory)
            engine = PaperTradingEngine(recorder=recorder)

            trade = engine.open_position(
                strategy_id=PaperStrategyId.STRATEGY_A,
                direction="LONG",
                symbol="NSE:NIFTY26OCT26000CE",
                entry_price=100.0,
                timestamp=1_791_887_000,
            )
            self.assertIsNotNone(trade)

            exits = engine.process_option_candle(
                strategy_id=PaperStrategyId.STRATEGY_A,
                timestamp=1_791_887_060,
                option_high=101.0,
                option_low=79.0,
                option_close=85.0,
                underlying_close=25000.0,
                kama_value=24900.0,
            )

            self.assertEqual(len(exits), 1)
            self.assertEqual(exits[0].reason, OptionExitReason.STOP_LOSS)
            with recorder.trades_path.open(newline="", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))

            self.assertEqual([row["event_type"] for row in rows], ["ENTRY", "EXIT"])
            self.assertEqual(rows[0]["symbol"], "NSE:NIFTY26OCT26000CE")
            self.assertEqual(rows[1]["exit_reason"], "STOP_LOSS")
            self.assertEqual(float(rows[1]["gross_pnl"]), -2600.0)
            self.assertEqual(rows[1]["closed"], "True")

    def test_recorder_appends_across_instances_without_duplicate_headers(self):
        with tempfile.TemporaryDirectory() as directory:
            first = PaperTradeRecorder(directory)
            signal = PaperSignal(
                strategy_id=PaperStrategyId.STRATEGY_B,
                direction="SHORT",
                timestamp=123,
                index=4,
                reason="TEST",
            )
            first.record_signal(signal, symbol="NSE:NIFTY50-INDEX")

            second = PaperTradeRecorder(directory)
            second.record_signal(signal, symbol="NSE:NIFTY50-INDEX")

            with Path(directory, "signals.csv").open(
                newline="", encoding="utf-8"
            ) as handle:
                rows = list(csv.DictReader(handle))

            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0]["signal_timestamp"], "123")
            self.assertEqual(rows[1]["direction"], "SHORT")


if __name__ == "__main__":
    unittest.main()
