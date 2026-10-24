"""Transaction costs for paper-traded NSE index options.

The paper engine only BUYS premium and later SELLS it, so every entry is a BUY
order and every exit is a SELL order. Defaults are the rates published for
NSE index options in October 2026 (STT 0.15% of premium on the sell side since
1 April 2026; NSE options exchange charge 0.03553% of premium on each side;
SEBI fee Rs 10 per crore; stamp duty 0.003% on the buy side; GST 18% on
brokerage + exchange charge + SEBI fee) with Rs 20 flat brokerage per order.
They are DEFAULTS, not guarantees: check them against your broker's contract
note and edit them. BSE (Sensex) options use a different exchange charge.
Slippage is not a cost here; it belongs in the fill price.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite


@dataclass(frozen=True)
class OptionCostModel:
    brokerage_per_order: float = 20.0
    stt_sell_pct: float = 0.15          # % of premium turnover, sell side only
    exchange_txn_pct: float = 0.03553   # % of premium turnover, both sides
    sebi_fee_pct: float = 0.0001        # Rs 10 per crore, both sides
    stamp_buy_pct: float = 0.003        # % of premium turnover, buy side only
    gst_pct: float = 18.0               # on brokerage + exchange charge + SEBI fee

    def __post_init__(self) -> None:
        for name, value in self.__dict__.items():
            if not (isfinite(value) and value >= 0):
                raise ValueError(f"{name} must be a finite number, zero or more.")

    @classmethod
    def zero(cls) -> "OptionCostModel":
        return cls(0.0, 0.0, 0.0, 0.0, 0.0, 0.0)

    def order_cost(self, *, side: str, price: float, quantity: int) -> float:
        side = str(side).upper()
        if side not in ("BUY", "SELL"):
            raise ValueError("side must be BUY or SELL.")
        turnover = float(price) * int(quantity)
        exchange = turnover * self.exchange_txn_pct / 100.0
        sebi = turnover * self.sebi_fee_pct / 100.0
        gst = (self.brokerage_per_order + exchange + sebi) * self.gst_pct / 100.0
        stt = turnover * self.stt_sell_pct / 100.0 if side == "SELL" else 0.0
        stamp = turnover * self.stamp_buy_pct / 100.0 if side == "BUY" else 0.0
        return self.brokerage_per_order + exchange + sebi + gst + stt + stamp


__all__ = ["OptionCostModel"]
