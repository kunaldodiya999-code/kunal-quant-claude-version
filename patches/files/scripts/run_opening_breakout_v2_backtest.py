"""Configurable Opening Breakout V2 historical backtest with saved reports.

Research-only. Reads the local database, never contacts FYERS, never places
orders. Differences from ``run_opening_breakout_v2_multi_session.py``:

* every V2 setting is a command-line option (triggers, OH/OL, SL/TP, risk...);
* VWAP / Bollinger / KTMI / DMI triggers get real causal indicator values,
  warmed up on history *before* the test window (only the window is traded);
* no new entries after --entry-end (default 15:10); force exit stays 15:15;
* results are saved: trades.csv, equity_curve.csv, summary.json, config.json.

Example (PowerShell, from the KunalQuant folder):

    python scripts/run_opening_breakout_v2_backtest.py `
        --from 2026-08-21 --to 2026-09-23 `
        --instrument CALL --triggers CANDLE_HIGH --open-low
"""

from __future__ import annotations

import argparse
import csv
import json
import sqlite3
import sys
from dataclasses import asdict
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backtest.broker_cost_model import calculate_options_trade_costs, fyers_options_profile
from backtest.fyers_option_candles import FyersOptionCandleLoader
from backtest.opening_breakout_v2_indicators import V2IndicatorProvider
from backtest.opening_breakout_v2_multi_session import (
    run_multi_session_backtest,
    session_date,
)
from backtest.opening_breakout_v2_option_integration import database_lot_size
from config.settings import DATABASE_PATH, REPORTS_DIR
from execution.opening_breakout_v2_execution import V2ExecutionPolicy
from research.opening_breakout_1m_v2 import Candle, V2Config
from strategies.option_contract_resolver import OptionContractResolver

IST = ZoneInfo("Asia/Kolkata")
UNDERLYING_SYMBOL = "NSE:NIFTY50-INDEX"
TRIGGERS = (
    "CANDLE_HIGH", "CANDLE_LOW", "ABOVE_VWAP", "BELOW_VWAP",
    "CLOSE_ABOVE_UPPER_BB", "CLOSE_BELOW_LOWER_BB", "KTMI", "DMI",
)


TRADE_FIELDS = [
    "date", "signal_time", "direction", "instrument", "triggers", "contract", "expiry",
    "strike", "underlying_at_signal", "option_at_signal", "entry_time", "entry_price",
    "stop", "target", "final_stop", "exit_time", "exit_price", "exit_reason", "lots",
    "quantity", "gross_pnl", "costs", "net_pnl", "status",
]


def parse_day(value: str) -> date:
    return date.fromisoformat(value[:10])


def epoch(day: date, at: time) -> int:
    return int(datetime.combine(day, at, tzinfo=IST).timestamp())


def ist(timestamp: int | None) -> str:
    if timestamp is None:
        return ""
    return datetime.fromtimestamp(timestamp, tz=IST).strftime("%Y-%m-%d %H:%M:%S")


def load_underlying(
    database_path: Path, start_ts: int, end_ts: int
) -> tuple[list[Candle], list[float]]:
    with sqlite3.connect(database_path) as connection:
        rows = connection.execute(
            """
            SELECT c.timestamp, c.open, c.high, c.low, c.close, COALESCE(c.volume, 0)
            FROM candles c
            JOIN instruments i ON i.id = c.instrument_id
            WHERE i.broker = 'FYERS'
              AND i.symbol = ?
              AND c.resolution = '1'
              AND c.timestamp BETWEEN ? AND ?
            GROUP BY c.timestamp
            ORDER BY c.timestamp
            """,
            (UNDERLYING_SYMBOL, start_ts, end_ts),
        ).fetchall()
    candles = [Candle(int(r[0]), float(r[1]), float(r[2]), float(r[3]), float(r[4])) for r in rows]
    volumes = [float(r[5]) for r in rows]
    return candles, volumes


def before_entry_end(candles, end_hhmm: str) -> list[Candle]:
    """Drop candles after the entry cut-off; the 09:15 setup candle is kept."""
    end = time.fromisoformat(end_hhmm)
    return [c for c in candles if datetime.fromtimestamp(c.timestamp, tz=IST).time() <= end]


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    g = p.add_argument_group("window")
    g.add_argument("--from", dest="start", required=True, help="first trading date, YYYY-MM-DD")
    g.add_argument("--to", dest="end", required=True, help="last trading date, YYYY-MM-DD")
    g.add_argument("--warmup-days", type=int, default=15,
                   help="calendar days of history before --from used only to warm up indicators")
    g.add_argument("--database", type=Path, default=DATABASE_PATH)
    g.add_argument("--out-dir", type=Path, default=None,
                   help="report folder (default: data/reports/opening_breakout_v2/<run time>)")

    g = p.add_argument_group("strategy")
    g.add_argument("--instrument", choices=("CALL", "PUT"), default="CALL")
    g.add_argument("--bias", choices=("UP", "DOWN", "NEUTRAL"), default="NEUTRAL")
    g.add_argument("--triggers", default="CANDLE_HIGH",
                   help="comma list (AND-combined): " + ",".join(TRIGGERS))
    g.add_argument("--open-low", action="store_true", help="require OPEN=LOW setup (CALL side)")
    g.add_argument("--open-high", action="store_true", help="require OPEN=HIGH setup (PUT side)")
    g.add_argument("--tolerance", type=float, default=0.05, help="OPEN=LOW/HIGH tolerance in points")
    g.add_argument("--ktmi-call-buying", type=float, default=0.5)
    g.add_argument("--ktmi-call-momentum", type=float, default=0.5)
    g.add_argument("--ktmi-put-selling", type=float, default=0.5)
    g.add_argument("--ktmi-put-momentum", type=float, default=-0.5)
    g.add_argument("--dmi-length", type=int, default=14)
    g.add_argument("--adx-smoothing", type=int, default=14)
    g.add_argument("--dmi-plus", type=float, default=25.0)
    g.add_argument("--dmi-minus", type=float, default=25.0)
    g.add_argument("--adx", type=float, default=25.0)
    g.add_argument("--bb-length", type=int, default=20)
    g.add_argument("--bb-mult", type=float, default=2.0)

    g = p.add_argument_group("exits and risk")
    g.add_argument("--sl-mode", choices=("CUSTOM_POINTS", "CANDLE_1_LOW", "CANDLE_1_HIGH"),
                   default="CUSTOM_POINTS")
    g.add_argument("--sl-points", type=float, default=20.0, help="premium points below entry")
    g.add_argument("--tp-mode", choices=("OFF", "CUSTOM_POINTS", "RR_RATIO", "VALUE"), default="RR_RATIO")
    g.add_argument("--tp-points", type=float, default=20.0)
    g.add_argument("--tp-value", type=float, default=10000.0)
    g.add_argument("--rr", type=float, default=2.0)
    g.add_argument("--trailing", action="store_true", help="enable RR-step trailing (2R->0R, 3R->1R)")
    g.add_argument("--capital", type=float, default=100000.0)
    g.add_argument("--risk", type=float, default=2000.0, help="rupees risked per trade")
    g.add_argument("--allocation", type=float, default=100.0, help="max %% of capital per trade")

    g = p.add_argument_group("execution")
    g.add_argument("--entry-buffer", type=float, default=1.0)
    g.add_argument("--max-slippage", type=float, default=2.0)
    g.add_argument("--fill-timeout", type=int, default=60, help="seconds")
    g.add_argument("--entry-end", default="15:10", help="no new entries after this time (HH:MM)")
    return p


def config_from_args(args) -> V2Config:
    triggers = tuple(t.strip().upper() for t in args.triggers.split(",") if t.strip())
    unknown = [t for t in triggers if t not in TRIGGERS]
    if unknown:
        raise SystemExit(f"unknown trigger(s): {unknown}. Choose from {TRIGGERS}")
    return V2Config(
        trade_instrument=args.instrument,
        market_bias=args.bias,
        selected_timeframes=("1M",),
        selected_triggers=triggers,
        filter_open_low=args.open_low,
        filter_open_high=args.open_high,
        open_equal_tolerance_points=args.tolerance,
        ktmi_buy_call_buying_speed=args.ktmi_call_buying,
        ktmi_buy_call_momentum_speed=args.ktmi_call_momentum,
        ktmi_buy_put_selling_speed=args.ktmi_put_selling,
        ktmi_buy_put_momentum_speed=args.ktmi_put_momentum,
        dmi_length=args.dmi_length,
        dmi_adx_smoothing=args.adx_smoothing,
        dmi_buy_call_plus_di=args.dmi_plus,
        dmi_buy_put_minus_di=args.dmi_minus,
        dmi_adx_threshold=args.adx,
        sl_mode=args.sl_mode,
        custom_sl_points=args.sl_points,
        tp_mode=args.tp_mode,
        custom_tp_points=args.tp_points,
        tp_value_target=args.tp_value,
        rr_multiplier=args.rr,
        trailing_enabled=args.trailing,
        risk_per_trade_value=args.risk,
        capital_allocation_percent=args.allocation,
        entry_buffer_points=args.entry_buffer,
        max_slippage_points=args.max_slippage,
        fill_timeout_seconds=args.fill_timeout,
    )


def trade_row(trade) -> dict:
    costs = None
    if trade.status == "CLOSED":
        costs = calculate_options_trade_costs(
            entry_price=trade.entry.price,
            exit_price=trade.exit.price,
            quantity=trade.quantity,
            profile=fyers_options_profile(session_date(trade.event.trigger_timestamp)),
            gross_pnl=trade.gross_pnl,
        )
    return {
        "date": session_date(trade.event.trigger_timestamp).isoformat(),
        "signal_time": ist(trade.event.trigger_timestamp),
        "direction": trade.event.direction,
        "instrument": trade.event.instrument,
        "triggers": "+".join(trade.event.trigger_reasons),
        "contract": trade.contract.symbol,
        "expiry": str(trade.contract.expiry_date),
        "strike": trade.contract.strike,
        "underlying_at_signal": round(trade.signal_underlying_price, 2),
        "option_at_signal": round(trade.option_signal_price, 2),
        "entry_time": ist(trade.entry.timestamp),
        "entry_price": trade.entry.price,
        "stop": trade.stop_price,
        "target": trade.target_price,
        "final_stop": trade.final_stop_price,
        "exit_time": ist(trade.exit.timestamp),
        "exit_price": trade.exit.price,
        "exit_reason": trade.exit.reason,
        "lots": trade.lots,
        "quantity": trade.quantity,
        "gross_pnl": round(trade.gross_pnl, 2),
        "costs": round(costs.total_cost, 2) if costs else 0.0,
        "net_pnl": round(trade.gross_pnl - costs.total_cost, 2) if costs else 0.0,
        "status": trade.status,
    }


def run(args) -> dict:
    config = config_from_args(args)
    start_day, end_day = parse_day(args.start), parse_day(args.end)
    if end_day < start_day:
        raise SystemExit("--to must be on/after --from")
    if not args.database.exists():
        raise SystemExit(f"database not found: {args.database}")

    window_start = epoch(start_day, time(0, 0))
    window_end = epoch(end_day, time(23, 59))
    history_start = epoch(start_day - timedelta(days=args.warmup_days), time(0, 0))

    all_candles, volumes = load_underlying(args.database, history_start, window_end)
    window = [c for c in all_candles if c.timestamp >= window_start]
    if len(window) < 2:
        raise SystemExit("not enough NIFTY 1M candles in the requested window")
    warmup_bars = len(all_candles) - len(window)

    provider = V2IndicatorProvider(
        all_candles,
        config=config,
        volumes=volumes,
        bb_length=args.bb_length,
        bb_multiplier=args.bb_mult,
    )
    coverage = provider.coverage(window_start, window_end)

    tradable = before_entry_end(window, args.entry_end)
    result = run_multi_session_backtest(
        candles=tradable,
        config=config,
        resolver=OptionContractResolver(args.database),
        option_loader=FyersOptionCandleLoader(args.database),
        execution_policy=V2ExecutionPolicy(
            entry_buffer_points=args.entry_buffer,
            max_slippage_points=args.max_slippage,
            fill_timeout_seconds=args.fill_timeout,
            entry_end_hhmm=args.entry_end,
        ),
        capital=args.capital,
        indicator_provider=provider,
        lot_size_loader=lambda instrument_id: database_lot_size(instrument_id, args.database),
    )

    warnings = []
    needs_vwap = {"ABOVE_VWAP", "BELOW_VWAP"} & set(config.selected_triggers)
    if needs_vwap and coverage.vwap_available == 0:
        warnings.append(
            "VWAP trigger selected but the NIFTY index candles carry no volume, so VWAP "
            "is unavailable and the trigger can never pass. A futures-volume VWAP is needed."
        )
    if "KTMI" in config.selected_triggers and coverage.ktmi_available < coverage.candles:
        warnings.append(f"KTMI unavailable on {coverage.candles - coverage.ktmi_available} window bars (warm-up too short?)")
    if "DMI" in config.selected_triggers and coverage.dmi_available < coverage.candles:
        warnings.append(f"DMI unavailable on {coverage.candles - coverage.dmi_available} window bars (warm-up too short?)")
    if warmup_bars == 0 and {"KTMI", "DMI", "CLOSE_ABOVE_UPPER_BB", "CLOSE_BELOW_LOWER_BB"} & set(config.selected_triggers):
        warnings.append("no warm-up history found before --from")

    rows = [trade_row(t) for t in result.trades]
    summary = {
        "generated_at": datetime.now(tz=IST).isoformat(timespec="seconds"),
        "window": {"from": start_day.isoformat(), "to": end_day.isoformat()},
        "underlying_bars_in_window": len(window),
        "warmup_bars": warmup_bars,
        "sessions": result.sessions,
        "signals": result.signals,
        "closed_trades": result.closed,
        "rejected": result.rejected,
        "rejection_reasons": dict(result.rejection_reasons),
        "wins": result.wins,
        "losses": result.losses,
        "win_rate_pct": round(result.win_rate_pct, 2),
        "initial_capital": result.initial_capital,
        "ending_equity": round(result.ending_equity, 2),
        "peak_equity": round(result.peak_equity, 2),
        "max_drawdown": round(result.max_drawdown, 2),
        "max_drawdown_pct": round(result.max_drawdown_pct, 2),
        "gross_pnl": round(result.gross_pnl, 2),
        "total_costs": round(result.total_costs, 2),
        "net_pnl": round(result.net_pnl, 2),
        "indicator_coverage": asdict(coverage),
        "warnings": warnings,
    }

    out_dir = args.out_dir or (
        REPORTS_DIR / "opening_breakout_v2" / datetime.now(tz=IST).strftime("%Y%m%d_%H%M%S")
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    (out_dir / "config.json").write_text(
        json.dumps({"cli": {k: str(v) for k, v in vars(args).items()}, "v2_config": asdict(config)}, indent=2),
        encoding="utf-8",
    )
    with (out_dir / "trades.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=TRADE_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    with (out_dir / "equity_curve.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["time", "gross_pnl", "costs", "net_pnl", "equity", "drawdown", "drawdown_pct"])
        for point in result.equity_curve:
            writer.writerow([ist(point.timestamp), round(point.gross_pnl, 2), round(point.costs, 2),
                             round(point.net_pnl, 2), round(point.equity, 2),
                             round(point.drawdown, 2), round(point.drawdown_pct, 2)])
    summary["out_dir"] = str(out_dir)
    return summary


def print_summary(summary: dict) -> None:
    line = "=" * 78
    print(line)
    print("KUNAL QUANT - OPENING BREAKOUT V2 BACKTEST (research only)")
    print(line)
    for key in ("window", "underlying_bars_in_window", "warmup_bars", "sessions", "signals",
                "closed_trades", "rejected", "wins", "losses", "win_rate_pct",
                "initial_capital", "ending_equity", "max_drawdown", "max_drawdown_pct",
                "gross_pnl", "total_costs", "net_pnl"):
        print(f"{key:<26}: {summary[key]}")
    if summary["rejection_reasons"]:
        print("rejection reasons:")
        for reason, count in sorted(summary["rejection_reasons"].items(), key=lambda kv: -kv[1]):
            print(f"  {count:5d}  {reason[:150]}")
    print(f"indicator coverage        : {summary['indicator_coverage']}")
    for warning in summary["warnings"]:
        print(f"WARNING: {warning}")
    print(f"reports saved to          : {summary['out_dir']}")
    print(line)


def main(argv=None) -> None:
    print_summary(run(build_parser().parse_args(argv)))


if __name__ == "__main__":
    main()
