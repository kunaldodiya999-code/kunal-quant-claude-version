"""The ONE price database both repos use (owner 26 Oct 2026): KunalQuant\\data\\database\\kunal_quant.db.

Only FYERS data (owner: "we need trusted data from the broker's API only, not Yahoo").
New candles are ADDED in exactly the format KunalQuant's own downloader writes (downloader/historical.py):
instruments row with broker 'FYERS', candles with resolution '1' and source 'FYERS_HISTORY', INSERT OR IGNORE.
Nothing is ever changed or deleted. Before the FIRST write, a backup copy of the database is made
(data\\database\\backups\\kunal_quant_before_kunal_quant_claude_<date>.db next to it).

Where the database is: --kq-db on a command, else the KQ_DATABASE environment variable, else
C:\\Users\\USER\\Desktop\\Kunal\\KunalQuant\\data\\database\\kunal_quant.db.
"""

from __future__ import annotations

import os
import shutil
import sqlite3
from datetime import date, datetime
from pathlib import Path
from typing import Iterable, Sequence
from zoneinfo import ZoneInfo

from market_data.resampling import Candle

IST = ZoneInfo("Asia/Kolkata")
SOURCE = "FYERS_HISTORY"                      # the label KunalQuant's downloader uses
WINDOWS_DEFAULT = Path(r"C:\Users\USER\Desktop\Kunal\KunalQuant\data\database\kunal_quant.db")
INDEX_SYMBOLS = {"NIFTY": "NSE:NIFTY50-INDEX", "BANKNIFTY": "NSE:NIFTYBANK-INDEX", "SENSEX": "BSE:SENSEX-INDEX",
                 "INDIAVIX": "NSE:INDIAVIX-INDEX"}


def default_path() -> Path:
    return Path(os.environ.get("KQ_DATABASE") or WINDOWS_DEFAULT)


def symbol_of(name: str) -> str:
    """NIFTY -> NSE:NIFTY50-INDEX, STK_RELIANCE or RELIANCE -> NSE:RELIANCE-EQ, a FYERS symbol stays as it is."""
    if ":" in name:
        return name
    if name in INDEX_SYMBOLS:
        return INDEX_SYMBOLS[name]
    return f"NSE:{name[4:] if name.startswith('STK_') else name}-EQ"


class KQStore:
    def __init__(self, path: str | Path | None = None, *, backup: bool = True) -> None:
        self.path = Path(path) if path else default_path()
        self.backup = backup
        self._backed_up = False
        self._ids: dict[str, int] = {}

    def exists(self) -> bool:
        return self.path.exists()

    def _connect(self, write: bool = False) -> sqlite3.Connection:
        if not write:
            return sqlite3.connect(f"file:{self.path}?mode=ro", uri=True, timeout=30)
        return sqlite3.connect(self.path, timeout=30)

    # ---------------------------------------------------------------- writing (add only)
    def _before_first_write(self) -> None:
        if self._backed_up:
            return
        self._backed_up = True
        if not self.path.exists():                       # a brand-new database: KunalQuant's own layout
            from database.schema import initialize_database
            initialize_database(self.path)
            return
        if not self.backup:
            return
        folder = self.path.parent / "backups"
        if any(folder.glob("kunal_quant_before_kunal_quant_claude_*.db")):
            return                                       # one backup is enough: we only ever ADD rows
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / f"kunal_quant_before_kunal_quant_claude_{date.today().isoformat()}.db"
        print(f"First write to the shared database: backup copy -> {target} "
              f"({self.path.stat().st_size / 1e9:.2f} GB, once)", flush=True)
        with self._connect() as src, sqlite3.connect(target) as dst:
            src.backup(dst)                              # a consistent copy even while the database is open

    def instrument_id(self, symbol: str) -> int:
        if symbol in self._ids:
            return self._ids[symbol]
        self._before_first_write()
        exchange = symbol.split(":")[0]
        index = symbol.endswith("-INDEX")
        underlying = next((k for k, v in INDEX_SYMBOLS.items() if v == symbol), None) or \
            symbol.split(":")[1].rsplit("-", 1)[0]
        with self._connect(write=True) as db:
            row = db.execute("SELECT id FROM instruments WHERE broker='FYERS' AND symbol=?", (symbol,)).fetchone()
            if row is None:
                db.execute("INSERT INTO instruments (broker, exchange, segment, symbol, underlying, instrument_type, "
                           "currency, is_active) VALUES ('FYERS', ?, '10', ?, ?, ?, 'INR', 1)",
                           (exchange, symbol, underlying, "INDEX" if index else "EQUITY"))
                row = db.execute("SELECT id FROM instruments WHERE broker='FYERS' AND symbol=?", (symbol,)).fetchone()
        self._ids[symbol] = int(row[0])
        return self._ids[symbol]

    def add_candles(self, symbol: str, candles: Iterable[Candle], *, source: str = SOURCE) -> int:
        """Add 1-minute candles (INSERT OR IGNORE: what is already there is never changed). Returns rows added."""
        rows = [(int(c.timestamp), c.open, c.high, c.low, c.close, c.volume, getattr(c, "open_interest", None))
                for c in candles]
        if not rows:
            return 0
        iid = self.instrument_id(symbol)
        with self._connect(write=True) as db:
            before = db.total_changes
            db.executemany("INSERT OR IGNORE INTO candles (instrument_id, timestamp, open, high, low, close, volume, "
                           "open_interest, resolution, source) VALUES (?,?,?,?,?,?,?,?,'1',?)",
                           [(iid, *r, source) for r in rows])
            return db.total_changes - before

    # ---------------------------------------------------------------- reading
    def load(self, name: str, *, since: date | None = None) -> list[Candle]:
        """1-minute candles of NIFTY / STK_RELIANCE / a FYERS symbol (one per minute, whatever the source label)."""
        if not self.path.exists():
            return []
        lo = 0 if since is None else int(datetime.combine(since, datetime.min.time(), tzinfo=IST).timestamp())
        with self._connect() as db:
            rows = db.execute(
                "SELECT c.timestamp, c.open, c.high, c.low, c.close, c.volume FROM candles c JOIN instruments i "
                "ON i.id = c.instrument_id WHERE i.symbol = ? AND c.resolution = '1' AND c.timestamp >= ? "
                "GROUP BY c.timestamp ORDER BY c.timestamp", (symbol_of(name), lo)).fetchall()
        return [Candle(int(t), float(o), float(h), float(l), float(c), None if v is None else int(v))
                for t, o, h, l, c, v in rows]

    def saved_range(self, name: str) -> tuple[date | None, date | None]:
        if not self.path.exists():
            return None, None
        with self._connect() as db:
            lo, hi = db.execute("SELECT MIN(c.timestamp), MAX(c.timestamp) FROM candles c JOIN instruments i ON "
                                "i.id = c.instrument_id WHERE i.symbol = ? AND c.resolution = '1'",
                                (symbol_of(name),)).fetchone()
        if lo is None:
            return None, None
        return datetime.fromtimestamp(lo, IST).date(), datetime.fromtimestamp(hi, IST).date()

    def stocks(self) -> list[str]:
        """Every stock (EQUITY) that has 1-minute candles."""
        if not self.path.exists():
            return []
        with self._connect() as db:
            rows = db.execute("SELECT DISTINCT i.symbol FROM instruments i WHERE i.instrument_type = 'EQUITY' AND "
                              "EXISTS (SELECT 1 FROM candles c WHERE c.instrument_id = i.id AND c.resolution = '1')"
                              ).fetchall()
        return sorted(r[0].split(":")[1].rsplit("-", 1)[0] for r in rows)

    def trading_days(self, since: date | None = None) -> list[date]:
        """The trading calendar = the days NIFTY has candles (an index trades every market day)."""
        return sorted({datetime.fromtimestamp(c.timestamp, IST).date() for c in self.load("NIFTY", since=since)})


def five_minute(candles: Sequence[Candle]) -> list[Candle]:
    """5-minute candles built from 1-minute ones (09:15 anchored, like TradingView). Every day is built; whether a day
    is clean enough to trade is decided by the day check (market_data/clean_days.py), not here."""
    from market_data.day_quality import group_by_day
    from market_data.resampling import aggregate_day
    return [Candle(b.timestamp, b.open, b.high, b.low, b.close, b.volume)
            for _day, bars in sorted(group_by_day(candles).items()) for b in aggregate_day(bars, 5)]


__all__ = ["INDEX_SYMBOLS", "KQStore", "SOURCE", "default_path", "five_minute", "symbol_of"]
