"""Restart recovery for the paper engine, rebuilt only from its own journal.

The recorder appends every entry and exit to ``trade_events.csv`` and every
emitted signal to ``signals.csv``. After a crash or restart this module
replays those files so that:

* an open paper position is restored with its exact stop, target, remaining
  lots and partial-exit state, instead of being silently lost;
* a signal already seen before the restart cannot open a second entry.

Restoring never writes to the journal and never contacts a broker. If the
journal is inconsistent, ``RecoveryError`` is raised and nothing is installed:
a wrong position is worse than a refused start.
"""
from __future__ import annotations

import csv
import math
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional
from zoneinfo import ZoneInfo

from backtest.option_trade_lifecycle import (
    OptionExitReason,
    OptionTradeDirection,
    OptionTradeExit,
    OptionTradePosition,
)
from paper_trading.engine import PaperStrategyId, PaperTradeRecord, PaperTradingEngine

IST = ZoneInfo("Asia/Kolkata")
SignalKey = tuple[str, str, int]


class RecoveryError(RuntimeError):
    """The journal cannot be replayed into a trustworthy engine state."""


@dataclass(frozen=True)
class RecoveryReport:
    trades_restored: int
    open_trade_ids: tuple[str, ...]
    closed_trade_ids: tuple[str, ...]
    stale_open_trade_ids: tuple[str, ...]  # still open, entered on an earlier IST date
    signals_restored: int


def _rows(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _num(row: dict, key: str, cast=float):
    try:
        return cast(row[key])
    except (KeyError, TypeError, ValueError) as exc:
        raise RecoveryError(f"Journal row has invalid {key!r}: {row.get(key)!r}") from exc


def _bool(row: dict) -> bool:
    text = str(row.get("closed", "")).strip().lower()
    if text in ("true", "1"):
        return True
    if text in ("false", "0"):
        return False
    raise RecoveryError(f"Journal row has invalid 'closed': {row.get('closed')!r}")


def _optional_float(row: dict, key: str) -> Optional[float]:
    text = str(row.get(key, "")).strip()
    return None if text in ("", "None", "none", "nan") else _num(row, key)


def _build_record(trade_id: str, rows: list[dict]) -> PaperTradeRecord:
    entry = rows[0]
    if entry.get("event_type") != "ENTRY":
        raise RecoveryError(f"Trade {trade_id}: first journal event is not ENTRY.")
    if any(r.get("event_type") != "EXIT" for r in rows[1:]):
        raise RecoveryError(f"Trade {trade_id}: more than one ENTRY or unknown event type.")
    try:
        strategy = PaperStrategyId(entry["strategy_id"])
        direction = OptionTradeDirection(str(entry["direction"]).upper())
    except ValueError as exc:
        raise RecoveryError(f"Trade {trade_id}: unsupported strategy or direction.") from exc

    lots, quantity = _num(entry, "lots", int), _num(entry, "quantity", int)
    position = OptionTradePosition(
        strategy_id=strategy.value, direction=direction, symbol=entry["symbol"],
        entry_price=_num(entry, "entry_price"), lots=lots, quantity=quantity,
        stop_loss=_num(entry, "stop_loss"), target=_optional_float(entry, "target"),
        remaining_lots=lots, remaining_quantity=quantity,
    )
    entry_ts = _num(entry, "entry_timestamp", int)
    record = PaperTradeRecord(
        strategy_id=strategy, entry_timestamp=entry_ts, position=position,
        last_processed_timestamp=entry_ts,
    )
    for row in rows[1:]:
        try:
            reason = OptionExitReason(row["exit_reason"])
        except (KeyError, ValueError) as exc:
            raise RecoveryError(f"Trade {trade_id}: unknown exit reason.") from exc
        event = OptionTradeExit(
            timestamp=_num(row, "event_timestamp", int), reason=reason,
            price=_num(row, "exit_price"), quantity=_num(row, "exit_quantity", int),
            lots=_num(row, "exit_lots", int), pnl=_num(row, "event_pnl"),
            remaining_quantity=_num(row, "remaining_quantity", int),
            remaining_lots=_num(row, "remaining_lots", int),
        )
        if event.remaining_quantity != position.remaining_quantity - event.quantity:
            raise RecoveryError(f"Trade {trade_id}: exit quantities do not add up.")
        position.remaining_quantity = event.remaining_quantity
        position.remaining_lots = event.remaining_lots
        position.gross_pnl += event.pnl
        position.closed = _bool(row)
        if reason == OptionExitReason.TARGET_3R:
            position.partial_exit_done = True
        record.exits.append(event)
        record.last_processed_timestamp = max(record.last_processed_timestamp, event.timestamp)
        if not math.isclose(position.gross_pnl, _num(row, "gross_pnl"), abs_tol=0.01):
            raise RecoveryError(f"Trade {trade_id}: gross P&L does not match its exits.")
    if position.closed != (position.remaining_quantity == 0):
        raise RecoveryError(f"Trade {trade_id}: closed flag disagrees with remaining quantity.")
    return record


def restore_engine_from_journal(
    engine: PaperTradingEngine,
    trades_path: str | Path | None = None,
    *,
    today: datetime | None = None,
) -> RecoveryReport:
    """Rebuild trade logs and open positions on a fresh engine from the journal."""
    if trades_path is None:
        if engine.recorder is None:
            raise RecoveryError("Engine has no recorder; pass trades_path.")
        trades_path = engine.recorder.trades_path
    if engine.active_positions or any(engine.trade_logs.values()):
        raise RecoveryError("Restore must run on a fresh engine, before any trade.")

    groups: dict[str, list[dict]] = {}
    for row in _rows(Path(trades_path)):
        groups.setdefault(row.get("trade_id", ""), []).append(row)

    records = [_build_record(trade_id, rows) for trade_id, rows in groups.items()]
    open_by_strategy: dict[PaperStrategyId, PaperTradeRecord] = {}
    for record in records:
        if not record.closed:
            if record.strategy_id in open_by_strategy:
                raise RecoveryError(
                    f"Journal holds two open trades for {record.strategy_id.value}."
                )
            open_by_strategy[record.strategy_id] = record

    # Everything validated: install in one step.
    for record in records:
        engine.trade_logs[record.strategy_id].append(record)
    engine.active_positions.update(open_by_strategy)

    today_date = (today or datetime.now(IST)).astimezone(IST).date()

    def _id(record: PaperTradeRecord) -> str:
        return f"{record.strategy_id.value}:{record.entry_timestamp}:{record.position.symbol}"

    stale = tuple(
        _id(r) for r in open_by_strategy.values()
        if datetime.fromtimestamp(r.entry_timestamp, IST).date() != today_date
    )
    return RecoveryReport(
        trades_restored=len(records),
        open_trade_ids=tuple(_id(r) for r in open_by_strategy.values()),
        closed_trade_ids=tuple(_id(r) for r in records if r.closed),
        stale_open_trade_ids=stale,
        signals_restored=0,
    )


def load_seen_signal_keys(signals_path: str | Path) -> set[SignalKey]:
    """Return (strategy, direction, bar timestamp) for every journaled signal."""
    keys: set[SignalKey] = set()
    for row in _rows(Path(signals_path)):
        try:
            keys.add((str(row["strategy_id"]), str(row["direction"]),
                      int(float(row["signal_timestamp"]))))
        except (KeyError, ValueError) as exc:
            raise RecoveryError(f"Signal journal row is invalid: {row!r}") from exc
    return keys


def restore_from_journal(
    engine: PaperTradingEngine,
    coordinator,
    *,
    today: datetime | None = None,
) -> RecoveryReport:
    """Restore open positions and already-seen signals using the engine's recorder."""
    if engine.recorder is None:
        raise RecoveryError("Engine has no recorder; there is nothing to restore from.")
    report = restore_engine_from_journal(engine, today=today)
    keys = load_seen_signal_keys(engine.recorder.signals_path)
    coordinator.restore_seen_signals(keys)
    return RecoveryReport(
        trades_restored=report.trades_restored,
        open_trade_ids=report.open_trade_ids,
        closed_trade_ids=report.closed_trade_ids,
        stale_open_trade_ids=report.stale_open_trade_ids,
        signals_restored=len(keys),
    )


__all__ = [
    "RecoveryError", "RecoveryReport", "load_seen_signal_keys",
    "restore_engine_from_journal", "restore_from_journal",
]
