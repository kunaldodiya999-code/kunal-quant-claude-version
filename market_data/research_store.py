"""Research database for swept historical data: data/research/market_data.db.

Separate from the trading databases. Stores raw candles per (series, source,
resolution) and the day-quality verdicts, so backtests can load CLEAN days only.

Series names: NIFTY, BANKNIFTY, SENSEX (index), INDIAVIX, NIFTY_FUT ... (futures,
continuous), and option contracts by their FYERS symbol.
"""

from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path
from typing import Iterable, Sequence

from market_data.day_quality import DayQuality
from market_data.resampling import Candle

SCHEMA = """
CREATE TABLE IF NOT EXISTS candles (
    series TEXT NOT NULL, source TEXT NOT NULL, resolution TEXT NOT NULL, ts INTEGER NOT NULL,
    open REAL NOT NULL, high REAL NOT NULL, low REAL NOT NULL, close REAL NOT NULL, volume INTEGER,
    PRIMARY KEY (series, source, resolution, ts)
);
CREATE TABLE IF NOT EXISTS day_quality (
    series TEXT NOT NULL, source TEXT NOT NULL, resolution TEXT NOT NULL, day TEXT NOT NULL,
    clean INTEGER NOT NULL, expected INTEGER, actual INTEGER, cut_after TEXT, reason TEXT,
    verified_by TEXT,
    PRIMARY KEY (series, source, resolution, day)
);
"""


class ResearchStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.executescript(SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path)

    def save_candles(self, series: str, source: str, resolution: str, candles: Iterable[Candle]) -> int:
        rows = [(series, source, resolution, int(c.timestamp), c.open, c.high, c.low, c.close, c.volume)
                for c in candles]
        with self._connect() as db:
            db.executemany("INSERT OR REPLACE INTO candles VALUES (?,?,?,?,?,?,?,?,?)", rows)
        return len(rows)

    def save_quality(self, series: str, source: str, resolution: str, reports: Sequence[DayQuality]) -> None:
        with self._connect() as db:
            db.executemany(
                "INSERT OR REPLACE INTO day_quality VALUES (?,?,?,?,?,?,?,?,?, "
                "(SELECT verified_by FROM day_quality WHERE series=? AND source=? AND resolution=? AND day=?))",
                [(series, source, resolution, r.day.isoformat(), int(r.clean), r.expected, r.actual, r.cut_after,
                  r.reason, series, source, resolution, r.day.isoformat()) for r in reports])

    def mark_verified(self, series: str, source: str, resolution: str, day: date, other_source: str) -> None:
        with self._connect() as db:
            db.execute("UPDATE day_quality SET verified_by=? WHERE series=? AND source=? AND resolution=? AND day=?",
                       (other_source, series, source, resolution, day.isoformat()))

    def clean_days(self, series: str, source: str, resolution: str = "1m") -> list[tuple[date, str | None]]:
        with self._connect() as db:
            rows = db.execute("SELECT day, cut_after FROM day_quality WHERE series=? AND source=? AND resolution=? "
                              "AND clean=1 ORDER BY day", (series, source, resolution)).fetchall()
        return [(date.fromisoformat(d), cut) for d, cut in rows]

    def load(self, series: str, source: str, resolution: str = "1m", *, clean_only: bool = True) -> list[Candle]:
        """Candles of a series; with clean_only, only clean days and only up to each day's cut."""
        with self._connect() as db:
            rows = db.execute("SELECT ts, open, high, low, close, volume FROM candles WHERE series=? AND source=? "
                              "AND resolution=? ORDER BY ts", (series, source, resolution)).fetchall()
        candles = [Candle(int(t), o, h, l, c, v) for t, o, h, l, c, v in rows]
        if not clean_only:
            return candles
        from datetime import datetime
        from zoneinfo import ZoneInfo
        ist = ZoneInfo("Asia/Kolkata")
        allowed = dict(self.clean_days(series, source, resolution))
        out = []
        for c in candles:
            local = datetime.fromtimestamp(c.timestamp, ist)
            if local.date() in allowed:
                cut = allowed[local.date()]
                if cut is None or local.strftime("%H:%M") <= cut:
                    out.append(c)
        return out

    def summary(self) -> list[tuple]:
        with self._connect() as db:
            return db.execute(
                "SELECT series, source, resolution, COUNT(*), SUM(clean), MIN(day), MAX(day), "
                "SUM(CASE WHEN verified_by IS NOT NULL THEN 1 ELSE 0 END) "
                "FROM day_quality GROUP BY series, source, resolution ORDER BY series, source, resolution"
            ).fetchall()


__all__ = ["ResearchStore"]
