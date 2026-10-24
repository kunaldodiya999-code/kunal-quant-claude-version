"""Candles + KTMI Uni Lite for the dashboard chart (read-only).

Sources:
  live      data/paper_trading/<INDEX>/minute_candles.csv, written by the trading program
            (morning warm-up history + every live minute).
  research  data/research/market_data.db (scripts/sweep_market_data.py, Yahoo 1-minute).
  kq-db     the KunalQuant database (5 years of NIFTY 1-minute), if it is on this PC.

KTMI Uni Lite is the locked calculation (profile UNI_LITE_CORE), run on the
chosen timeframe with earlier days as warm-up, exactly like the paper engine.
"""

from __future__ import annotations

import csv
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from .live import paper_dir                # also puts the project folder on sys.path
from .research import research_dir
from indicators.ktmi.universal import OHLCData
from indicators.ktmi_uni_lite import UNI_LITE_CORE, calculate_uni_lite
from market_data.day_quality import group_by_day
from market_data.resampling import Candle, aggregate_day
from paper_trading.minute_journal import MINUTE_FILE
from strategies.index_profiles import INDEX_PROFILES

IST = ZoneInfo("Asia/Kolkata")
IST_OFFSET = 19800            # the chart library shows UTC; shifting by +5:30 shows IST on the axis
WARMUP_DAYS = 15
SOURCES = {
    "live": "Trading program (today + warm-up days)",
    "research": "Research data (Yahoo 1-minute, last ~30 days)",
    "kq-db": "KunalQuant database (NIFTY, 5 years)",
}
DEFAULT_KQ_DB = Path(r"C:\Users\USER\Desktop\Kunal\KunalQuant\data\database\kunal_quant.db")


def _day(ts: int) -> date:
    return datetime.fromtimestamp(ts, IST).date()


def live_minutes(index: str) -> list[Candle]:
    path = paper_dir(index) / MINUTE_FILE
    if not path.exists():
        return []
    rows: dict[int, Candle] = {}
    try:
        with path.open(newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                ts = int(row["timestamp"])
                rows[ts] = Candle(ts, float(row["open"]), float(row["high"]), float(row["low"]),
                                  float(row["close"]), 0)
    except (OSError, ValueError, KeyError):
        return []
    return [rows[ts] for ts in sorted(rows)]


def research_minutes(index: str) -> list[Candle]:
    path = research_dir() / "market_data.db"
    if not path.exists():
        return []
    from market_data.research_store import ResearchStore
    return ResearchStore(path).load(index, "yahoo", "1m", clean_only=False)


def kq_minutes(index: str, path: Path = DEFAULT_KQ_DB, *, since: int | None = None,
               until: int | None = None) -> list[Candle]:
    if not Path(path).exists():
        return []
    symbol = INDEX_PROFILES[index].spot_symbol
    with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as db:
        rows = db.execute(
            "SELECT c.timestamp, c.open, c.high, c.low, c.close FROM candles c JOIN instruments i "
            "ON i.id = c.instrument_id WHERE i.symbol = ? AND c.resolution = '1' AND c.timestamp >= ? "
            "AND c.timestamp < ? GROUP BY c.timestamp ORDER BY c.timestamp",
            (symbol, since or 0, until or 2**62)).fetchall()
    return [Candle(int(t), float(o), float(h), float(l), float(c), 0) for t, o, h, l, c in rows]


def kq_last_day(index: str, path: Path = DEFAULT_KQ_DB) -> date | None:
    if not Path(path).exists():
        return None
    symbol = INDEX_PROFILES[index].spot_symbol
    with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as db:
        row = db.execute("SELECT MAX(c.timestamp) FROM candles c JOIN instruments i ON i.id = c.instrument_id "
                         "WHERE i.symbol = ? AND c.resolution = '1'", (symbol,)).fetchone()
    return _day(row[0]) if row and row[0] else None


def load_minutes(source: str, index: str, *, last_day: date | None = None, kq_db: Path = DEFAULT_KQ_DB
                 ) -> list[Candle]:
    """1-minute candles up to ``last_day`` (all if None), with warm-up days before it."""
    if source == "kq-db":
        last_day = last_day or kq_last_day(index, kq_db)
        if last_day is None:
            return []
        start = datetime.combine(last_day - timedelta(days=WARMUP_DAYS * 2), datetime.min.time(), IST)
        end = datetime.combine(last_day + timedelta(days=1), datetime.min.time(), IST)
        return kq_minutes(index, kq_db, since=int(start.timestamp()), until=int(end.timestamp()))
    minutes = live_minutes(index) if source == "live" else research_minutes(index)
    if last_day is not None:
        minutes = [c for c in minutes if _day(c.timestamp) <= last_day]
    return minutes


def trading_days(minutes) -> list[date]:
    return sorted({_day(c.timestamp) for c in minutes})


def chart_payload(minutes, timeframe: int, *, show_days: int = 1, momentum: bool = False) -> dict:
    """Candles, KTMI lines and arrows for the last ``show_days`` days of ``minutes``."""
    if timeframe == 1:
        bars = list(minutes)
    else:
        bars = [bar for _, day in sorted(group_by_day(minutes).items())
                for bar in aggregate_day(day, timeframe) if bar.complete]
    values = calculate_uni_lite([OHLCData(b.open, b.high, b.low, b.close) for b in bars], UNI_LITE_CORE) if bars else []
    days = trading_days(bars)
    first_shown = days[-show_days] if days else None
    out = {"timeframe": timeframe, "bar_seconds": timeframe * 60, "candles": [], "markers": [],
           "lines": {"long_speed": [], "long_signal": [], "short_speed": [], "short_signal": []},
           "levels": {"center": 0.0, "upper": 0.5, "lower": -0.5, "overbought": 3.0, "oversold": -3.0},
           "days": [d.isoformat() for d in days[-show_days:]]}
    if momentum:
        out["lines"].update(momentum_speed=[], momentum_signal=[])
    for bar, v in zip(bars, values):
        if _day(bar.timestamp) < first_shown:
            continue
        t = int(bar.timestamp) + IST_OFFSET
        out["candles"].append({"time": t, "open": bar.open, "high": bar.high, "low": bar.low, "close": bar.close})
        for name, series in out["lines"].items():
            value = getattr(v, name)
            series.append({"time": t} if value is None else {"time": t, "value": round(float(value), 4)})
        if v.long_buy:
            out["markers"].append({"time": t, "position": "belowBar", "color": "#26a69a", "shape": "arrowUp",
                                   "text": "BUY CALL"})
        if v.short_buy:
            out["markers"].append({"time": t, "position": "aboveBar", "color": "#ef5350", "shape": "arrowDown",
                                   "text": "BUY PUT"})
    return out


__all__ = ["IST_OFFSET", "SOURCES", "chart_payload", "kq_last_day", "load_minutes", "trading_days"]
