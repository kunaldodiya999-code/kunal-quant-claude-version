"""KTMI Uni Lite values for every closed candle: ``ktmi_bars.csv``.

The signal checker. Each row holds the candle and the six KTMI lines exactly
as the paper engine saw them when the candle closed, plus which arrows fired.
Compare any row with TradingView's Data Window for the same candle.
"""

from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from indicators.ktmi_uni_lite import UniLiteBar

IST = ZoneInfo("Asia/Kolkata")
KTMI_BAR_FIELDS = (
    "candle_time", "timeframe_min", "symbol", "open", "high", "low", "close",
    "long_speed", "long_signal", "short_speed", "short_signal", "momentum_speed", "momentum_signal",
    "long_buy", "short_buy", "momentum_buy", "momentum_sell", "recorded_at",
)


def _r(value):
    return "" if value is None else round(float(value), 4)


def ktmi_row(bar, values: UniLiteBar, *, timeframe_minutes: int, symbol: str) -> dict:
    return {
        "candle_time": datetime.fromtimestamp(int(bar.timestamp), IST).strftime("%Y-%m-%d %H:%M"),
        "timeframe_min": timeframe_minutes,
        "symbol": symbol,
        "open": bar.open, "high": bar.high, "low": bar.low, "close": bar.close,
        "long_speed": _r(values.long_speed), "long_signal": _r(values.long_signal),
        "short_speed": _r(values.short_speed), "short_signal": _r(values.short_signal),
        "momentum_speed": _r(values.momentum_speed), "momentum_signal": _r(values.momentum_signal),
        "long_buy": "BUY CALL" if values.long_buy else "",
        "short_buy": "BUY PUT" if values.short_buy else "",
        "momentum_buy": "Y" if values.momentum_buy else "",
        "momentum_sell": "Y" if values.momentum_sell else "",
        "recorded_at": datetime.now(IST).isoformat(timespec="seconds"),
    }


class KtmiBarJournal:
    def __init__(self, output_dir: str | Path, *, timeframe_minutes: int, symbol: str) -> None:
        self.path = Path(output_dir) / "ktmi_bars.csv"
        self.timeframe_minutes = timeframe_minutes
        self.symbol = symbol

    def record(self, bar, values: UniLiteBar) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        new = not self.path.exists() or self.path.stat().st_size == 0
        with self.path.open("a", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=KTMI_BAR_FIELDS)
            if new:
                writer.writeheader()
            writer.writerow(ktmi_row(bar, values, timeframe_minutes=self.timeframe_minutes, symbol=self.symbol))


__all__ = ["KTMI_BAR_FIELDS", "KtmiBarJournal", "ktmi_row"]
