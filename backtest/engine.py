"""Kunal Quant backtest execution engine.

Backward compatible with the original V1/V2 API.

Features:
- LONG / SHORT enum or string directions
- controlled backtest
- sparse entry lists
- completed-candle strategy exits
- protective stop loss
- target
- planned risk
- realized risk
- MAE
- entry slippage
- exit slippage
- fixed transaction charges
- gross P&L
- net P&L
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence

from backtest.costs import (
    CostConfig,
    calculate_entry_execution,
    calculate_exit_execution,
    calculate_trade_costs,
)
from backtest.exit_evaluator import ExitEvaluator
from backtest.models import (
    BacktestBar,
    BacktestResult,
    CompletedTrade,
    ExitReason,
    OpenPosition,
)


# ==============================================================
# HELPERS
# ==============================================================


def _normalize_direction(direction: object) -> str:
    """Normalize enum/string direction to LONG or SHORT."""

    value = getattr(
        direction,
        "value",
        direction,
    )

    value = str(value).upper()

    if value not in {"LONG", "SHORT"}:
        raise ValueError(
            f"Unsupported direction: {direction}"
        )

    return value


# ==============================================================
# ENTRY / EXIT MODELS
# ==============================================================


@dataclass(frozen=True)
class BacktestEntry:
    timestamp: int
    direction: object
    price: float
    quantity: int

    # Original V1/V2 API.
    lot_size: int = 1
    stop_loss: Optional[float] = None
    target: Optional[float] = None

    strategy_id: str = "UNKNOWN"
    config_version: str = "UNKNOWN"

    planned_risk: float = 0.0

    @property
    def stop_loss_price(self) -> Optional[float]:
        return self.stop_loss

    @property
    def target_price(self) -> Optional[float]:
        return self.target


@dataclass(frozen=True)
class BacktestExit:
    timestamp: int
    price: float
    reason: ExitReason


# ==============================================================
# P&L
# ==============================================================


def calculate_trade_pnl(
    direction: object,
    entry_price: float,
    exit_price: float,
    quantity: int,
) -> float:

    if quantity <= 0:
        raise ValueError(
            "Quantity must be greater than zero."
        )

    direction_value = _normalize_direction(
        direction
    )

    if direction_value == "LONG":
        return (
            exit_price - entry_price
        ) * quantity

    return (
        entry_price - exit_price
    ) * quantity


# ==============================================================
# OPEN POSITION
# ==============================================================


def open_position(
    entry: BacktestEntry,
    cost_config: Optional[CostConfig] = None,
) -> OpenPosition:

    if entry.price <= 0:
        raise ValueError(
            "Entry price must be positive."
        )

    if entry.quantity <= 0:
        raise ValueError(
            "Entry quantity must be greater than zero."
        )

    if entry.lot_size <= 0:
        raise ValueError(
            "Lot size must be greater than zero."
        )

    direction = _normalize_direction(
        entry.direction
    )

    # ----------------------------------------------------------
    # STOP LOSS VALIDATION
    # ----------------------------------------------------------

    if entry.stop_loss is not None:

        if entry.stop_loss <= 0:
            raise ValueError(
                "Stop loss price must be positive."
            )

        if direction == "LONG":

            if entry.stop_loss >= entry.price:
                raise ValueError(
                    "LONG stop loss must be below entry price."
                )

        else:

            if entry.stop_loss <= entry.price:
                raise ValueError(
                    "SHORT stop loss must be above entry price."
                )

    # ----------------------------------------------------------
    # TARGET VALIDATION
    # ----------------------------------------------------------

    if entry.target is not None:

        if entry.target <= 0:
            raise ValueError(
                "Target price must be positive."
            )

        if direction == "LONG":

            if entry.target <= entry.price:
                raise ValueError(
                    "LONG target must be above entry price."
                )

        else:

            if entry.target >= entry.price:
                raise ValueError(
                    "SHORT target must be below entry price."
                )

    if entry.planned_risk < 0:
        raise ValueError(
            "Planned risk cannot be negative."
        )

    if cost_config is None:
        cost_config = CostConfig(
            enabled=False
        )

    execution = calculate_entry_execution(
        direction=direction,
        reference_price=entry.price,
        config=cost_config,
    )

    return OpenPosition(
        direction=direction,
        entry_timestamp=entry.timestamp,
        entry_price=execution.execution_price,
        quantity=entry.quantity,

        lot_size=entry.lot_size,

        stop_loss=entry.stop_loss,
        target=entry.target,

        strategy_id=entry.strategy_id,
        config_version=entry.config_version,

        planned_risk=entry.planned_risk,

        entry_reference_price=entry.price,
    )


# ==============================================================
# CLOSE POSITION
# ==============================================================


def close_position(
    position: OpenPosition,
    exit_request: BacktestExit,
    position_bars: Optional[
        Sequence[BacktestBar]
    ] = None,
    cost_config: Optional[CostConfig] = None,
) -> CompletedTrade:

    if exit_request.timestamp < position.entry_timestamp:
        raise ValueError(
            "Exit timestamp cannot be before entry timestamp."
        )

    if exit_request.timestamp == position.entry_timestamp:
        raise ValueError(
            "Exit cannot occur on the entry candle."
        )

    if exit_request.price <= 0:
        raise ValueError(
            "Exit price must be positive."
        )

    if cost_config is None:
        cost_config = CostConfig(
            enabled=False
        )

    if position_bars is None:
        position_bars = ()

    # ----------------------------------------------------------
    # EXIT EXECUTION
    # ----------------------------------------------------------

    exit_execution = calculate_exit_execution(
        direction=position.direction,
        reference_price=exit_request.price,
        config=cost_config,
    )

    actual_exit_price = (
        exit_execution.execution_price
        
    )

    # Original market price before entry slippage.
    entry_reference_price = (
        position.entry_reference_price
        if position.entry_reference_price is not None
        else position.entry_price
    )
    
    # ----------------------------------------------------------
    # GROSS P&L
    # ----------------------------------------------------------
    #
    # Gross P&L is calculated from the ORIGINAL MARKET
    # reference prices.
    #
    # Slippage is accounted for separately below.
    #
    # This prevents slippage from being charged twice.
    #

    gross_pnl = calculate_trade_pnl(
        direction=position.direction,
        entry_price=entry_reference_price,
        exit_price=exit_request.price,
        quantity=position.quantity,
    )

    # ----------------------------------------------------------
    # COSTS
    # ----------------------------------------------------------

    entry_reference_price = (
        position.entry_reference_price
        if position.entry_reference_price is not None
        else position.entry_price
    )

    costs = calculate_trade_costs(
        entry_price=entry_reference_price,
        exit_price=exit_request.price,
        quantity=position.quantity,
        direction=position.direction,
        config=cost_config,
    )

    net_pnl = (
        gross_pnl
        - costs.total_cost
    )

    realized_risk = (
        abs(net_pnl)
        if net_pnl < 0
        else 0.0
    )

    # ----------------------------------------------------------
    # MAE
    # ----------------------------------------------------------

    maximum_adverse_excursion = 0.0

    for bar in position_bars:

        if bar.timestamp <= position.entry_timestamp:
            continue

        if position.direction == "LONG":

            adverse_move = (
                position.entry_price
                - bar.low
            )

        else:

            adverse_move = (
                bar.high
                - position.entry_price
            )

        maximum_adverse_excursion = max(
            maximum_adverse_excursion,
            adverse_move,
        )

    maximum_adverse_excursion *= (
        position.quantity
    )

    # ----------------------------------------------------------
    # HOLDING BARS
    # ----------------------------------------------------------

    holding_bars = sum(
        1
        for bar in position_bars
        if (
            bar.timestamp > position.entry_timestamp
            and bar.timestamp <= exit_request.timestamp
        )
    )

    return CompletedTrade(
        direction=position.direction,

        entry_timestamp=position.entry_timestamp,
        entry_price=position.entry_price,

        exit_timestamp=exit_request.timestamp,
        exit_price=actual_exit_price,

        quantity=position.quantity,

        pnl=gross_pnl,
        net_pnl=net_pnl,

        exit_reason=exit_request.reason,

        strategy_id=position.strategy_id,
        config_version=position.config_version,

        holding_bars=holding_bars,

        planned_risk=position.planned_risk,
        realized_risk=realized_risk,

        maximum_adverse_excursion=(
            maximum_adverse_excursion
        ),

        entry_reference_price=(
            entry_reference_price
        ),

        exit_reference_price=(
            exit_request.price
        ),

        entry_slippage=(
            costs.entry_slippage
        ),

        exit_slippage=(
            costs.exit_slippage
        ),

        entry_fixed_charge=(
            costs.entry_fixed_charge
        ),

        exit_fixed_charge=(
            costs.exit_fixed_charge
        ),

        total_cost=(
            costs.total_cost
        ),
    )


# ==============================================================
# CONTROLLED BACKTEST
# ==============================================================


def run_controlled_backtest(
    starting_capital: float,
    entries_and_exits: Sequence[
        tuple[BacktestEntry, BacktestExit]
    ],
    cost_config: Optional[CostConfig] = None,
) -> BacktestResult:

    if starting_capital <= 0:
        raise ValueError(
            "Starting capital must be positive."
        )

    if cost_config is None:
        cost_config = CostConfig(
            enabled=False
        )

    trades: list[CompletedTrade] = []

    for entry, exit_request in entries_and_exits:

        position = open_position(
            entry=entry,
            cost_config=cost_config,
        )

        trade = close_position(
            position=position,
            exit_request=exit_request,
            position_bars=(),
            cost_config=cost_config,
        )

        trades.append(trade)

    total_net_pnl = sum(
        trade.net_pnl
        for trade in trades
    )

    return BacktestResult(
        trades=tuple(trades),
        initial_capital=starting_capital,
        final_equity=(
            starting_capital
            + total_net_pnl
        ),
    )


# ==============================================================
# BAR-BY-BAR BACKTEST
# ==============================================================


def run_bar_by_bar_backtest(
    bars: Sequence[BacktestBar],
    entries: Sequence[BacktestEntry],
    exit_evaluator: Optional[ExitEvaluator] = None,
    indicator_data: Optional[Sequence[object]] = None,
    initial_capital: float = 100000.0,
    cost_config: Optional[CostConfig] = None,
) -> BacktestResult:

    if not bars:
        raise ValueError(
            "Bars cannot be empty."
        )

    if initial_capital <= 0:
        raise ValueError(
            "Initial capital must be positive."
        )

    if indicator_data is None:

        indicator_data = [
            None
            for _ in bars
        ]

    if len(indicator_data) != len(bars):
        raise ValueError(
            "Bars and indicator_data must have equal length."
        )

    if cost_config is None:
        cost_config = CostConfig(
            enabled=False
        )

    # ----------------------------------------------------------
    # SPARSE ENTRY SUPPORT
    # ----------------------------------------------------------
    #
    # Existing tests intentionally provide:
    #
    # bars    = 4
    # entries = 1
    #
    # Therefore entries are indexed by timestamp.
    #

    entries_by_timestamp = {
        entry.timestamp: entry
        for entry in entries
    }

    trades: list[CompletedTrade] = []

    position: Optional[OpenPosition] = None

    position_bars: list[BacktestBar] = []

    for index, bar in enumerate(bars):

        entry = entries_by_timestamp.get(
            bar.timestamp
        )

        # ======================================================
        # ENTRY
        # ======================================================

        if position is None and entry is not None:

            position = open_position(
                entry=entry,
                cost_config=cost_config,
            )

            position_bars = [bar]

            # No same-candle exit.
            continue

        # ======================================================
        # NO POSITION
        # ======================================================

        if position is None:
            continue

        # ======================================================
        # ACTIVE POSITION
        # ======================================================

        position_bars.append(bar)

        exit_price: Optional[float] = None
        exit_reason: Optional[ExitReason] = None

        # ======================================================
        # 1. STOP LOSS
        # ======================================================

        if position.stop_loss is not None:

            if position.direction == "LONG":

                if bar.low <= position.stop_loss:

                    exit_price = position.stop_loss

                    exit_reason = (
                        ExitReason.STOP_LOSS
                    )

            else:

                if bar.high >= position.stop_loss:

                    exit_price = position.stop_loss

                    exit_reason = (
                        ExitReason.STOP_LOSS
                    )

        # ======================================================
        # 2. TARGET
        # ======================================================

        if (
            exit_reason is None
            and position.target is not None
        ):

            if position.direction == "LONG":

                if bar.high >= position.target:

                    exit_price = position.target

                    exit_reason = (
                        ExitReason.TARGET
                    )

            else:

                if bar.low <= position.target:

                    exit_price = position.target

                    exit_reason = (
                        ExitReason.TARGET
                    )

        # ======================================================
        # 3. STRATEGY EXIT
        # ======================================================
        #
        # IMPORTANT:
        # This exactly matches the existing ExitEvaluator
        # protocol:
        #
        # evaluate(
        #     position,
        #     timestamp,
        #     close_price,
        #     indicator_data
        # )
        #

        if (
            exit_reason is None
            and exit_evaluator is not None
        ):

            evaluation = (
                exit_evaluator.evaluate(
                    position=position,
                    timestamp=bar.timestamp,
                    close_price=bar.close,
                    indicator_data=indicator_data[index],
                )
            )

            if evaluation.should_exit:

                exit_price = bar.close

                exit_reason = (
                    evaluation.reason
                )

        # ======================================================
        # CLOSE
        # ======================================================

        if (
            exit_reason is not None
            and exit_price is not None
        ):

            exit_request = BacktestExit(
                timestamp=bar.timestamp,
                price=exit_price,
                reason=exit_reason,
            )

            trade = close_position(
                position=position,
                exit_request=exit_request,
                position_bars=position_bars,
                cost_config=cost_config,
            )

            trades.append(trade)

            position = None
            position_bars = []

    # ==========================================================
    # END OF DATA
    # ==========================================================

    if position is not None:

        final_bar = bars[-1]

        exit_request = BacktestExit(
            timestamp=final_bar.timestamp,
            price=final_bar.close,
            reason=ExitReason.END_OF_DATA,
        )

        trade = close_position(
            position=position,
            exit_request=exit_request,
            position_bars=position_bars,
            cost_config=cost_config,
        )

        trades.append(trade)

    # ==========================================================
    # RESULT
    # ==========================================================

    total_net_pnl = sum(
        trade.net_pnl
        for trade in trades
    )

    return BacktestResult(
        trades=tuple(trades),
        initial_capital=initial_capital,
        final_equity=(
            initial_capital
            + total_net_pnl
        ),
    )