"""Buying and selling the option: LIMIT orders with a buffer, NEVER market orders (owner rule).

  BUY  limit = price + buffer (owner: price 100 -> 102), rounded UP to the 0.05 tick
  SELL limit = price - buffer (owner: 2), rounded DOWN to the tick (stop, cross exit, 15:10)

PaperBroker (default): nothing is sent; the fill is the real ask (buy) / bid (sell) at that moment, never worse
than the limit. RealBroker: FYERS orders through live_trading/ (copied, tested: limit + re-price only, a test fails
on any market order). It is used ONLY when "Real orders" is ON in the settings AND the day is armed
(``python arm_real_orders.py``); FYERS also needs your whitelisted static IP for API orders (SEBI 2026).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Callable, Optional

from live_trading.orders import LiveOrderPolicy, round_to_tick


@dataclass(frozen=True)
class Fill:
    ok: bool
    price: float
    qty: int
    limit: float
    message: str


def buy_limit(ltp: float, buffer: float, tick: float = 0.05) -> float:
    return round_to_tick(ltp + buffer, tick, "BUY")


def sell_limit(ltp: float, buffer: float, tick: float = 0.05) -> float:
    return max(round_to_tick(ltp - buffer, tick, "SELL"), tick)


class PaperBroker:
    mode = "PAPER"

    def __init__(self, buffer_buy: float = 2.0, buffer_sell: float = 2.0) -> None:
        self.buffer_buy, self.buffer_sell = buffer_buy, buffer_sell

    def buy(self, symbol: str, qty: int, quote: dict, lot_size: int) -> Fill:
        limit = buy_limit(quote["ltp"], self.buffer_buy)
        ask = quote.get("ask") or 0
        price = ask if 0 < ask <= limit else min(quote["ltp"], limit)
        return Fill(True, round(price, 2), qty, limit, f"PAPER BUY limit {limit}")

    def sell(self, symbol: str, qty: int, quote: dict, lot_size: int) -> Fill:
        limit = sell_limit(quote["ltp"], self.buffer_sell)
        bid = quote.get("bid") or 0
        price = bid if bid >= limit else max(quote["ltp"], limit)
        return Fill(True, round(price, 2), qty, limit, f"PAPER SELL limit {limit}")


class RealBroker:
    """FYERS limit orders (live_trading.executor: buy at price + buffer, re-priced, capped; sells re-priced)."""
    mode = "REAL"

    def __init__(self, model, journal: Path, price_source: Callable[[str], float], *, buffer_buy: float = 2.0,
                 buffer_sell: float = 2.0) -> None:
        from live_trading.executor import LimitOrderExecutor
        from live_trading.gateway import FyersOrderGateway
        policy = LiveOrderPolicy(entry_buffer=buffer_buy, exit_buffer=buffer_sell, max_entry_chase_points=1.0)
        self.executor = LimitOrderExecutor(FyersOrderGateway(model, journal_path=journal, product_type="INTRADAY"),
                                           policy, price_source)

    def _run(self, kind: str, symbol: str, qty: int, quote: dict, lot_size: int) -> Fill:
        r = self.executor.execute(kind=kind, symbol=symbol, qty=qty, lot_size=lot_size, reference=quote["ltp"],
                                  tag="KFT")
        ok = r.status in ("FILLED",) or (kind == "ENTRY" and r.status == "PARTIAL" and r.filled_qty > 0)
        return Fill(ok, float(r.avg_price or quote["ltp"]), int(r.filled_qty or 0), 0.0, f"{r.status}: {r.message}")

    def buy(self, symbol, qty, quote, lot_size) -> Fill:
        return self._run("ENTRY", symbol, qty, quote, lot_size)

    def sell(self, symbol, qty, quote, lot_size) -> Fill:
        return self._run("EXIT", symbol, qty, quote, lot_size)


def real_orders_allowed(setting_on: bool, armed_folder: Path, today: date) -> bool:
    from live_trading.switch import LiveSwitch
    return bool(setting_on) and LiveSwitch(armed_folder).armed_for(today)


__all__ = ["Fill", "PaperBroker", "RealBroker", "buy_limit", "real_orders_allowed", "sell_limit"]
