"""Estimated charges of one intraday (MIS) stock trade on NSE through FYERS (rates as of 2026, all settings).

  brokerage      Rs 20 or 0.03% of the order value, whichever is lower, per order (2 orders)
  STT            0.025% of the SELL value (intraday)
  exchange       0.00297% of turnover (NSE equity)
  SEBI fee       Rs 10 per crore of turnover;  IPFT Rs 10 per crore
  stamp duty     0.003% of the BUY value
  GST            18% on brokerage + exchange + SEBI + IPFT

A SHORT trade sells first and buys back later: the same charges apply (sell = entry, buy = exit).
"""

from __future__ import annotations

from dataclasses import dataclass

from backtest.broker_cost_model import OptionsCostProfile, calculate_options_trade_costs


@dataclass(frozen=True)
class EquityIntradayRates:
    brokerage_cap: float = 20.0
    brokerage_rate: float = 0.0003
    stt_sell_rate: float = 0.00025
    exchange_txn_rate: float = 0.0000297
    sebi_rate: float = 10.0 / 10_000_000.0
    ipft_rate: float = 10.0 / 10_000_000.0
    stamp_buy_rate: float = 0.00003
    gst_rate: float = 0.18


def intraday_charges(entry: float, exit: float, quantity: int, side: str,
                     rates: EquityIntradayRates = EquityIntradayRates()) -> float:
    """Total estimated charges in rupees for one round trip."""
    if quantity <= 0:
        return 0.0
    buy, sell = (entry, exit) if side.upper() == "LONG" else (exit, entry)
    order = lambda price: min(rates.brokerage_cap, rates.brokerage_rate * price * quantity)  # noqa: E731
    profile = OptionsCostProfile(brokerage_per_order=(order(buy) + order(sell)) / 2,
                                 exchange_txn_rate=rates.exchange_txn_rate, stt_sell_rate=rates.stt_sell_rate,
                                 sebi_rate=rates.sebi_rate, stamp_buy_rate=rates.stamp_buy_rate,
                                 ipft_rate=rates.ipft_rate, gst_rate=rates.gst_rate)
    return calculate_options_trade_costs(entry_price=abs(buy), exit_price=abs(sell), quantity=quantity,
                                         profile=profile).total_cost


__all__ = ["EquityIntradayRates", "intraday_charges"]
