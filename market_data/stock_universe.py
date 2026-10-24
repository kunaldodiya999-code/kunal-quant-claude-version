"""The stock universe for scanners: every NSE F&O stock, from FYERS' public contract list.

Read-only. The list changes when NSE adds or drops F&O stocks, so it is rebuilt from the
day's FYERS NSE_FO master (downloaded at most once a day, no login needed).
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

INDEX_FUTURE_TYPE = 11            # FYERS exInstType of index futures (NIFTY, BANKNIFTY, ...)
INDEX_UNDERLYINGS = {"NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "NIFTYNXT50", "SENSEX", "BANKEX"}


def fno_stocks(master: dict) -> list[dict]:
    """[{"stock": "HCLTECH", "symbol": "NSE:HCLTECH-EQ", "lot_size": 350}, ...] sorted by name."""
    stocks: dict[str, dict] = {}
    for row in master.values():
        ticker = str(row.get("symTicker") or "")
        under = row.get("underSym")
        if not ticker.endswith("FUT") or not under or under in INDEX_UNDERLYINGS:
            continue
        if int(row.get("exInstType") or 0) == INDEX_FUTURE_TYPE:
            continue
        stocks.setdefault(under, {"stock": under, "symbol": f"NSE:{under}-EQ",
                                  "lot_size": int(row.get("minLotSize") or 0)})
    return [stocks[k] for k in sorted(stocks)]


def load_fno_stocks(data_folder: str | Path, *, today: date, fetch=None) -> list[dict]:
    from paper_trading.live_support import load_fyers_master
    return fno_stocks(load_fyers_master("NSE_FO", Path(data_folder) / "raw" / "fyers", today=today, fetch=fetch))


__all__ = ["INDEX_UNDERLYINGS", "fno_stocks", "load_fno_stocks"]
