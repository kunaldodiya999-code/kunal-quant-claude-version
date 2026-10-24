"""Yahoo Finance index history (free, no login). Research use only.

Covers the indexes and India VIX, NOT options or futures.
Limits seen 2026-10-24: 1m = last ~30 days in 8-day requests, 5m = 60 days,
60m = 2 years. Volume for indexes is 0. Known artifacts are handled by the
quality checker (missing minutes, official close stamped on the last bars).
"""

from __future__ import annotations

import json
import time
import urllib.request
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from market_data.resampling import Candle

IST = ZoneInfo("Asia/Kolkata")
YAHOO_SYMBOLS = {"NIFTY": "^NSEI", "BANKNIFTY": "^NSEBANK", "SENSEX": "^BSESN", "INDIAVIX": "^INDIAVIX"}
URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval={interval}&period1={p1}&period2={p2}"
# interval -> (max days back, max days per request)
LIMITS = {"1m": (29, 7), "5m": (59, 59), "60m": (729, 729)}


def _get(url: str) -> dict:
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def parse_chart(payload: dict) -> list[Candle]:
    """Candles from a Yahoo chart response; bars with any missing value are dropped."""
    result = (payload.get("chart") or {}).get("result")
    if not result:
        error = (payload.get("chart") or {}).get("error")
        raise ValueError(f"Yahoo returned no data: {error}")
    data = result[0]
    quote = data["indicators"]["quote"][0]
    out = []
    for i, ts in enumerate(data.get("timestamp") or []):
        o, h, l, c = (quote[k][i] for k in ("open", "high", "low", "close"))
        if None in (o, h, l, c):
            continue                       # a hole stays a hole: never filled
        volume = quote.get("volume", [None] * (i + 1))[i]
        out.append(Candle(int(ts), round(o, 2), round(h, 2), round(l, 2), round(c, 2),
                          None if volume is None else int(volume)))
    return out


def fetch(key: str, interval: str, *, now: datetime | None = None, days: int | None = None,
          get=_get, pause: float = 0.5) -> list[Candle]:
    if key not in YAHOO_SYMBOLS:
        raise ValueError(f"Yahoo source has no '{key}'. Choose from {', '.join(YAHOO_SYMBOLS)}.")
    if interval not in LIMITS:
        raise ValueError(f"interval must be one of {tuple(LIMITS)}")
    max_back, per_request = LIMITS[interval]
    now = now or datetime.now(IST)
    start = now - timedelta(days=min(days or max_back, max_back))
    symbol = urllib.request.quote(YAHOO_SYMBOLS[key])
    candles: dict[int, Candle] = {}
    chunk_start = start
    while chunk_start < now:
        chunk_end = min(chunk_start + timedelta(days=per_request), now)
        payload = get(URL.format(symbol=symbol, interval=interval,
                                 p1=int(chunk_start.timestamp()), p2=int(chunk_end.timestamp())))
        for candle in parse_chart(payload):
            candles[candle.timestamp] = candle
        chunk_start = chunk_end
        if pause:
            time.sleep(pause)
    return [candles[t] for t in sorted(candles)]


__all__ = ["LIMITS", "YAHOO_SYMBOLS", "fetch", "parse_chart"]
