"""Risk/execution decomposition audit for Opening Breakout V2.

Reporting-only. Reuses the existing V2 backtest and does not alter strategy,
execution, sizing, or cost assumptions.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import date, datetime
from pathlib import Path
import sqlite3
import sys
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backtest.opening_breakout_v2_economic_attribution import attribute_trade_economics
from backtest.fyers_option_candles import FyersOptionCandleLoader
from backtest.opening_breakout_v2_multi_session import run_multi_session_backtest
from config.settings import DATABASE_PATH
from execution.opening_breakout_v2_execution import V2ExecutionPolicy
from research.opening_breakout_1m_v2 import Candle, IndicatorSnapshot, V2Config
from strategies.option_contract_resolver import OptionContractResolver

IST = ZoneInfo("Asia/Kolkata")


def epoch_seconds(value: str) -> int:
    return int(datetime.fromisoformat(value).replace(tzinfo=IST).timestamp())


def load_nifty_candles(start_ts: int, end_ts: int) -> list[Candle]:
    with sqlite3.connect(DATABASE_PATH) as connection:
        rows = connection.execute(
            """
            SELECT c.timestamp, c.open, c.high, c.low, c.close
            FROM candles c
            JOIN instruments i ON i.id = c.instrument_id
            WHERE i.broker = 'FYERS'
              AND i.symbol = 'NSE:NIFTY50-INDEX'
              AND c.resolution = '1'
              AND c.timestamp BETWEEN ? AND ?
            ORDER BY c.timestamp
            """,
            (start_ts, end_ts),
        ).fetchall()
    return [Candle(int(ts), float(o), float(h), float(l), float(c)) for ts, o, h, l, c in rows]


def empty_indicator_provider(timestamp: int, candle: Candle) -> IndicatorSnapshot:
    return IndicatorSnapshot()


def decompose_trade(trade, entry_buffer: float, exit_buffer: float, intended_risk: float) -> dict:
    attribution = attribute_trade_economics(
        trade,
        intended_risk=intended_risk,
        trade_date=datetime.fromtimestamp(
            trade.event.trigger_timestamp, tz=IST
        ).date(),
    )
    theoretical_label = (
        "STOP"
        if attribution.exit_reason == "STOP_LOSS"
        else "TARGET"
        if attribution.exit_reason == "TARGET"
        else "UNAVAILABLE"
    )
    return {
        "signal": attribution.signal_price,
        "entry": attribution.entry_price,
        "stop": attribution.stop_price,
        "target": attribution.target_price,
        "exit": attribution.exit_price,
        "qty": attribution.quantity,
        "exit_reason": attribution.exit_reason,
        "theoretical_exit": attribution.theoretical_exit,
        "theoretical_label": theoretical_label,
        "theoretical_strategy_pnl": attribution.theoretical_strategy_pnl,
        "entry_execution_impact": attribution.entry_execution_impact,
        "exit_execution_impact": attribution.exit_execution_impact,
        "gross_pnl": attribution.gross_pnl,
        "cost": attribution.total_cost,
        "brokerage": attribution.brokerage,
        "exchange_transaction": attribution.exchange_transaction,
        "stt": attribution.stt,
        "sebi": attribution.sebi,
        "stamp_duty": attribution.stamp_duty,
        "ipft": attribution.ipft,
        "gst": attribution.gst,
        "net_pnl": attribution.net_pnl,
        "intended_risk": attribution.intended_risk,
        "strategy_risk": attribution.strategy_risk,
        "realized_r": attribution.realized_r,
        "net_r": attribution.net_r,
        "execution_adjusted_from_signal": attribution.execution_adjusted_from_signal,
        "entry_buffer": entry_buffer,
        "exit_buffer": exit_buffer,
    }

def summarize(rows: list[dict]) -> dict:
    def total(key: str) -> float:
        return sum(float(row[key]) for row in rows)

    theoretical_strategy = sum(
        float(row["theoretical_strategy_pnl"])
        for row in rows
        if row["theoretical_strategy_pnl"] is not None
    )
    known_entry_impact = sum(
        float(row["entry_execution_impact"])
        for row in rows
        if row["exit_reason"] != "FORCE_EXIT"
    )
    force_entry_impact = sum(
        float(row["entry_execution_impact"])
        for row in rows
        if row["exit_reason"] == "FORCE_EXIT"
    )
    exit_impact_known = sum(
        float(row["exit_execution_impact"])
        for row in rows
        if row["exit_execution_impact"] is not None
    )
    known_gross = theoretical_strategy + known_entry_impact + exit_impact_known
    force_exit_gross = sum(
        float(row["gross_pnl"])
        for row in rows
        if row["exit_reason"] == "FORCE_EXIT"
    )
    force_exit_residual = force_exit_gross - force_entry_impact
    return {
        "count": len(rows),
        "gross": total("gross_pnl"),
        "cost": total("cost"),
        "brokerage": total("brokerage"),
        "exchange_transaction": total("exchange_transaction"),
        "stt": total("stt"),
        "sebi": total("sebi"),
        "stamp_duty": total("stamp_duty"),
        "ipft": total("ipft"),
        "gst": total("gst"),
        "net": total("net_pnl"),
        "theoretical_strategy": theoretical_strategy,
        "entry_impact_known": known_entry_impact,
        "entry_impact_force": force_entry_impact,
        "exit_impact_known": exit_impact_known,
        "known_gross": known_gross,
        "force_exit_gross": force_exit_gross,
        "force_exit_residual": force_exit_residual,
        "strategy_risk": total("strategy_risk"),
        "intended_risk": total("intended_risk"),
        "avg_cost": total("cost") / len(rows) if rows else 0.0,
        "exit_reasons": Counter(row["exit_reason"] for row in rows),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--from", dest="start", required=True)
    parser.add_argument("--to", dest="end", required=True)
    parser.add_argument("--capital", type=float, default=100000.0)
    parser.add_argument("--risk", type=float, default=2000.0)
    args = parser.parse_args()

    candles = load_nifty_candles(epoch_seconds(args.start), epoch_seconds(args.end))
    config = V2Config(
        trade_instrument="CALL",
        market_bias="NEUTRAL",
        selected_timeframes=("1M",),
        selected_triggers=("CANDLE_HIGH",),
        filter_open_high=False,
        filter_open_low=False,
        custom_sl_points=20.0,
        tp_mode="RR_RATIO",
        rr_multiplier=2.0,
        risk_per_trade_value=args.risk,
        capital_allocation_percent=100.0,
    )
    policy = V2ExecutionPolicy(
        entry_buffer_points=1.0,
        max_slippage_points=2.0,
        fill_timeout_seconds=60,
    )
    result = run_multi_session_backtest(
        candles=candles,
        config=config,
        resolver=OptionContractResolver(DATABASE_PATH),
        option_loader=FyersOptionCandleLoader(DATABASE_PATH),
        execution_policy=policy,
        capital=args.capital,
        indicator_provider=empty_indicator_provider,
    )

    closed = [trade for trade in result.trades if trade.status == "CLOSED"]
    rows = [
        decompose_trade(
            trade,
            entry_buffer=policy.entry_buffer_points,
            exit_buffer=policy.exit_buffer_points,
            intended_risk=args.risk,
        )
        for trade in closed
    ]
    summary = summarize(rows)

    print("=" * 100)
    print("KUNAL QUANT — OPENING BREAKOUT V2 RISK / EXECUTION DECOMPOSITION")
    print("=" * 100)
    print(f"Closed trades                 : {summary['count']}")
    print(f"Intended risk / trade         : {args.risk:.2f}")
    print(f"Total intended risk           : {summary['intended_risk']:.2f}")
    print(f"Total strategy stop risk      : {summary['strategy_risk']:.2f}")
    print(f"Theoretical strategy P&L      : {summary['theoretical_strategy']:.2f}")
    print(f"Entry execution impact (known): {summary['entry_impact_known']:.2f}")
    print(f"Entry impact on force exits   : {summary['entry_impact_force']:.2f}")
    print(f"Exit execution impact (known) : {summary['exit_impact_known']:.2f}")
    print(f"Known decomposed gross P&L    : {summary['known_gross']:.2f}")
    print(f"Force-exit gross P&L          : {summary['force_exit_gross']:.2f}")
    print(f"Force-exit residual from entry: {summary['force_exit_residual']:.2f}")
    print(f"Gross P&L                     : {summary['gross']:.2f}")
    print(f"Broker costs                  : {summary['cost']:.2f}")
    print(f"  Brokerage                   : {summary['brokerage']:.2f}")
    print(f"  Exchange transaction        : {summary['exchange_transaction']:.2f}")
    print(f"  STT                         : {summary['stt']:.2f}")
    print(f"  SEBI                        : {summary['sebi']:.2f}")
    print(f"  Stamp duty                  : {summary['stamp_duty']:.2f}")
    print(f"  IPFT                        : {summary['ipft']:.2f}")
    print(f"  GST                         : {summary['gst']:.2f}")
    print(f"Net P&L                       : {summary['net']:.2f}")
    print(f"Average cost / trade          : {summary['avg_cost']:.2f}")
    print()
    print("EXIT REASONS")
    for reason, count in sorted(summary["exit_reasons"].items()):
        print(f"  {count:4d}  {reason}")
    print()
    print("RISK / EXECUTION DISTRIBUTION")
    print(f"  strategy risk / 75-lot trade: {20.0 * 75:.2f}")
    print(f"  strategy risk / 65-lot trade: {20.0 * 65:.2f}")
    print(f"  stop loss with 2-point exit buffer: 22 points")
    print()
    print("TRADE-LEVEL DECOMPOSITION")
    print(
        "  columns: signal_ts symbol qty signal entry stop target exit reason "
        "theoretical_strategy entry_impact exit_impact gross cost net realized_R net_R"
    )
    for trade, row in zip(closed, rows):
        def fmt(value):
            return "NA" if value is None else f"{value:.2f}"

        print(
            f"  {trade.event.trigger_timestamp} {trade.contract.symbol} "
            f"qty={row['qty']} signal={row['signal']:.2f} entry={row['entry']:.2f} "
            f"stop={row['stop']:.2f} target={row['target']:.2f} exit={row['exit']:.2f} "
            f"{row['exit_reason']} theoretical={fmt(row['theoretical_strategy_pnl'])} "
            f"entry_impact={row['entry_execution_impact']:.2f} "
            f"exit_impact={fmt(row['exit_execution_impact'])} "
            f"gross={row['gross_pnl']:.2f} cost={row['cost']:.2f} "
            f"brokerage={row['brokerage']:.2f} exchange={row['exchange_transaction']:.2f} "
            f"stt={row['stt']:.2f} sebi={row['sebi']:.2f} stamp={row['stamp_duty']:.2f} "
            f"ipft={row['ipft']:.2f} gst={row['gst']:.2f} net={row['net_pnl']:.2f} "
            f"realized_R={row['realized_r']:.3f} net_R={row['net_r']:.3f}"
        )


if __name__ == "__main__":
    main()
