"""Parallel shadow evaluation of option-premium trailing-stop candidates.

This module never changes the production paper position or submits orders.
All candidate stops are calculated from completed candles of the traded option.
"""
from __future__ import annotations

import csv
import math
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")


@dataclass(frozen=True)
class OptionCandle:
    timestamp: int
    open: float
    high: float
    low: float
    close: float


@dataclass
class _Candidate:
    name: str
    stop: float | None = None
    exited: bool = False
    exit_timestamp: int | None = None
    exit_price: float | None = None
    exit_reason: str = ""
    bars_to_exit: int | None = None
    pnl: float | None = None
    state: dict = field(default_factory=dict)


class TslShadowLab:
    """Track each entry independently across six shadow TSL candidates.

    Candidates: Chandelier ATR(9)*1.5; Supertrend ATR(5)*1.0 and
    ATR(7)*1.5; PSAR (0.02,0.02,0.20) and (0.04,0.04,0.10);
    Kunal Quant ATR-confirmed structure trail (ATR 5, swing 2.5 ATR,
    buffer 0.25 ATR), using the existing research defaults.
    """

    CANDIDATES = (
        "chandelier_atr9_mult1.5",
        "supertrend_atr5_factor1.0",
        "supertrend_atr7_factor1.5",
        "psar_start0.02_inc0.02_max0.20",
        "psar_start0.04_inc0.04_max0.10",
        "kunal_atr_structure_atr5_swing2.5_buffer0.25",
    )

    def __init__(self, output_dir: str | Path = "data/paper_trading/tsl_shadow") -> None:
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.bars_path = self.output_dir / "tsl_shadow_bars.csv"
        self.exits_path = self.output_dir / "tsl_shadow_exits.csv"
        self.summary_path = self.output_dir / "tsl_shadow_summary.csv"
        self.trades: dict[str, dict] = {}
        self._bars_written = self.bars_path.exists() and self.bars_path.stat().st_size > 0
        self._exits_written = self.exits_path.exists() and self.exits_path.stat().st_size > 0
        self._summary_written = self.summary_path.exists() and self.summary_path.stat().st_size > 0

    @staticmethod
    def _append(path: Path, row: dict, header_flag: str, obj: "TslShadowLab") -> None:
        fields = list(row)
        exists = getattr(obj, header_flag)
        with path.open("a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fields)
            if not exists:
                writer.writeheader()
                setattr(obj, header_flag, True)
            writer.writerow(row)
            f.flush()

    def register_trade(self, *, trade_id: str, symbol: str, direction: str,
                       entry_timestamp: int, entry_price: float, quantity: int) -> None:
        if trade_id in self.trades:
            return
        if direction.upper() not in {"LONG", "SHORT"}:
            raise ValueError("direction must be LONG or SHORT")
        if not math.isfinite(entry_price) or entry_price <= 0 or quantity < 1:
            raise ValueError("entry price and quantity must be positive")
        self.trades[trade_id] = {
            "trade_id": trade_id, "symbol": symbol, "direction": direction.upper(),
            "entry_timestamp": int(entry_timestamp), "entry_price": float(entry_price),
            "quantity": int(quantity), "bars": [], "last_timestamp": int(entry_timestamp),
            "candidates": {n: _Candidate(n) for n in self.CANDIDATES},
        }

    @staticmethod
    def _tr(c: OptionCandle, prev_close: float | None) -> float:
        return max(c.high-c.low, abs(c.high-prev_close), abs(c.low-prev_close)) if prev_close is not None else c.high-c.low

    @staticmethod
    def _atr(bars: list[OptionCandle], period: int) -> float | None:
        if len(bars) < period:
            return None
        trs = []
        for i, b in enumerate(bars):
            prev = bars[i-1].close if i else None
            trs.append(TslShadowLab._tr(b, prev))
        return sum(trs[-period:]) / period

    @staticmethod
    def _supertrend(bars: list[OptionCandle], period: int, factor: float,
                    state: dict) -> float | None:
        atr = TslShadowLab._atr(bars, period)
        if atr is None:
            return None
        c = bars[-1]
        mid = (c.high + c.low) / 2
        upper, lower = mid + factor*atr, mid - factor*atr
        prev_upper, prev_lower = state.get("st_upper"), state.get("st_lower")
        prev_close = bars[-2].close if len(bars) > 1 else c.close
        if prev_upper is not None and prev_close <= prev_upper:
            upper = min(upper, prev_upper)
        if prev_lower is not None and prev_close >= prev_lower:
            lower = max(lower, prev_lower)
        trend = state.get("st_trend", 1)
        if trend == 1 and c.close < lower:
            trend = -1
        elif trend == -1 and c.close > upper:
            trend = 1
        state.update(st_upper=upper, st_lower=lower, st_trend=trend)
        return lower if trend == 1 else upper

    @staticmethod
    def _psar(bars: list[OptionCandle], start: float, inc: float, maximum: float,
              state: dict) -> float | None:
        if len(bars) < 2:
            return None
        prev = bars[-2]
        cur = bars[-1]
        if "psar" not in state:
            bull = cur.close >= prev.close
            sar = min(prev.low, cur.low) if bull else max(prev.high, cur.high)
            ep = max(prev.high, cur.high) if bull else min(prev.low, cur.low)
            state.update(psar=sar, psar_ep=ep, psar_af=start, psar_bull=bull)
            return sar
        sar, ep, af, bull = state["psar"], state["psar_ep"], state["psar_af"], state["psar_bull"]
        sar = sar + af*(ep-sar)
        if bull:
            sar = min(sar, prev.low, bars[-3].low if len(bars) >= 3 else prev.low)
            if cur.low < sar:
                bull, sar, ep, af = False, ep, cur.low, start
            elif cur.high > ep:
                ep, af = cur.high, min(maximum, af+inc)
        else:
            sar = max(sar, prev.high, bars[-3].high if len(bars) >= 3 else prev.high)
            if cur.high > sar:
                bull, sar, ep, af = True, ep, cur.high, start
            elif cur.low < ep:
                ep, af = cur.low, min(maximum, af+inc)
        state.update(psar=sar, psar_ep=ep, psar_af=af, psar_bull=bull)
        return sar

    @staticmethod
    def _structure(bars: list[OptionCandle], state: dict) -> float | None:
        period, swing_mult, buffer_mult = 5, 2.5, 0.25
        atr = TslShadowLab._atr(bars, period)
        if atr is None:
            return None
        i, c = len(bars)-1, bars[-1]
        extreme = state.get("struct_extreme")
        if extreme is None or c.low < extreme:
            extreme = c.low
            state["struct_extreme_i"] = i
        if c.high - extreme >= swing_mult*atr:
            candidate = extreme - buffer_mult*atr
            old = state.get("struct_stop")
            if old is None or candidate > old:
                state["struct_stop"] = candidate
            state["struct_extreme"] = c.high
            state["struct_extreme_i"] = i
        return state.get("struct_stop")

    def on_candle(self, *, symbol: str, candle: OptionCandle) -> None:
        """Advance all still-open shadow candidates for this option symbol."""
        for trade in self.trades.values():
            if trade["symbol"] != symbol or candle.timestamp <= trade["last_timestamp"]:
                continue
            trade["last_timestamp"] = candle.timestamp
            bars: list[OptionCandle] = trade["bars"]
            bars.append(candle)
            row = {
                "recorded_at": datetime.now(IST).isoformat(timespec="seconds"),
                "trade_id": trade["trade_id"], "symbol": symbol,
                "entry_timestamp": trade["entry_timestamp"], "timestamp": candle.timestamp,
                "open": candle.open, "high": candle.high, "low": candle.low, "close": candle.close,
            }
            for name, candidate in trade["candidates"].items():
                # A stop calculated at this candle's close can only protect the
                # next candle; use the previously known stop for intrabar hits.
                prior_stop = candidate.stop
                stop = self._candidate_stop(name, bars, candidate)
                if not candidate.exited and prior_stop is not None and candle.low <= prior_stop:
                    self._finish_candidate(trade, candidate, candle, prior_stop, "OPTION_LOW_HIT_TRAILING_STOP", len(bars))
                elif not candidate.exited and candidate.state.pop("exit_signal", False):
                    self._finish_candidate(trade, candidate, candle, candle.close, "INDICATOR_CLOSE_REVERSAL", len(bars))
                if stop is not None:
                    candidate.stop = stop
                row[f"{name}_stop"] = candidate.stop
                row[f"{name}_status"] = "EXITED" if candidate.exited else ("ACTIVE" if candidate.stop is not None else "WARMUP")
            self._append(self.bars_path, row, "_bars_written", self)
            if all(c.exited for c in trade["candidates"].values()) and not trade.get("summary_written"):
                self._write_summary(trade)
                trade["summary_written"] = True

    def _finish_candidate(self, trade: dict, candidate: _Candidate, candle: OptionCandle,
                          price: float, reason: str, bars_to_exit: int) -> None:
        candidate.exited = True
        candidate.exit_timestamp = candle.timestamp
        candidate.exit_price = min(candle.open, price) if reason == "OPTION_LOW_HIT_TRAILING_STOP" and candle.open < price else price
        candidate.exit_reason = reason
        candidate.bars_to_exit = bars_to_exit
        candidate.pnl = (candidate.exit_price-trade["entry_price"])*trade["quantity"]
        self._append(self.exits_path, {
            "recorded_at": datetime.now(IST).isoformat(timespec="seconds"),
            "trade_id": trade["trade_id"], "symbol": trade["symbol"], "candidate": candidate.name,
            "entry_timestamp": trade["entry_timestamp"], "entry_price": trade["entry_price"],
            "quantity": trade["quantity"], "exit_timestamp": candidate.exit_timestamp,
            "exit_price": candidate.exit_price, "exit_reason": candidate.exit_reason,
            "bars_to_exit": candidate.bars_to_exit, "gross_pnl": candidate.pnl,
        }, "_exits_written", self)

    def _candidate_stop(self, name: str, bars: list[OptionCandle], c: _Candidate) -> float | None:
        if name.startswith("chandelier"):
            atr = self._atr(bars, 9)
            if atr is None:
                return None
            raw = max(b.high for b in bars) - 1.5*atr
            return raw if c.stop is None else max(c.stop, raw)
        if name.startswith("supertrend_atr5"):
            raw = self._supertrend(bars, 5, 1.0, c.state)
            return raw if raw is None or c.stop is None else max(c.stop, raw)
        if name.startswith("supertrend_atr7"):
            raw = self._supertrend(bars, 7, 1.5, c.state)
            return raw if raw is None or c.stop is None else max(c.stop, raw)
        if name.startswith("psar_start0.02"):
            raw = self._psar(bars, .02, .02, .20, c.state)
            if c.state.get("psar") is not None and not c.state.get("psar_bull", True):
                c.state["exit_signal"] = True
                return None
            return raw
        if name.startswith("psar_start0.04"):
            raw = self._psar(bars, .04, .04, .10, c.state)
            if c.state.get("psar") is not None and not c.state.get("psar_bull", True):
                c.state["exit_signal"] = True
                return None
            return raw
        return self._structure(bars, c.state)

    def _write_summary(self, trade: dict) -> None:
        for name, c in trade["candidates"].items():
            self._append(self.summary_path, {
                "recorded_at": datetime.now(IST).isoformat(timespec="seconds"),
                "trade_id": trade["trade_id"], "symbol": trade["symbol"],
                "candidate": name, "entry_timestamp": trade["entry_timestamp"],
                "entry_price": trade["entry_price"], "quantity": trade["quantity"],
                "exit_timestamp": c.exit_timestamp, "exit_price": c.exit_price,
                "exit_reason": c.exit_reason, "gross_pnl": c.pnl,
                "bars_to_exit": c.bars_to_exit, "status": "EXITED" if c.exited else "OPEN",
            }, "_summary_written", self)


__all__ = ["OptionCandle", "TslShadowLab"]
