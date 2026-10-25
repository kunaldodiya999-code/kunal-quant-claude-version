"""Exits of open paper trades: initial stop, 2R partial, trailing stop (TSL), manual stop.

Settings come from ``trade_management.json`` (paper_trading/trade_management.py). Every trade
keeps the settings it was opened with (snapshot), saved in ``trade_management_state.json`` so a
restart continues the same rules and the same ratcheted stop.

Order on each event:
* Every finished 1-minute OPTION candle: the lifecycle checks the initial stop (30% of premium)
  and the 2R partial booking (stop first if a candle touches both). After the partial the
  remaining lots' stop moves as chosen (breakeven by default).
* When a TSL candle (strategy timeframe or the chosen one) finishes on the chosen chart
  (option or spot), the trade's trail checks its exit and then tightens.
* Manual mode: the stop is the level the owner sets for that trade (it may move either way).

The TSL exit closes the remaining lots: on the option chart at the TSL price, on the spot chart
at the option's latest price. The journal reason stays STOP_LOSS (locked enum); the TSL detail
goes to ``exit_events.csv``. Nothing here talks to a broker.
"""

from __future__ import annotations

import csv
import json
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterable, Optional
from zoneinfo import ZoneInfo

from backtest.option_trade_lifecycle import OptionExitReason
from market_data.resampling import Candle
from paper_trading.engine import PaperStrategyId, PaperTradeRecord, PaperTradingEngine
from paper_trading.trade_management import (
    LABELS, TradeManagementSettings, TradeManagementStore, TslTracker, session_bars,
)
from paper_trading.tsl_shadow_lab import OptionCandle, TslShadowLab

IST = ZoneInfo("Asia/Kolkata")
EVENT_FIELDS = ["recorded_at", "event_timestamp", "event_type", "trade_id", "detail"]
STATE_FILE = "trade_management_state.json"
MANUAL_FILE = "manual_stops.json"


def trade_id_of(record: PaperTradeRecord) -> str:
    return f"{record.strategy_id.value}:{record.entry_timestamp}:{record.position.symbol}"


class ExitDecision:
    def __init__(self, strategy_id, timestamp, kind, detail, price):
        self.strategy_id, self.timestamp, self.kind, self.detail, self.price = strategy_id, timestamp, kind, detail, price

    def __repr__(self) -> str:
        return f"ExitDecision({self.kind}, {self.detail}, {self.price})"


def lifecycle_config(base, settings: TradeManagementSettings):
    """The lifecycle settings a new trade should be opened with."""
    if settings.exit_target_rr is not None:          # reward box filled: whole trade out at 1:box
        return replace(base, stop_loss_pct=settings.initial_sl_pct / 100.0, target_rr=settings.exit_target_rr,
                       target_enabled=True, close_all_at_target=True, after_partial=settings.after_partial)
    return replace(base, stop_loss_pct=settings.initial_sl_pct / 100.0, target_rr=settings.partial_r,
                   target_enabled=settings.partial_enabled, partial_exit_fraction=settings.partial_pct / 100.0,
                   single_lot_at_target=settings.one_lot_at_target, after_partial=settings.after_partial,
                   close_all_at_target=False)


class ExitManager:
    def __init__(self, engine: PaperTradingEngine, tsl_shadow: TslShadowLab | None = None, *,
                 store: TradeManagementStore | None = None, journal_dir: str | Path | None = None,
                 strategy_timeframe: Callable[[], int] = lambda: 3,
                 option_history: Callable[[str], Iterable] | None = None,
                 spot_minutes: Callable[[], list] | None = None,
                 future_minutes: Callable[[], list] | None = None,
                 option_price: Callable[[str], Optional[float]] | None = None,
                 kama_exit: bool = False) -> None:
        self.engine = engine
        self.lab = tsl_shadow
        self._dir = Path(journal_dir) if journal_dir is not None else None
        if self._dir is not None:
            self._dir.mkdir(parents=True, exist_ok=True)
        self.store = store or TradeManagementStore(self._dir)
        self.strategy_timeframe = strategy_timeframe
        self.option_history = option_history
        self.spot_minutes_provider = spot_minutes
        self.future_minutes_provider = future_minutes   # current-month futures 1-minute candles (FUTURE source)
        self.option_price = option_price
        self.kama_exit = kama_exit
        self.option_minutes: dict[str, dict[int, Candle]] = {}
        self.spot_minutes: dict[int, Candle] = {}
        self.trackers: dict[str, TslTracker] = {}
        self.snapshots: dict[str, dict] = self._load_state()
        self._manual_mtime = None
        self._pending: dict = {}
        self.apply_settings_to_lifecycle()

    # ---------------------------------------------------------------- settings
    @property
    def settings(self) -> TradeManagementSettings:
        return self.store.settings

    def apply_settings_to_lifecycle(self) -> TradeManagementSettings:
        """Refresh the settings for the NEXT trade (call before entries; open trades keep their snapshot)."""
        settings = self.store.refresh()
        lifecycle = self.engine.lifecycle
        if hasattr(lifecycle, "config") and hasattr(lifecycle.config, "after_partial"):
            lifecycle.config = lifecycle_config(lifecycle.config, settings)
        return settings

    # ---------------------------------------------------------------- persistence
    def _state_path(self) -> Optional[Path]:
        return None if self._dir is None else self._dir / STATE_FILE

    def _load_state(self) -> dict:
        path = self._state_path()
        if path is None or not path.exists():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            self._log("STATE_RESET", "", f"{STATE_FILE} unreadable; open trades use the current settings.", None)
            return {}

    def _save_state(self) -> None:
        path = self._state_path()
        if path is None:
            return
        for tid, tracker in self.trackers.items():
            self.snapshots.setdefault(tid, {})["tracker"] = tracker.state()
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.snapshots, indent=1), encoding="utf-8")
        tmp.replace(path)

    def _log(self, event_type: str, trade_id: str, detail: str, timestamp: int | None) -> None:
        if self._dir is None:
            return
        path = self._dir / "exit_events.csv"
        is_new = not path.exists()
        with path.open("a", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=EVENT_FIELDS)
            if is_new:
                writer.writeheader()
            writer.writerow({"recorded_at": datetime.now(IST).isoformat(timespec="seconds"),
                             "event_timestamp": "" if timestamp is None else int(timestamp),
                             "event_type": event_type, "trade_id": trade_id, "detail": detail})

    # ---------------------------------------------------------------- manual stops
    def _manual_path(self) -> Optional[Path]:
        return None if self._dir is None else self._dir / MANUAL_FILE

    def set_manual_stop(self, trade_id: str, price: float | None) -> None:
        """Owner's manual stop for one open trade (used in MANUAL mode; may move either way)."""
        path = self._manual_path()
        stops = self._read_manual()
        if price is None:
            stops.pop(trade_id, None)
        else:
            stops[trade_id] = float(price)
        if path is not None:
            path.write_text(json.dumps(stops), encoding="utf-8")
        self._apply_manual(stops)

    def _read_manual(self) -> dict:
        path = self._manual_path()
        if path is None or not path.exists():
            return {}
        try:
            return {k: float(v) for k, v in json.loads(path.read_text(encoding="utf-8")).items()}
        except (ValueError, OSError, TypeError):
            return {}

    def _apply_manual(self, stops: dict | None = None) -> None:
        stops = self._read_manual() if stops is None else stops
        for tid, tracker in self.trackers.items():
            tracker.manual_stop = stops.get(tid)

    def _refresh_manual(self) -> None:
        path = self._manual_path()
        if path is None or not path.exists():
            return
        mtime = path.stat().st_mtime
        if mtime != self._manual_mtime:
            self._manual_mtime = mtime
            self._apply_manual()

    # ---------------------------------------------------------------- trades
    def _spot_at(self, ts: int) -> Optional[float]:
        minutes = self._spot_series()
        before = [c for c in minutes if c.timestamp < ts]
        return before[-1].close if before else (minutes[0].open if minutes else None)

    def _spot_series(self) -> list:
        if self.spot_minutes_provider is not None:
            try:
                return list(self.spot_minutes_provider() or [])
            except Exception:
                pass
        return [self.spot_minutes[t] for t in sorted(self.spot_minutes)]

    def _future_series(self) -> list:
        if self.future_minutes_provider is None:
            return []
        try:
            return sorted(self.future_minutes_provider() or [], key=lambda c: c.timestamp)
        except Exception:
            return []

    def _future_at(self, ts: int) -> Optional[float]:
        before = [c for c in self._future_series() if c.timestamp < ts]
        return before[-1].close if before else None

    def _series(self, source: str, symbol: str) -> list:
        if source == "OPTION":
            return self._option_series(symbol)
        return self._future_series() if source == "FUTURE" else self._spot_series()

    def _option_series(self, symbol: str) -> list:
        data = self.option_minutes.get(symbol, {})
        return [data[t] for t in sorted(data)]

    def option_price_at(self, symbol: str, ts: int) -> Optional[float]:
        series = [c for c in self._option_series(symbol) if c.timestamp < ts]
        if series:
            return series[-1].close
        if self.option_price is not None:
            try:
                return self.option_price(symbol)
            except Exception:
                return None
        return None

    def enroll_open_trades(self) -> None:
        """Give every open trade its settings snapshot and its trail (safe to call repeatedly)."""
        changed = False
        for record in list(self.engine.active_positions.values()):
            if record.closed:
                continue
            tid = trade_id_of(record)
            if tid in self.trackers:
                continue
            position = record.position
            saved = self.snapshots.get(tid, {})
            if "settings" in saved:
                try:
                    settings = TradeManagementSettings(**saved["settings"])
                except (TypeError, ValueError):
                    settings = self.store.settings
            else:
                settings = self.store.settings
                self._log("TRADE_SETTINGS", tid, json.dumps(settings.to_dict()), record.entry_timestamp)
            lifecycle = self.engine.lifecycle
            if hasattr(lifecycle, "remember") and hasattr(lifecycle.config, "after_partial"):
                lifecycle.remember(position, lifecycle_config(lifecycle.config, settings))
            timeframe = int(saved.get("timeframe") or settings.timeframe_minutes(self.strategy_timeframe()))
            direction = getattr(position.direction, "value", position.direction)
            if settings.tsl_source == "FUTURE" and not saved.get("source_entry_price") \
                    and self._future_at(record.entry_timestamp + 60) is None:
                settings = replace(settings, tsl_source="SPOT")
                self._log("TSL_SOURCE", tid, "no futures candles at the entry: this trade trails on the SPOT chart",
                          record.entry_timestamp)
            if settings.tsl_source == "FUTURE":
                side = "LONG" if direction == "LONG" else "SHORT"
                entry_price = saved.get("source_entry_price") or self._future_at(record.entry_timestamp + 60)
            elif settings.tsl_source == "SPOT":
                side = "LONG" if direction == "LONG" else "SHORT"
                entry_price = saved.get("source_entry_price") or self._spot_at(record.entry_timestamp)
            else:
                side, entry_price = "LONG", position.entry_price
                if self.option_history is not None and position.symbol not in self.option_minutes:
                    try:
                        history = [c for c in (self.option_history(position.symbol) or [])
                                   if c.timestamp < record.entry_timestamp]
                        # safety: history that does not look like this option's price is not used
                        if history and not (position.entry_price / 3 <= history[-1].close <= position.entry_price * 3):
                            self._log("HISTORY_MISMATCH", tid, f"history last close {history[-1].close} vs entry "
                                      f"{position.entry_price}; not used", None)
                            history = []
                        for c in history:
                            self.option_minutes.setdefault(position.symbol, {})[int(c.timestamp)] = c
                    except Exception as exc:
                        self._log("HISTORY_MISSING", tid, f"option history not loaded ({exc}); TSL warms up live", None)
            if entry_price is None:
                entry_price = position.entry_price
            tracker = TslTracker(trade_id=tid, settings=settings, side=side, entry_timestamp=record.entry_timestamp,
                                 entry_price=float(entry_price), timeframe=timeframe)
            state = saved.get("tracker") or {}
            tracker.stop, tracker.last_bar_ts = state.get("stop"), state.get("last_bar_ts")
            self.trackers[tid] = tracker
            self.snapshots[tid] = {"settings": settings.to_dict(), "timeframe": timeframe, "side": side,
                                   "source_entry_price": float(entry_price), "symbol": position.symbol,
                                   "tracker": tracker.state()}
            if self.lab is not None:
                self.lab.register(trade_id=tid, symbol=position.symbol, settings=settings, side=side,
                                  entry_timestamp=record.entry_timestamp, entry_price=float(entry_price),
                                  option_entry_price=position.entry_price, quantity=position.quantity,
                                  timeframe=timeframe)
            changed = True
        if changed:
            self._apply_manual()
            self._save_state()

    def _close_by_tsl(self, record: PaperTradeRecord, tracker: TslTracker, exit_, price: float) -> ExitDecision:
        ts = max(int(exit_.timestamp), int(record.last_processed_timestamp or 0))
        self.engine.force_close(record.strategy_id, timestamp=ts, price=price, reason=OptionExitReason.STOP_LOSS)
        detail = f"{exit_.detail}; option sold at {round(price, 2)} ({tracker.settings.tsl_source} chart)"
        self._log("TSL_EXIT", tracker.trade_id, detail, ts)
        self._pending.pop(tracker.trade_id, None)
        self._save_state()
        return ExitDecision(record.strategy_id, ts, exit_.reason, detail, price)

    def _feed_comparison(self, *, source: str, symbol: Optional[str] = None) -> None:
        """Every method keeps following its trade (even after the real trade closed) until it exits."""
        if self.lab is None:
            return
        for tid, trade in self.lab.trades.items():
            if trade["done"] or trade["settings"].tsl_source != source:
                continue
            if source == "OPTION" and trade["symbol"] != symbol:
                continue
            minutes = self._series(source, trade["symbol"])
            self.lab.on_bars(tid, session_bars(minutes, trade["timeframe"]),
                             lambda t, sym=trade["symbol"]: self.option_price_at(sym, t + 1))

    def _run_trails(self, *, source: str, symbol: Optional[str] = None) -> list[ExitDecision]:
        decisions = []
        self._refresh_manual()
        self._feed_comparison(source=source, symbol=symbol)
        for record in list(self.engine.active_positions.values()):
            if record.closed:
                continue
            tid = trade_id_of(record)
            tracker = self.trackers.get(tid)
            if tracker is None or tracker.settings.tsl_source != source:
                continue
            if source == "OPTION" and record.position.symbol != symbol:
                continue
            pending = self._pending.get(tid)
            if pending is not None:                       # an exit waiting for an option price
                price = self.option_price_at(record.position.symbol, 2**62)
                if price is not None and price > 0:
                    decisions.append(self._close_by_tsl(record, tracker, pending, float(price)))
                continue
            minutes = self._series(source, record.position.symbol)
            bars = session_bars(minutes, tracker.timeframe)
            if not tracker.settings.tsl_enabled:
                tracker.last_bar_ts = bars[-1].timestamp if bars else tracker.last_bar_ts
                continue
            hit = tracker.on_bars(bars)
            if hit is None:
                continue
            price = hit.option_price if source == "OPTION" else self.option_price_at(record.position.symbol, hit.timestamp + 1)
            if price is None or price <= 0:
                self._log("TSL_WAITING", tid, f"{hit.detail}; no option price yet, exit on the next price", hit.timestamp)
                self._pending[tid] = hit
                continue
            decisions.append(self._close_by_tsl(record, tracker, hit, float(price)))
        self._save_state()
        return decisions

    # ---------------------------------------------------------------- events
    def on_option_candle(self, *, symbol: str, candle, underlying_close: float | None = None,
                         kama_value: float | None = None) -> list[ExitDecision]:
        """A finished 1-minute candle of an option: lifecycle first, then the option-chart trails."""
        self.option_minutes.setdefault(symbol, {})[int(candle.timestamp)] = Candle(
            int(candle.timestamp), candle.open, candle.high, candle.low, candle.close, None)
        self.enroll_open_trades()
        decisions: list[ExitDecision] = []
        for sid in PaperStrategyId:
            record = self.engine.open_trade(sid)
            if (record is None or record.closed or record.position.symbol != symbol
                    or (record.last_processed_timestamp is not None and candle.timestamp <= record.last_processed_timestamp)):
                continue
            stop_before = record.position.stop_loss
            exits = self.engine.process_option_candle(
                strategy_id=sid, timestamp=candle.timestamp, option_high=candle.high, option_low=candle.low,
                option_close=candle.close, underlying_close=0.0 if underlying_close is None else float(underlying_close),
                kama_value=kama_value if (self.kama_exit and underlying_close is not None) else None,
            )
            for event in exits:
                decisions.append(ExitDecision(sid, candle.timestamp, "LIFECYCLE", event.reason.value, event.price))
                if event.reason == OptionExitReason.TARGET_3R:
                    self._log("PARTIAL_TARGET", trade_id_of(record),
                              f"booked {event.lots} lot(s) at {event.price}; stop {round(stop_before, 2)} -> "
                              f"{round(record.position.stop_loss, 2)}", candle.timestamp)
        decisions += self._run_trails(source="OPTION", symbol=symbol)
        return decisions

    def on_spot_minutes(self, symbol: str, candles) -> list[ExitDecision]:
        """Finished 1-minute index candles (pipeline minute sink): runs the spot-chart and futures-chart trails."""
        for c in candles:
            self.spot_minutes[int(c.timestamp)] = c
        self.enroll_open_trades()
        return self._run_trails(source="SPOT") + self._run_trails(source="FUTURE")

    def finish_comparison(self, timestamp: int) -> None:
        """Session end: close every TSL comparison at the option's latest price."""
        if self.lab is None:
            return
        for tid, trade in self.lab.trades.items():
            if not trade["done"]:
                self.lab.finish(tid, timestamp=timestamp, option_price=self.option_price_at(trade["symbol"], timestamp + 1))

    def catch_up(self, *, symbol: str, candles: Iterable, underlying_close: float | None = None) -> int:
        """After a restart: replay the option's finished candles (already-processed ones only warm up the trail)."""
        count = 0
        for candle in sorted(candles, key=lambda c: c.timestamp):
            self.on_option_candle(symbol=symbol, candle=candle, underlying_close=underlying_close)
            count += 1
        return count

    # ---------------------------------------------------------------- dashboard
    def trade_view(self, record: PaperTradeRecord) -> dict:
        tid = trade_id_of(record)
        tracker = self.trackers.get(tid)
        if tracker is None:
            return {}
        s = tracker.settings
        return {"tsl_enabled": s.tsl_enabled, "tsl_mode": s.tsl_mode, "tsl_method": LABELS.get(s.tsl_method, s.tsl_method),
                "tsl_source": s.tsl_source, "tsl_timeframe": tracker.timeframe, "tsl_trigger": s.tsl_trigger,
                "tsl_stop": tracker.current_stop(), "tsl_side": tracker.side,
                "comparison": self.lab.stops(tid) if self.lab is not None else {}}


__all__ = ["ExitDecision", "ExitManager", "OptionCandle", "lifecycle_config", "trade_id_of"]
