"""Reusable trade-audit utilities for Kunal Quant.

This module does not change trading logic. It validates and summarizes
completed trade records produced by a backtest/integration runner.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Protocol


class ExitLike(Protocol):
    timestamp: int
    quantity: int
    pnl: float
    reason: object


class PositionLike(Protocol):
    strategy_id: str
    symbol: str
    direction: object
    quantity: int
    remaining_quantity: int
    gross_pnl: float


class TradeRecordLike(Protocol):
    trade: object
    exit: ExitLike


@dataclass(frozen=True)
class TradeAuditExit:
    exit_number: int
    timestamp: int
    quantity: int
    price: float
    pnl: float
    reason: str
    remaining_quantity: int
    remaining_lots: int


@dataclass(frozen=True)
class TradeAuditSummary:
    trade_key: int
    strategy_id: str
    symbol: str
    direction: str
    entry_price: float
    entry_quantity: int
    exit_quantity: int
    exit_count: int
    partial_exit_count: int
    total_pnl: float
    position_gross_pnl: float
    quantity_balanced: bool
    pnl_balanced: bool
    final_exit_reason: str
    first_exit_timestamp: int | None
    final_exit_timestamp: int | None
    exits: tuple[TradeAuditExit, ...]


@dataclass(frozen=True)
class AuditTotals:
    trades: int
    balanced_quantity: int
    balanced_pnl: int
    total_exit_events: int
    partial_exit_events: int
    stop_exits: int
    target_exits: int
    kama_exits: int
    end_of_data_exits: int
    gross_pnl: float


def _value(value: object) -> str:
    return getattr(value, "value", str(value))


def summarize_trade(trade_record_group: dict) -> TradeAuditSummary:
    trade = trade_record_group["trade"]
    position = trade.position
    exits = list(trade_record_group["exits"])

    entry_quantity = int(getattr(position, "quantity"))

    exit_quantity = sum(
        int(exit_event.quantity)
        for exit_event in exits
    )

    total_pnl = sum(
        float(exit_event.pnl)
        for exit_event in exits
    )

    position_gross_pnl = float(
        getattr(position, "gross_pnl")
    )

    audit_exits = tuple(
        TradeAuditExit(
            exit_number=index,
            timestamp=int(exit_event.timestamp),
            quantity=int(exit_event.quantity),
            price=float(getattr(exit_event, "price")),
            pnl=float(exit_event.pnl),
            reason=_value(exit_event.reason),
            remaining_quantity=int(exit_event.remaining_quantity),
            remaining_lots=int(
                getattr(exit_event, "remaining_lots", 0)
            ),
        )
        for index, exit_event in enumerate(exits, start=1)
    )

    partial_exit_count = sum(
        1
        for exit_event in exits
        if _value(exit_event.reason) == "TARGET_3R"
        and int(exit_event.remaining_quantity) > 0
    )

    final_reason = (
        _value(exits[-1].reason)
        if exits
        else "NO_EXIT"
    )

    return TradeAuditSummary(
        trade_key=id(trade),
        strategy_id=str(position.strategy_id),
        symbol=str(trade.contract.symbol),
        direction=_value(position.direction),
        entry_price=float(position.entry_price),
        entry_quantity=entry_quantity,
        exit_quantity=exit_quantity,
        exit_count=len(exits),
        partial_exit_count=partial_exit_count,
        total_pnl=total_pnl,
        position_gross_pnl=position_gross_pnl,
        quantity_balanced=(exit_quantity == entry_quantity),
        pnl_balanced=(
            abs(total_pnl - position_gross_pnl) < 1e-9
        ),
        final_exit_reason=final_reason,
        first_exit_timestamp=(
            int(exits[0].timestamp) if exits else None
        ),
        final_exit_timestamp=(
            int(exits[-1].timestamp) if exits else None
        ),
        exits=audit_exits,
    )


def build_trade_audit(
    completed_trade_groups: Iterable[dict],
) -> list[TradeAuditSummary]:
    return [
        summarize_trade(group)
        for group in completed_trade_groups
    ]


def calculate_audit_totals(
    summaries: Iterable[TradeAuditSummary],
) -> AuditTotals:
    rows = list(summaries)

    def count(reason: str) -> int:
        return sum(
            1
            for row in rows
            if row.final_exit_reason == reason
        )

    return AuditTotals(
        trades=len(rows),
        balanced_quantity=sum(
            row.quantity_balanced for row in rows
        ),
        balanced_pnl=sum(
            row.pnl_balanced for row in rows
        ),
        total_exit_events=sum(
            row.exit_count for row in rows
        ),
        partial_exit_events=sum(
            row.partial_exit_count for row in rows
        ),
        stop_exits=count("STOP_LOSS"),
        target_exits=count("TARGET_3R"),
        kama_exits=count("KAMA_EXIT"),
        end_of_data_exits=count("END_OF_DATA"),
        gross_pnl=sum(row.total_pnl for row in rows),
    )


def find_unbalanced_trades(
    summaries: Iterable[TradeAuditSummary],
) -> list[TradeAuditSummary]:
    return [
        row
        for row in summaries
        if not row.quantity_balanced or not row.pnl_balanced
    ]
