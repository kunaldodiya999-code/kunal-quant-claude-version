"""TSL comparison ("shadow lab"): every TSL method follows every paper trade, side by side.

Research only: it never changes a position or sends an order. For each paper trade it runs
all six TSL presets (Chandelier everget, Supertrend A/B, PSAR A/B, point trail) with the SAME
source (option or spot chart), timeframe and trigger the trade was opened with, so you can see
which method would have captured the most. Results:

  tsl_shadow/tsl_shadow_exits.csv    one row per method when it would have exited
  tsl_shadow/tsl_shadow_summary.csv  one row per method and trade once the comparison is complete
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional, Sequence
from zoneinfo import ZoneInfo

from paper_trading.trade_management import LABELS, TradeManagementSettings, TslExit, TslTracker
from paper_trading.tsl_methods import PRESETS

IST = ZoneInfo("Asia/Kolkata")
EXIT_FIELDS = ["recorded_at", "trade_id", "symbol", "method", "source", "timeframe", "trigger", "entry_timestamp",
               "entry_price", "quantity", "exit_timestamp", "exit_reason", "exit_option_price", "gross_pnl", "detail"]


@dataclass(frozen=True)
class OptionCandle:
    """A finished option candle (kept for callers that build candles by hand)."""
    timestamp: int
    open: float
    high: float
    low: float
    close: float


class TslShadowLab:
    METHODS = tuple(PRESETS)

    def __init__(self, output_dir: str | Path = "data/paper_trading/tsl_shadow") -> None:
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.exits_path = self.output_dir / "tsl_shadow_exits.csv"
        self.summary_path = self.output_dir / "tsl_shadow_summary.csv"
        self.trades: dict[str, dict] = {}

    def register(self, *, trade_id: str, symbol: str, settings: TradeManagementSettings, side: str,
                 entry_timestamp: int, entry_price: float, option_entry_price: float, quantity: int,
                 timeframe: int) -> None:
        if trade_id in self.trades:
            return
        indicator = TradeManagementSettings(**{**settings.to_dict(), "tsl_mode": "INDICATOR"})
        trackers = {}
        for key in self.METHODS:
            kind, _ = PRESETS[key]
            trackers[key] = TslTracker(trade_id=trade_id, settings=indicator, side=side, entry_timestamp=entry_timestamp,
                                       entry_price=entry_price, timeframe=timeframe,
                                       method=(kind, dict(settings.method_params[key])), label=LABELS[key])
        self.trades[trade_id] = {"symbol": symbol, "settings": settings, "entry_timestamp": int(entry_timestamp),
                                 "option_entry_price": float(option_entry_price), "quantity": int(quantity),
                                 "timeframe": timeframe, "trackers": trackers, "results": {}, "done": False}

    def on_bars(self, trade_id: str, bars: Sequence, option_price_at: Callable[[int], Optional[float]]) -> None:
        trade = self.trades.get(trade_id)
        if trade is None or trade["done"]:
            return
        for key, tracker in trade["trackers"].items():
            if key in trade["results"]:
                continue
            hit = tracker.on_bars(bars)
            if hit is not None:
                self._record(trade_id, key, hit, option_price_at)

    def _record(self, trade_id: str, key: str, hit: TslExit, option_price_at) -> None:
        trade = self.trades[trade_id]
        s: TradeManagementSettings = trade["settings"]
        price = hit.option_price if s.tsl_source == "OPTION" else option_price_at(hit.timestamp)
        pnl = None if price is None else round((price - trade["option_entry_price"]) * trade["quantity"], 2)
        result = {"exit_timestamp": hit.timestamp, "exit_reason": hit.reason, "exit_option_price": price,
                  "gross_pnl": pnl, "detail": hit.detail}
        trade["results"][key] = result
        self._append(self.exits_path, self._row(trade_id, key, result))

    def finish(self, trade_id: str, *, timestamp: int, option_price: Optional[float], reason: str = "SESSION_END") -> None:
        """Close the comparison for a trade: methods still running are valued at ``option_price``."""
        trade = self.trades.get(trade_id)
        if trade is None or trade["done"]:
            return
        for key in self.METHODS:
            if key not in trade["results"]:
                pnl = None if option_price is None else round((option_price - trade["option_entry_price"]) * trade["quantity"], 2)
                trade["results"][key] = {"exit_timestamp": int(timestamp), "exit_reason": reason,
                                         "exit_option_price": option_price, "gross_pnl": pnl,
                                         "detail": "still trailing when the comparison ended"}
        for key in self.METHODS:
            self._append(self.summary_path, self._row(trade_id, key, trade["results"][key]))
        trade["done"] = True

    def _row(self, trade_id: str, key: str, result: dict) -> dict:
        trade = self.trades[trade_id]
        s: TradeManagementSettings = trade["settings"]
        return {"recorded_at": datetime.now(IST).isoformat(timespec="seconds"), "trade_id": trade_id,
                "symbol": trade["symbol"], "method": LABELS[key], "source": s.tsl_source,
                "timeframe": trade["timeframe"], "trigger": s.tsl_trigger, "entry_timestamp": trade["entry_timestamp"],
                "entry_price": trade["option_entry_price"], "quantity": trade["quantity"], **result}

    @staticmethod
    def _append(path: Path, row: dict) -> None:
        new = not path.exists() or path.stat().st_size == 0
        with path.open("a", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=EXIT_FIELDS)
            if new:
                writer.writeheader()
            writer.writerow({k: row.get(k) for k in EXIT_FIELDS})

    def stops(self, trade_id: str) -> dict:
        """Current stop of every method for a trade (for the dashboard)."""
        trade = self.trades.get(trade_id)
        if trade is None:
            return {}
        return {LABELS[k]: (None if k in trade["results"] else t.stop) for k, t in trade["trackers"].items()}


__all__ = ["OptionCandle", "TslShadowLab"]
