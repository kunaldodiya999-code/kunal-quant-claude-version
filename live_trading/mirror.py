"""Copy paper-engine entries/exits to broker orders (dry run unless armed).

Hooks the paper recorder: record_trade_open -> BUY, record_trade_exit -> SELL.
Orders run one at a time on a background worker so the live feed is never
blocked. A SELL is never larger than what was really bought (if the entry was
not filled, the exit is skipped and journaled).
"""

from __future__ import annotations

import csv
import queue
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo

from live_trading.executor import ExecutionResult, LimitOrderExecutor

IST = ZoneInfo("Asia/Kolkata")
LIVE_ORDER_FIELDS = ("time", "mode", "kind", "symbol", "requested_qty", "status", "filled_qty",
                     "avg_price", "order_ids", "paper_price", "message")


class LiveOrderMirror:
    def __init__(self, executor: LimitOrderExecutor, *, lot_size: int, journal_path: Path,
                 mode: str, on_alert: Callable[[str], None] = print, synchronous: bool = False) -> None:
        self.executor, self.lot_size, self.mode, self.on_alert = executor, lot_size, mode, on_alert
        self.path = Path(journal_path)
        self.holdings: dict[str, int] = {}
        self.results: list[ExecutionResult] = []
        self._synchronous = synchronous
        self._queue: "queue.Queue[tuple | None]" = queue.Queue()
        self._worker = None if synchronous else threading.Thread(target=self._run, name="live-orders", daemon=True)
        if self._worker:
            self._worker.start()

    # -- hooks -------------------------------------------------------------
    def on_open(self, record: Any) -> None:
        p = record.position
        self._submit(("ENTRY", p.symbol, int(p.quantity), float(p.entry_price), str(record.strategy_id.value)))

    def on_exit(self, record: Any, exit_event: Any) -> None:
        self._submit(("EXIT", record.position.symbol, int(exit_event.quantity), float(exit_event.price),
                      str(getattr(exit_event.reason, "value", exit_event.reason))))

    def _submit(self, job: tuple) -> None:
        if self._synchronous:
            self._handle(job)
        else:
            self._queue.put(job)

    def close(self, timeout: float = 60.0) -> None:
        if self._worker:
            self._queue.put(None)
            self._worker.join(timeout)

    # -- worker ------------------------------------------------------------
    def _run(self) -> None:
        while True:
            job = self._queue.get()
            if job is None:
                return
            try:
                self._handle(job)
            except Exception as exc:  # never let the worker die silently
                self.on_alert(f"LIVE ORDER ERROR: {exc}")
                self._journal("ERROR", job[1], job[2], ExecutionResult(job[0], job[1], "", job[2], "ERROR",
                                                                       message=str(exc)), job[3])

    def _handle(self, job: tuple) -> None:
        kind, symbol, qty, paper_price, label = job
        if kind == "EXIT":
            held = self.holdings.get(symbol, 0)
            if held <= 0:
                result = ExecutionResult("EXIT", symbol, "SELL", qty, "SKIPPED",
                                         message="no real position (entry was not filled): nothing to sell")
                self._journal(kind, symbol, qty, result, paper_price)
                return
            qty = min(qty, held)
        result = self.executor.execute(kind=kind, symbol=symbol, qty=qty, lot_size=self.lot_size,
                                       reference=paper_price, tag=f"KQ{label[:12]}")
        if result.filled_qty:
            sign = 1 if kind == "ENTRY" else -1
            self.holdings[symbol] = self.holdings.get(symbol, 0) + sign * result.filled_qty
        self.results.append(result)
        self._journal(kind, symbol, qty, result, paper_price)
        if result.alert or result.status in ("REJECTED", "PARTIAL"):
            self.on_alert(f"LIVE ORDER {result.status}: {kind} {symbol} - {result.message}")

    def _journal(self, kind, symbol, qty, result: ExecutionResult, paper_price) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        new = not self.path.exists() or self.path.stat().st_size == 0
        with self.path.open("a", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=LIVE_ORDER_FIELDS)
            if new:
                writer.writeheader()
            writer.writerow({
                "time": datetime.now(IST).isoformat(timespec="seconds"), "mode": self.mode, "kind": kind,
                "symbol": symbol, "requested_qty": qty, "status": result.status, "filled_qty": result.filled_qty,
                "avg_price": result.avg_price, "order_ids": " ".join(result.order_ids),
                "paper_price": paper_price, "message": result.message,
            })


class MirroringRecorder:
    """Wraps the paper recorder; everything is forwarded, trade opens/exits are also mirrored."""

    def __init__(self, inner: Any, mirror: LiveOrderMirror) -> None:
        self._inner, self._mirror = inner, mirror

    def __getattr__(self, name):
        return getattr(self._inner, name)

    def record_trade_open(self, trade) -> None:
        self._inner.record_trade_open(trade)
        self._mirror.on_open(trade)

    def record_trade_exit(self, trade, exit_event) -> None:
        self._inner.record_trade_exit(trade, exit_event)
        self._mirror.on_exit(trade, exit_event)


__all__ = ["LIVE_ORDER_FIELDS", "LiveOrderMirror", "MirroringRecorder"]
