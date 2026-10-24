"""Configurable broker-realistic cost model for NSE equity-index options.

The accounting engine is separate from strategy/execution logic. Regulatory and
broker rates are explicit inputs so historical backtests can select the
applicable regime without changing trading behavior.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class OptionsCostProfile:
    brokerage_per_order: float = 20.0
    exchange_txn_rate: float = 0.000355299
    stt_sell_rate: float = 0.0015
    sebi_rate: float = 10.0 / 10_000_000.0
    stamp_buy_rate: float = 0.00003
    ipft_rate: float = 50.0 / 10_000_000.0
    gst_rate: float = 0.18

    def __post_init__(self) -> None:
        for name in (
            "exchange_txn_rate",
            "stt_sell_rate",
            "sebi_rate",
            "stamp_buy_rate",
            "ipft_rate",
            "gst_rate",
        ):
            if getattr(self, name) < 0:
                raise ValueError(f"{name} must be >= 0")
        if self.brokerage_per_order < 0:
            raise ValueError("brokerage_per_order must be >= 0")


@dataclass(frozen=True)
class TradeCostBreakdown:
    buy_turnover: float
    sell_turnover: float
    turnover: float
    brokerage: float
    exchange_transaction: float
    stt: float
    sebi: float
    stamp_duty: float
    ipft: float
    gst: float
    total_cost: float
    net_pnl: float


def fyers_options_profile(trade_date: date) -> OptionsCostProfile:
    """Return the FYERS/NSE option cost regime applicable to a trade date.

    STT changed from 0.10% to 0.15% on option premium sold from 2026-04-01.
    Other rates remain explicit profile inputs so future regulatory changes can
    be represented without changing the accounting engine.
    """
    stt = 0.0010 if trade_date < date(2026, 4, 1) else 0.0015
    return OptionsCostProfile(stt_sell_rate=stt)


def calculate_options_trade_costs(
    *,
    entry_price: float,
    exit_price: float,
    quantity: int,
    entry_orders: int = 1,
    exit_orders: int = 1,
    profile: OptionsCostProfile | None = None,
    gross_pnl: float | None = None,
) -> TradeCostBreakdown:
    if entry_price < 0 or exit_price < 0:
        raise ValueError("prices must be >= 0")
    if quantity <= 0:
        raise ValueError("quantity must be > 0")
    if entry_orders <= 0 or exit_orders <= 0:
        raise ValueError("order counts must be > 0")

    p = profile or OptionsCostProfile()
    buy_turnover = entry_price * quantity
    sell_turnover = exit_price * quantity
    turnover = buy_turnover + sell_turnover

    brokerage = p.brokerage_per_order * (entry_orders + exit_orders)
    exchange_transaction = turnover * p.exchange_txn_rate
    stt = sell_turnover * p.stt_sell_rate
    sebi = turnover * p.sebi_rate
    stamp_duty = buy_turnover * p.stamp_buy_rate
    ipft = turnover * p.ipft_rate
    gst = p.gst_rate * (
        brokerage + exchange_transaction + sebi + ipft
    )
    total = (
        brokerage
        + exchange_transaction
        + stt
        + sebi
        + stamp_duty
        + ipft
        + gst
    )

    gross = (
        gross_pnl
        if gross_pnl is not None
        else (exit_price - entry_price) * quantity
    )

    return TradeCostBreakdown(
        buy_turnover=buy_turnover,
        sell_turnover=sell_turnover,
        turnover=turnover,
        brokerage=brokerage,
        exchange_transaction=exchange_transaction,
        stt=stt,
        sebi=sebi,
        stamp_duty=stamp_duty,
        ipft=ipft,
        gst=gst,
        total_cost=total,
        net_pnl=gross - total,
    )
