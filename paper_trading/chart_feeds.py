"""Extra data the trading program saves for the dashboard chart (read-only, never trades).

Per index, in data/paper_trading/<INDEX>/:
  futures_minute_candles.csv  1-minute candles of the nearest FUTURES contract WITH volume.
                              The spot index has no volume of its own, so the chart shows
                              futures volume on the spot candles (same minute), and VWAP and
                              the volume profile use it.
  daily_candles.csv           spot daily candles (about 1 year) + futures daily volume.
  oi_chain.json               option-chain open interest per strike (refreshed every minute).

Nothing here can stop trading: callers catch and report errors.
"""

from __future__ import annotations

import csv
import json
import math
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Mapping
from zoneinfo import ZoneInfo

from market_data.live_ticks import LiveMinuteBarBuilder
from market_data.resampling import Candle
from market_data.sources.fyers_history import fetch_history

IST = ZoneInfo("Asia/Kolkata")
FUTURES_FILE = "futures_minute_candles.csv"
DAILY_FILE = "daily_candles.csv"
OI_FILE = "oi_chain.json"
CANDLE_FIELDS = ("timestamp", "time", "symbol", "open", "high", "low", "close", "volume")


def _session_minute(ts: int) -> bool:
    local = datetime.fromtimestamp(ts, IST)
    return local.weekday() < 5 and (9, 15) <= (local.hour, local.minute) <= (15, 29)


class CandleFile:
    """Append-only CSV of candles; a timestamp already in the file is never written twice."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.seen: set[int] = set()
        if self.path.exists():
            try:
                with self.path.open(newline="", encoding="utf-8") as handle:
                    self.seen = {int(r["timestamp"]) for r in csv.DictReader(handle) if r.get("timestamp")}
            except (OSError, ValueError, KeyError):
                self.seen = set()

    def write(self, symbol: str, candles, *, daily: bool = False) -> int:
        fresh = sorted((c for c in candles if int(c.timestamp) not in self.seen), key=lambda c: c.timestamp)
        if not fresh:
            return 0
        self.path.parent.mkdir(parents=True, exist_ok=True)
        new = not self.path.exists() or self.path.stat().st_size == 0
        with self.path.open("a", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=CANDLE_FIELDS)
            if new:
                writer.writeheader()
            for c in fresh:
                writer.writerow({
                    "timestamp": int(c.timestamp),
                    "time": datetime.fromtimestamp(int(c.timestamp), IST).strftime("%Y-%m-%d" if daily else "%Y-%m-%d %H:%M"),
                    "symbol": symbol, "open": c.open, "high": c.high, "low": c.low, "close": c.close,
                    "volume": "" if c.volume is None else int(c.volume),
                })
                self.seen.add(int(c.timestamp))
        return len(fresh)


def read_candles(path: str | Path) -> list[Candle]:
    """Candles from a CandleFile (or minute_candles.csv); missing volume = None."""
    path = Path(path)
    if not path.exists():
        return []
    out: dict[int, Candle] = {}
    try:
        with path.open(newline="", encoding="utf-8") as handle:
            for r in csv.DictReader(handle):
                ts = int(r["timestamp"])
                vol = r.get("volume")
                out[ts] = Candle(ts, float(r["open"]), float(r["high"]), float(r["low"]), float(r["close"]),
                                 int(float(vol)) if vol not in (None, "") else None)
    except (OSError, ValueError, KeyError):
        return []
    return [out[t] for t in sorted(out)]


class FuturesMinuteRecorder:
    """1-minute futures candles with volume, from history at start and live ticks after.

    FYERS sends the day's total traded volume (``vol_traded_today``) with each tick;
    a minute's volume = total at its last tick - total at the previous minute's last tick.
    """

    def __init__(self, output_dir: str | Path, symbol: str) -> None:
        self.symbol = symbol
        self.file = CandleFile(Path(output_dir) / FUTURES_FILE)
        self._minute: dict | None = None
        self._last_total: float | None = None     # day total at the end of the previous minute

    def seed(self, candles) -> int:
        return self.file.write(self.symbol, [c for c in candles if _session_minute(int(c.timestamp))])

    def on_message(self, message: Any) -> None:
        if not isinstance(message, Mapping) or message.get("symbol") != self.symbol:
            return
        ts = LiveMinuteBarBuilder._timestamp_seconds(message)
        price = LiveMinuteBarBuilder._last_price(message)
        if ts is None or price is None:
            return
        try:
            total = float(message.get("vol_traded_today"))
            total = total if math.isfinite(total) else None
        except (TypeError, ValueError):
            total = None
        minute = ts - ts % 60
        m = self._minute
        if m is not None and minute > m["ts"]:
            self._close_minute()
            m = None
        if m is None:
            self._minute = {"ts": minute, "o": price, "h": price, "l": price, "c": price,
                            "start_total": self._last_total if self._last_total is not None else total,
                            "total": total}
        elif minute == m["ts"]:
            m["h"], m["l"], m["c"] = max(m["h"], price), min(m["l"], price), price
            if total is not None:
                m["total"] = total
                if m["start_total"] is None:
                    m["start_total"] = total

    def _close_minute(self) -> None:
        m = self._minute
        if m is None:
            return
        volume = None
        if m["total"] is not None and m["start_total"] is not None:
            volume = max(0, int(m["total"] - m["start_total"]))
            self._last_total = m["total"]
        if _session_minute(m["ts"]):
            self.file.write(self.symbol, [Candle(m["ts"], m["o"], m["h"], m["l"], m["c"], volume)])
        self._minute = None


def save_daily_candles(client: Any, output_dir: str | Path, *, spot: str, future: str | None, today: date,
                       days: int = 400, pause: float = 0.35) -> int:
    """Spot daily candles for about a year, with futures daily volume (continuous contract)."""
    start = today - timedelta(days=days)
    spot_days = fetch_history(client, spot, resolution="D", start=start, end=today, pause=pause)
    volume: dict[date, int] = {}
    if future:
        for c in fetch_history(client, future, resolution="D", start=start, end=today, cont_flag="1", pause=pause):
            if c.volume:
                volume[datetime.fromtimestamp(c.timestamp, IST).date()] = int(c.volume)
    rows = [Candle(c.timestamp, c.open, c.high, c.low, c.close,
                   volume.get(datetime.fromtimestamp(c.timestamp, IST).date())) for c in spot_days]
    return CandleFile(Path(output_dir) / DAILY_FILE).write(spot, rows, daily=True)


def _num(value) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def parse_option_chain(response: Any) -> dict:
    """FYERS option-chain answer -> {expiry, rows: [{strike, call_oi, put_oi, call_oi_change, put_oi_change}]}."""
    data = response.get("data") if isinstance(response, Mapping) else None
    if not isinstance(data, Mapping) or not isinstance(data.get("optionsChain"), list):
        raise ValueError(f"no option chain in the answer: {str(response)[:200]}")
    strikes: dict[float, dict] = {}
    spot = None
    for item in data["optionsChain"]:
        kind = str(item.get("option_type") or "").upper()
        strike = _num(item.get("strike_price"))
        if kind not in ("CE", "PE"):
            spot = _num(item.get("ltp")) or spot
            continue
        if strike is None or strike <= 0:
            continue
        row = strikes.setdefault(strike, {"strike": strike, "call_oi": 0.0, "put_oi": 0.0,
                                          "call_oi_change": 0.0, "put_oi_change": 0.0})
        side = "call" if kind == "CE" else "put"
        row[f"{side}_oi"] = _num(item.get("oi")) or 0.0
        change = _num(item.get("oich"))
        if change is None and _num(item.get("prev_oi")) is not None:
            change = (_num(item.get("oi")) or 0.0) - _num(item.get("prev_oi"))
        row[f"{side}_oi_change"] = change or 0.0
    expiry = None
    for entry in data.get("expiryData") or []:
        expiry = entry.get("date") or expiry
        break
    return {"spot": spot, "expiry": expiry, "rows": [strikes[k] for k in sorted(strikes)]}


def save_option_chain(model: Any, output_dir: str | Path, *, spot_symbol: str, strikes: int = 15,
                      now: datetime | None = None) -> dict:
    answer = model.optionchain(data={"symbol": spot_symbol, "strikecount": strikes, "timestamp": ""})
    chain = parse_option_chain(answer)
    chain["symbol"] = spot_symbol
    chain["updated_at"] = (now or datetime.now(IST)).strftime("%Y-%m-%d %H:%M:%S")
    path = Path(output_dir) / OI_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(chain), encoding="utf-8")
    tmp.replace(path)
    return chain


__all__ = [
    "DAILY_FILE", "FUTURES_FILE", "OI_FILE", "CandleFile", "FuturesMinuteRecorder", "parse_option_chain",
    "read_candles", "save_daily_candles", "save_option_chain",
]
