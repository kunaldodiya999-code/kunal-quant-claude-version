"""A pretend FYERS for the tests (no network): prices, 1-minute candles and funds that the test sets."""

from datetime import date, datetime
from zoneinfo import ZoneInfo

from terminal.candles import Candle

IST = ZoneInfo("Asia/Kolkata")
DAY = date(2026, 10, 28)
EXPIRY = int(datetime(2026, 11, 4, 15, 30, tzinfo=IST).timestamp())


def at(h: int, m: int, s: int = 0) -> datetime:
    return datetime(DAY.year, DAY.month, DAY.day, h, m, s, tzinfo=IST)


def master(strikes=range(24500, 25550, 50), lot=65):
    out = {}
    for k in strikes:
        for t in ("CE", "PE"):
            sym = f"NSE:NIFTY26N04{k}{t}"
            out[sym] = {"underSym": "NIFTY", "optType": t, "strikePrice": k, "expiryDate": EXPIRY,
                        "symTicker": sym, "minLotSize": lot}
    out["NSE:NIFTY26NOVFUT"] = {"underSym": "NIFTY", "optType": "XX", "strikePrice": -1,
                                "expiryDate": int(datetime(2026, 11, 25, 15, 30, tzinfo=IST).timestamp()),
                                "symTicker": "NSE:NIFTY26NOVFUT", "minLotSize": lot}
    return out


class FakeFyers:
    model = None

    def __init__(self, funds=50000.0):
        self.prices: dict[str, dict] = {}
        self.candles: dict[str, list[Candle]] = {}
        self.fund = funds
        self.calls = []

    def set_price(self, symbol, ltp, bid=None, ask=None):
        self.prices[symbol] = {"ltp": float(ltp), "bid": float(bid if bid is not None else ltp - 0.5),
                               "ask": float(ask if ask is not None else ltp + 0.5)}

    def add_minutes(self, symbol, start: datetime, closes):
        rows = self.candles.setdefault(symbol, [])
        t0 = int(start.timestamp())
        for i, c in enumerate(closes):
            rows.append(Candle(t0 + 60 * i, c, c + 1, c - 1, c, 100))

    def quotes(self, symbols):
        self.calls.append(("quotes", tuple(symbols)))
        return {s: dict(self.prices[s]) for s in symbols if s in self.prices}

    def minutes(self, symbol, start, end):
        self.calls.append(("minutes", symbol))
        return list(self.candles.get(symbol, []))

    def available_funds(self):
        return self.fund
