"""FYERS history for the data sweep (runs on the owner's PC: needs the daily login).

Read-only: FYERS history API only, never orders.
  * index / India VIX 1-minute: up to 2+ years, fetched in 90-day requests
  * futures 1-minute, continuous series (cont_flag=1) through the current contract
  * futures 5-second (FYERS keeps seconds data only for a short time)
  * current option contracts (strike ladder around spot) 1-minute
"""

from __future__ import annotations

import time
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from market_data.resampling import Candle
from paper_trading.warmup import parse_history_candles

IST = ZoneInfo("Asia/Kolkata")
FYERS_SPOT = {"NIFTY": "NSE:NIFTY50-INDEX", "BANKNIFTY": "NSE:NIFTYBANK-INDEX", "SENSEX": "BSE:SENSEX-INDEX",
              "INDIAVIX": "NSE:INDIAVIX-INDEX"}
CHUNK_DAYS = {"1": 90, "5S": 5, "10S": 5}


def fetch_history(client: Any, symbol: str, *, resolution: str, start: date, end: date, cont_flag: str = "0",
                  pause: float = 0.35, on_error=None) -> list[Candle]:
    """Chunked FYERS history; failed chunks are reported (never silently filled)."""
    step = CHUNK_DAYS.get(resolution, 90)
    candles: dict[int, Candle] = {}
    chunk = start
    while chunk <= end:
        chunk_end = min(chunk + timedelta(days=step - 1), end)
        try:
            response = client.history(symbol, resolution=resolution, range_from=chunk.isoformat(),
                                      range_to=chunk_end.isoformat(), cont_flag=cont_flag)
            for candle in parse_history_candles(response):
                candles[candle.timestamp] = candle
        except Exception as exc:          # one bad chunk must not stop the sweep
            if on_error:
                on_error(f"{symbol} {resolution} {chunk}..{chunk_end}: {exc}")
        chunk = chunk_end + timedelta(days=1)
        if pause:
            time.sleep(pause)
    return [candles[t] for t in sorted(candles)]


def nearest_future(master: dict, underlying: str, today: date) -> str | None:
    """Current-month futures symbol of an index from the FYERS symbol master."""
    best = None
    for symbol, row in master.items():
        ticker = str(row.get("symTicker") or symbol)
        if row.get("underSym") != underlying or not ticker.endswith("FUT"):
            continue
        try:
            expiry = datetime.fromtimestamp(int(row["expiryDate"]), IST).date()
        except (KeyError, ValueError, TypeError):
            continue
        if expiry >= today and (best is None or expiry < best[0]):
            best = (expiry, ticker)
    return best[1] if best else None


def option_ladder_symbols(master: dict, underlying: str, spot: float, step: int, today: date,
                          *, width: int = 5, expiries: int = 2) -> list[str]:
    """Option contracts within +-width strikes of spot for the next ``expiries`` expiries."""
    atm = round(spot / step) * step
    wanted = {atm + k * step for k in range(-width, width + 1)}
    rows = []
    for symbol, row in master.items():
        if row.get("underSym") != underlying or row.get("optType") not in ("CE", "PE"):
            continue
        try:
            expiry = datetime.fromtimestamp(int(row["expiryDate"]), IST).date()
            strike = float(row["strikePrice"])
        except (KeyError, ValueError, TypeError):
            continue
        if expiry >= today and strike in wanted:
            rows.append((expiry, str(row.get("symTicker") or symbol)))
    keep = sorted({e for e, _ in rows})[:expiries]
    return sorted(s for e, s in rows if e in keep)


__all__ = ["FYERS_SPOT", "fetch_history", "nearest_future", "option_ladder_symbols"]
