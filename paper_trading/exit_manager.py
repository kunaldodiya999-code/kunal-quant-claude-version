"""Switchable exits for the paper engine: pick trailing-stop methods with checkboxes.

Exit rules on a trade, in the order they are evaluated on each COMPLETED option candle:

1. Initial stop-loss: always on. It is separate from trailing stops.
2. Trailing stops: any of the six methods the shadow lab already computes may be ticked
   active. Every method keeps running in the shadow lab for every trade whether ticked or
   not, so switching takes effect on the very next candle with no warm-up.
3. 3R partial target: a checkbox (default on).
4. KAMA exit on the underlying: a checkbox (default off, parked by the handover).

Combining rules (explicit, because the brief asks for them):

* The effective stop is the TIGHTER of the initial stop and every ticked trailing stop. A
  trailing stop that is looser than the initial stop changes nothing. Stops never loosen:
  each method's own trail only ratchets up.
* A stop calculated at a candle's close protects only the NEXT candle (no look-ahead).
* Stop fill price = the stop level, or the candle's open if it gapped below the stop.
  If several ticked methods are hit on the same candle, the highest stop (hit first on the
  way down) fills. The initial stop fills first when it is higher than the trailing stop.
* If a stop and the 3R target touch in one candle, the stop wins.
* Parabolic SAR methods also exit at the candle close when the SAR flips against the trade.
* A ticked method that already "exited" in the shadow run for this trade is SPENT: its
  frozen result is kept for comparison but it cannot drive the live trade.
* Nothing here talks to a broker. Trailing exits are recorded as STOP_LOSS in the journal
  (the locked lifecycle enum is unchanged); the method name goes to ``exit_events.csv``.
* With candles counted only from entry, Chandelier ATR(9) has no stop for the first 9
  candles; only the initial stop protects the trade until then.
"""
from __future__ import annotations

import csv
import json
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional
from zoneinfo import ZoneInfo

from backtest.option_trade_lifecycle import OptionExitReason
from paper_trading.engine import PaperStrategyId, PaperTradeRecord, PaperTradingEngine
from paper_trading.tsl_shadow_lab import OptionCandle, TslShadowLab

IST = ZoneInfo("Asia/Kolkata")
EVENT_FIELDS = ["recorded_at", "event_timestamp", "event_type", "trade_id", "detail"]

TSL_METHODS: dict[str, str] = {
    "chandelier_atr9_mult1.5": "Chandelier Exit (ATR 9, x1.5)",
    "supertrend_atr5_factor1.0": "Supertrend A (ATR 5, x1.0)",
    "supertrend_atr7_factor1.5": "Supertrend B (ATR 7, x1.5)",
    "psar_start0.02_inc0.02_max0.20": "Parabolic SAR A (0.02 / 0.02 / 0.20)",
    "psar_start0.04_inc0.04_max0.10": "Parabolic SAR B (0.04 / 0.04 / 0.10)",
    "kunal_atr_structure_atr5_swing2.5_buffer0.25": "Kunal Quant ATR structure trail",
}
DEFAULT_TSL = ("chandelier_atr9_mult1.5",)
_STOP_HIT = "OPTION_LOW_HIT_TRAILING_STOP"
_SAR_FLIP = "INDICATOR_CLOSE_REVERSAL"


@dataclass(frozen=True)
class ExitRules:
    active_tsl: tuple[str, ...] = DEFAULT_TSL
    partial_target: bool = True
    kama_exit: bool = False

    def __post_init__(self) -> None:
        names = tuple(self.active_tsl)
        if len(set(names)) != len(names):
            raise ValueError("active_tsl contains duplicates.")
        unknown = [n for n in names if n not in TSL_METHODS]
        if unknown:
            raise ValueError(f"Unknown trailing-stop method(s): {unknown}")
        object.__setattr__(self, "active_tsl", names)


@dataclass(frozen=True)
class ExitDecision:
    strategy_id: PaperStrategyId
    timestamp: int
    kind: str           # TSL_STOP, SAR_FLIP or LIFECYCLE
    detail: str
    price: float | None


def _trade_id(record: PaperTradeRecord) -> str:
    return f"{record.strategy_id.value}:{record.entry_timestamp}:{record.position.symbol}"


class ExitManager:
    def __init__(self, engine: PaperTradingEngine, tsl_shadow: TslShadowLab, *,
                 rules: ExitRules | None = None, journal_dir: str | Path | None = None) -> None:
        self.engine = engine
        self.lab = tsl_shadow
        self._dir = Path(journal_dir) if journal_dir is not None else None
        self._rules = rules or ExitRules()
        if self._dir is not None:
            self._dir.mkdir(parents=True, exist_ok=True)
            self._load_saved_rules()
        self._apply_to_lifecycle()

    # ---- rules (the checkboxes) --------------------------------------
    @property
    def rules(self) -> ExitRules:
        return self._rules

    def set_rules(self, *, active_tsl: Iterable[str] | None = None, partial_target: bool | None = None,
                  kama_exit: bool | None = None, timestamp: int | None = None) -> ExitRules:
        """Change which exits are active. Takes effect from the next completed candle."""
        new = ExitRules(
            active_tsl=tuple(active_tsl) if active_tsl is not None else self._rules.active_tsl,
            partial_target=self._rules.partial_target if partial_target is None else bool(partial_target),
            kama_exit=self._rules.kama_exit if kama_exit is None else bool(kama_exit),
        )
        old, self._rules = self._rules, new
        self._apply_to_lifecycle()
        self._save_rules()
        self._log("RULES_CHANGED", "",
                  f"tsl {list(old.active_tsl)} -> {list(new.active_tsl)}; "
                  f"partial_target {old.partial_target} -> {new.partial_target}; "
                  f"kama_exit {old.kama_exit} -> {new.kama_exit}", timestamp)
        return new

    def _apply_to_lifecycle(self) -> None:
        config = getattr(self.engine.lifecycle, "config", None)
        if config is not None and hasattr(config, "target_enabled"):
            self.engine.lifecycle.config = replace(config, target_enabled=self._rules.partial_target)

    @property
    def _rules_path(self) -> Optional[Path]:
        return None if self._dir is None else self._dir / "exit_rules.json"

    def _load_saved_rules(self) -> None:
        path = self._rules_path
        if path is None or not path.exists():
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            self._rules = ExitRules(tuple(data["active_tsl"]), bool(data["partial_target"]),
                                    bool(data["kama_exit"]))
        except (ValueError, KeyError, TypeError):
            self._log("RULES_RESET", "", "exit_rules.json unreadable; defaults used.", None)

    def _save_rules(self) -> None:
        path = self._rules_path
        if path is not None:
            path.write_text(json.dumps({
                "active_tsl": list(self._rules.active_tsl),
                "partial_target": self._rules.partial_target, "kama_exit": self._rules.kama_exit,
            }), encoding="utf-8")

    def _log(self, event_type: str, trade_id: str, detail: str, timestamp: int | None) -> None:
        if self._dir is None:
            return
        path = self._dir / "exit_events.csv"
        is_new = not path.exists()
        with path.open("a", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=EVENT_FIELDS)
            if is_new:
                writer.writeheader()
            writer.writerow({
                "recorded_at": datetime.now(IST).isoformat(timespec="seconds"),
                "event_timestamp": "" if timestamp is None else int(timestamp),
                "event_type": event_type, "trade_id": trade_id, "detail": detail,
            })

    # ---- trades and candles ------------------------------------------
    def enroll_open_trades(self) -> None:
        """Register every open paper trade with the shadow lab (safe to call repeatedly)."""
        for record in self.engine.active_positions.values():
            if record.closed:
                continue
            position = record.position
            self.lab.register_trade(
                trade_id=_trade_id(record), symbol=position.symbol,
                direction=getattr(position.direction, "value", position.direction),
                entry_timestamp=record.entry_timestamp,
                entry_price=position.entry_price, quantity=position.quantity,
            )

    def spent_methods(self, strategy_id: PaperStrategyId) -> tuple[str, ...]:
        """Ticked methods that already hit their shadow stop for the open trade (cannot drive it)."""
        record = self.engine.open_trade(strategy_id)
        trade = None if record is None else self.lab.trades.get(_trade_id(record))
        if trade is None:
            return ()
        return tuple(n for n in self._rules.active_tsl if trade["candidates"][n].exited)

    def on_option_candle(self, *, symbol: str, candle: OptionCandle,
                         underlying_close: float | None = None,
                         kama_value: float | None = None) -> list[ExitDecision]:
        """Advance every shadow method, then apply the active exit rules to open paper trades."""
        self.enroll_open_trades()
        decisions: list[ExitDecision] = []
        before = {sid: self.engine.open_trade(sid) for sid in PaperStrategyId}
        self.lab.on_candle(symbol=symbol, candle=candle)
        for sid, record in before.items():
            if (record is None or record.closed or record.position.symbol != symbol
                    or candle.timestamp <= record.last_processed_timestamp):
                continue
            trade = self.lab.trades.get(_trade_id(record))
            candidates = trade["candidates"] if trade is not None else {}
            # A spent method's frozen exit has an older timestamp, so it can never match this candle.
            live = set(self._rules.active_tsl) & set(candidates)
            hits = [candidates[n] for n in live
                    if candidates[n].exited and candidates[n].exit_timestamp == candle.timestamp
                    and candidates[n].exit_reason == _STOP_HIT]
            flips = [candidates[n] for n in live
                     if candidates[n].exited and candidates[n].exit_timestamp == candle.timestamp
                     and candidates[n].exit_reason == _SAR_FLIP]
            initial = record.position.stop_loss
            if hits:
                best = max(hits, key=lambda c: c.exit_price)
                if not (candle.low <= initial and best.exit_price < initial):
                    self.engine.force_close(sid, timestamp=candle.timestamp, price=best.exit_price,
                                            reason=OptionExitReason.STOP_LOSS)
                    self._log("TSL_EXIT", _trade_id(record),
                              f"{TSL_METHODS[best.name]} stop hit; filled at {best.exit_price}", candle.timestamp)
                    decisions.append(ExitDecision(sid, candle.timestamp, "TSL_STOP", best.name, best.exit_price))
                    continue
            kama = kama_value if (self._rules.kama_exit and underlying_close is not None) else None
            exits = self.engine.process_option_candle(
                strategy_id=sid, timestamp=candle.timestamp, option_high=candle.high,
                option_low=candle.low, option_close=candle.close,
                underlying_close=0.0 if underlying_close is None else float(underlying_close),
                kama_value=kama,
            )
            for event in exits:
                decisions.append(ExitDecision(sid, candle.timestamp, "LIFECYCLE", event.reason.value, event.price))
            if flips and self.engine.open_trade(sid) is not None:
                best = flips[0]
                self.engine.force_close(sid, timestamp=candle.timestamp, price=candle.close,
                                        reason=OptionExitReason.STOP_LOSS)
                self._log("TSL_EXIT", _trade_id(record),
                          f"{TSL_METHODS[best.name]} flipped against the trade; filled at close {candle.close}",
                          candle.timestamp)
                decisions.append(ExitDecision(sid, candle.timestamp, "SAR_FLIP", best.name, candle.close))
        return decisions

    def catch_up(self, *, symbol: str, candles: Iterable[OptionCandle],
                 underlying_close: float | None = None) -> int:
        """Rebuild trailing-stop state after a restart from the option's completed candles.

        Candles the engine already processed before the restart only advance the shadow
        lab. Later candles go through the full exit rules. Returns the candles replayed.
        """
        self.enroll_open_trades()
        count = 0
        for candle in sorted(candles, key=lambda c: c.timestamp):
            already = [r for r in self.engine.active_positions.values()
                       if not r.closed and r.position.symbol == symbol
                       and candle.timestamp <= r.last_processed_timestamp]
            if already:
                self.lab.on_candle(symbol=symbol, candle=candle)
            else:
                self.on_option_candle(symbol=symbol, candle=candle, underlying_close=underlying_close)
            count += 1
        return count


__all__ = ["DEFAULT_TSL", "ExitDecision", "ExitManager", "ExitRules", "TSL_METHODS"]
