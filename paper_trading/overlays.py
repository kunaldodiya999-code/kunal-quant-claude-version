"""Chart data for paper trades: entry markers and the entry / stop / target box.

Pure data for the UI, nothing is drawn here. All levels are on the traded OPTION PREMIUM
chart, where a bought call and a bought put are both long premium: the stop is below the
entry and the target is above it. ``signal_direction`` (LONG or SHORT) is what the marker on
the underlying chart shows; SHORT means a bought put, never a short-sold option.
"""
from __future__ import annotations

from typing import Any, Optional

from paper_trading.engine import PaperTradeRecord, PaperTradingEngine
from paper_trading.exit_manager import ExitManager


def _instrument(symbol: str) -> str:
    return "CE" if symbol.endswith("CE") else ("PE" if symbol.endswith("PE") else "")


def trade_overlay(record: PaperTradeRecord, exit_manager: Optional[ExitManager] = None) -> dict[str, Any]:
    p = record.position
    direction = getattr(p.direction, "value", p.direction)
    initial = float(p.stop_loss)
    view = exit_manager.trade_view(record) if exit_manager is not None else {}
    tsl = view.get("tsl_stop")
    # On the option chart the TSL and the initial stop are the same kind of number; on the spot
    # chart the TSL is an index level and is shown separately.
    option_tsl = tsl if view.get("tsl_source") == "OPTION" and view.get("tsl_enabled") else None
    effective = max([initial] + ([option_tsl] if option_tsl is not None else [])) if not record.closed else None
    last_exit = record.exits[-1] if record.exits else None
    risk = p.entry_price - initial
    reward = (p.target - p.entry_price) if p.target is not None else None
    return {
        "trade_id": f"{record.strategy_id.value}:{record.entry_timestamp}:{p.symbol}",
        "strategy_id": record.strategy_id.value,
        "symbol": p.symbol,
        "instrument": _instrument(p.symbol),
        "signal_direction": direction,
        "marker": {"time": record.entry_timestamp, "side": direction,
                   "label": f"{direction} {_instrument(p.symbol)}".strip()},
        "status": "CLOSED" if record.closed else "OPEN",
        "entry_time": record.entry_timestamp, "entry_price": float(p.entry_price),
        "lots": p.lots, "quantity": p.quantity, "remaining_quantity": p.remaining_quantity,
        "initial_stop": initial,
        "tsl": {k: v for k, v in view.items() if k != "comparison"},
        "tsl_comparison": view.get("comparison", {}),
        "effective_stop": effective,
        "target": None if p.target is None else float(p.target),
        "partial_target_done": bool(p.partial_exit_done),
        "risk_per_unit": risk, "reward_per_unit": reward,
        "reward_to_risk": None if (reward is None or risk <= 0) else round(reward / risk, 2),
        "max_loss_at_initial_stop": round(risk * p.quantity, 2),
        "exit_time": None if last_exit is None or not record.closed else last_exit.timestamp,
        "exit_price": None if last_exit is None or not record.closed else float(last_exit.price),
        "exit_reason": None if last_exit is None or not record.closed else last_exit.reason.value,
        "gross_pnl": round(p.gross_pnl, 2),
    }


def trade_overlays(engine: PaperTradingEngine, exit_manager: Optional[ExitManager] = None) -> list[dict[str, Any]]:
    """Every paper trade, oldest first, ready for the chart."""
    records = sorted(engine.all_trades(), key=lambda r: r.entry_timestamp)
    return [trade_overlay(r, exit_manager) for r in records]


__all__ = ["trade_overlay", "trade_overlays"]
