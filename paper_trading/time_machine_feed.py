"""History for the Time Machine in the live programs: each symbol's last ~90 days of 5-minute candles from FYERS,
downloaded once per symbol per day (one request; FYERS allows 100 days of 5-minute history per request)."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Callable


def fyers_odds_history(client, today: date, days: int = 90) -> Callable[[str], list]:
    from paper_trading.warmup import parse_history_candles
    cache: dict[str, list] = {}

    def history(symbol: str) -> list:
        if symbol not in cache:
            answer = client.history(symbol, resolution="5", range_from=(today - timedelta(days=days)).isoformat(),
                                    range_to=(today - timedelta(days=1)).isoformat())
            cache[symbol] = parse_history_candles(answer)
        return cache[symbol]

    return history


__all__ = ["fyers_odds_history"]
