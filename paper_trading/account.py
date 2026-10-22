"""Live paper account: net liquidation value (NLV) and the day's P&L.

    equity = starting capital + realised P&L + unrealised mark-to-market - costs

* Realised P&L comes from the journal-backed engine (closed trades and partial exits).
* Unrealised P&L marks every open position at a live price supplied by the caller.
  A position with no usable price is reported in ``marks_missing`` instead of being
  silently valued at zero.
* Costs are the costs INCURRED so far (entry orders, plus exit orders already made).
  Exit costs of positions still open are not estimated.
* Opening equity of an IST day = starting capital + realised P&L of every exit before
  that day, minus costs of every order before that day. This is the cash balance at the
  start of the day, so yesterday's net result becomes today's opening balance.
  Unrealised P&L of a position carried over midnight is not part of the opening balance.
* Costs are recomputed from the journal with the current cost model, so a restart
  needs no extra state.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from math import isfinite
from typing import Mapping, Optional
from zoneinfo import ZoneInfo

from paper_trading.costs import OptionCostModel
from paper_trading.engine import PaperStrategyId, PaperTradingEngine

IST = ZoneInfo("Asia/Kolkata")


@dataclass(frozen=True)
class EquitySnapshot:
    timestamp: int
    starting_capital: float
    realized_pnl: float          # gross, closed trades and partial exits
    unrealized_pnl: float        # open positions marked to market
    costs: float                 # incurred so far
    equity: float                # net liquidation value
    opening_equity: float        # balance at the start of this IST day
    day_pnl: float               # equity - opening_equity
    marks_missing: tuple[PaperStrategyId, ...]


class PaperAccount:
    def __init__(self, engine: PaperTradingEngine, *, starting_capital: float = 100_000.0,
                 cost_model: Optional[OptionCostModel] = None) -> None:
        if not (isfinite(starting_capital) and starting_capital > 0):
            raise ValueError("starting_capital must be positive.")
        self.engine = engine
        self.starting_capital = float(starting_capital)
        self.cost_model = cost_model if cost_model is not None else OptionCostModel()

    @staticmethod
    def _day(timestamp: int):
        return datetime.fromtimestamp(int(timestamp), IST).date()

    def snapshot(self, timestamp: int, marks: Mapping[PaperStrategyId | str, float] | None = None
                 ) -> EquitySnapshot:
        by_value = {getattr(k, "value", k): v for k, v in (marks or {}).items()}
        today = self._day(timestamp)
        realized = costs = unrealized = 0.0
        opening = self.starting_capital
        missing: list[PaperStrategyId] = []
        for record in self.engine.all_trades():
            position = record.position
            realized += position.gross_pnl
            entry_cost = self.cost_model.order_cost(
                side="BUY", price=position.entry_price, quantity=position.quantity)
            costs += entry_cost
            if self._day(record.entry_timestamp) < today:
                opening -= entry_cost
            for event in record.exits:
                exit_cost = self.cost_model.order_cost(
                    side="SELL", price=event.price, quantity=event.quantity)
                costs += exit_cost
                if self._day(event.timestamp) < today:
                    opening += event.pnl - exit_cost
            if not record.closed:
                mark = by_value.get(record.strategy_id.value)
                if mark is None or not isfinite(float(mark)) or float(mark) <= 0:
                    missing.append(record.strategy_id)
                else:
                    unrealized += self.engine.lifecycle.calculate_pnl(
                        direction=position.direction, entry_price=position.entry_price,
                        exit_price=float(mark), quantity=position.remaining_quantity)
        equity = self.starting_capital + realized + unrealized - costs
        return EquitySnapshot(
            timestamp=int(timestamp), starting_capital=self.starting_capital,
            realized_pnl=realized, unrealized_pnl=unrealized, costs=costs, equity=equity,
            opening_equity=opening, day_pnl=equity - opening, marks_missing=tuple(missing),
        )


__all__ = ["EquitySnapshot", "PaperAccount"]
