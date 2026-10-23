"""Append-only CSV journal for paper signals and simulated trade events.

This recorder never places broker orders. Each event is appended immediately so
records survive process restarts and can be reviewed in spreadsheet software.
"""
from __future__ import annotations

import csv
from pathlib import Path
from typing import Any


SIGNAL_FIELDS = (
    "recorded_at",
    "signal_timestamp",
    "symbol",
    "strategy_id",
    "direction",
    "bar_index",
    "reason",
)

REJECTION_FIELDS = (
    "recorded_at",
    "decision_timestamp",
    "signal_timestamp",
    "strategy_id",
    "direction",
    "reason",
)

TRADE_FIELDS = (
    "recorded_at",
    "event_type",
    "trade_id",
    "event_timestamp",
    "strategy_id",
    "direction",
    "symbol",
    "entry_timestamp",
    "entry_price",
    "quantity",
    "lots",
    "stop_loss",
    "target",
    "exit_reason",
    "exit_price",
    "exit_quantity",
    "exit_lots",
    "remaining_quantity",
    "remaining_lots",
    "event_pnl",
    "gross_pnl",
    "closed",
)


class PaperTradeRecorder:
    """Persist paper signals and engine trade events to two append-only CSVs.

    By default files are written to data/paper_trading/: signals.csv and
    trade_events.csv. A custom directory is useful for tests or separate
    paper sessions. Existing files are appended to, not overwritten.
    """

    def __init__(self, output_dir: str | Path = "data/paper_trading") -> None:
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.signals_path = self.output_dir / "signals.csv"
        self.trades_path = self.output_dir / "trade_events.csv"

    @staticmethod
    def _append(path: Path, fields: tuple[str, ...], row: dict[str, Any]) -> None:
        needs_header = not path.exists() or path.stat().st_size == 0
        with path.open("a", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
            if needs_header:
                writer.writeheader()
            writer.writerow({field: row.get(field) for field in fields})
            handle.flush()

    def record_signal(self, signal: Any, *, symbol: str) -> None:
        strategy = getattr(signal, "strategy_id", "")
        self._append(
            self.signals_path,
            SIGNAL_FIELDS,
            {
                "recorded_at": self._now_iso(),
                "signal_timestamp": getattr(signal, "timestamp", ""),
                "symbol": symbol,
                "strategy_id": getattr(strategy, "value", strategy),
                "direction": getattr(signal, "direction", ""),
                "bar_index": getattr(signal, "index", ""),
                "reason": getattr(signal, "reason", ""),
            },
        )

    def record_rejection(self, *, signal: Any, decision_timestamp: int, reason: str) -> None:
        """Journal a signal that did not become a trade, with the reason."""
        strategy = getattr(signal.strategy_id, "value", signal.strategy_id)
        self._append(
            self.output_dir / "rejections.csv",
            REJECTION_FIELDS,
            {
                "recorded_at": self._now_iso(),
                "decision_timestamp": int(decision_timestamp),
                "signal_timestamp": int(signal.timestamp),
                "strategy_id": strategy,
                "direction": signal.direction,
                "reason": reason,
            },
        )

    def record_trade_open(self, trade: Any) -> None:
        position = trade.position
        strategy = getattr(trade, "strategy_id", position.strategy_id)
        strategy_value = getattr(strategy, "value", strategy)
        entry_timestamp = int(trade.entry_timestamp)
        trade_id = f"{strategy_value}:{entry_timestamp}:{position.symbol}"
        self._append(
            self.trades_path,
            TRADE_FIELDS,
            {
                "recorded_at": self._now_iso(),
                "event_type": "ENTRY",
                "trade_id": trade_id,
                "event_timestamp": entry_timestamp,
                "strategy_id": strategy_value,
                "direction": getattr(position.direction, "value", position.direction),
                "symbol": position.symbol,
                "entry_timestamp": entry_timestamp,
                "entry_price": position.entry_price,
                "quantity": position.quantity,
                "lots": position.lots,
                "stop_loss": position.stop_loss,
                "target": position.target,
                "remaining_quantity": position.remaining_quantity,
                "remaining_lots": position.remaining_lots,
                "event_pnl": 0.0,
                "gross_pnl": position.gross_pnl,
                "closed": position.closed,
            },
        )

    def record_trade_exit(self, trade: Any, exit_event: Any) -> None:
        position = trade.position
        strategy = getattr(trade, "strategy_id", position.strategy_id)
        strategy_value = getattr(strategy, "value", strategy)
        entry_timestamp = int(trade.entry_timestamp)
        trade_id = f"{strategy_value}:{entry_timestamp}:{position.symbol}"
        self._append(
            self.trades_path,
            TRADE_FIELDS,
            {
                "recorded_at": self._now_iso(),
                "event_type": "EXIT",
                "trade_id": trade_id,
                "event_timestamp": exit_event.timestamp,
                "strategy_id": strategy_value,
                "direction": getattr(position.direction, "value", position.direction),
                "symbol": position.symbol,
                "entry_timestamp": entry_timestamp,
                "entry_price": position.entry_price,
                "quantity": position.quantity,
                "lots": position.lots,
                "stop_loss": position.stop_loss,
                "target": position.target,
                "exit_reason": getattr(exit_event.reason, "value", exit_event.reason),
                "exit_price": exit_event.price,
                "exit_quantity": exit_event.quantity,
                "exit_lots": exit_event.lots,
                "remaining_quantity": exit_event.remaining_quantity,
                "remaining_lots": exit_event.remaining_lots,
                "event_pnl": exit_event.pnl,
                "gross_pnl": position.gross_pnl,
                "closed": position.closed,
            },
        )

    @staticmethod
    def _now_iso() -> str:
        from datetime import datetime
        from zoneinfo import ZoneInfo

        return datetime.now(ZoneInfo("Asia/Kolkata")).isoformat(timespec="seconds")


__all__ = ["PaperTradeRecorder"]
