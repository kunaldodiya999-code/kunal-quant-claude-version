"""Every 1-minute index candle the session saw: ``minute_candles.csv``.

Holds the morning warm-up history and each live minute, so the dashboard
chart can draw the whole day (and KTMI Uni Lite on any timeframe) even when
the program was started late. A minute already in the file is not written again.
"""

from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")
MINUTE_FILE = "minute_candles.csv"
MINUTE_FIELDS = ("timestamp", "time", "symbol", "open", "high", "low", "close")


class MinuteCandleJournal:
    def __init__(self, output_dir: str | Path) -> None:
        self.path = Path(output_dir) / MINUTE_FILE
        self._seen: set[int] = set()
        if self.path.exists():
            try:
                with self.path.open(newline="", encoding="utf-8") as handle:
                    self._seen = {int(row["timestamp"]) for row in csv.DictReader(handle) if row.get("timestamp")}
            except (OSError, ValueError, KeyError):
                self._seen = set()

    def record(self, symbol: str, candles) -> None:
        fresh = [c for c in candles if int(c.timestamp) not in self._seen]
        if not fresh:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        new = not self.path.exists() or self.path.stat().st_size == 0
        with self.path.open("a", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=MINUTE_FIELDS)
            if new:
                writer.writeheader()
            for c in sorted(fresh, key=lambda c: c.timestamp):
                writer.writerow({
                    "timestamp": int(c.timestamp),
                    "time": datetime.fromtimestamp(int(c.timestamp), IST).strftime("%Y-%m-%d %H:%M"),
                    "symbol": symbol, "open": c.open, "high": c.high, "low": c.low, "close": c.close,
                })
                self._seen.add(int(c.timestamp))


__all__ = ["MINUTE_FIELDS", "MINUTE_FILE", "MinuteCandleJournal"]
