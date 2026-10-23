"""Capital allocation and lot sizing for bought option premium.

    cost per lot = premium x lot size
    lots         = floor(allocated capital / cost per lot)     (whole lots only)
    deployed     = lots x cost per lot                          (never above the budget)

The budget is a HARD ceiling. If it cannot buy one complete lot there is no trade, and the
reason names the exact shortfall. Arithmetic uses Decimal so a budget that exactly equals N
lots never loses a lot to floating-point noise.

The owner sets the budget either as a percent preset or as a rupee amount. The two inputs
are two views of one setting: the last one used decides the mode (PERCENT follows the account
balance as it changes; AMOUNT stays fixed) and the other is derived for display.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal
from math import isfinite
from pathlib import Path
from typing import Optional

PERCENT_PRESETS: tuple[int, ...] = (10, 20, 30, 40, 50, 60, 70, 80, 90, 100)
_CENT = Decimal("0.01")


def _dec(value: float) -> Decimal:
    if not isfinite(float(value)):
        raise ValueError("Value must be finite.")
    return Decimal(str(float(value)))


@dataclass(frozen=True)
class SizingResult:
    budget: float
    premium: float
    lot_size: int
    cost_per_lot: float
    lots: int
    quantity: int
    deployed: float
    unallocated: float

    @property
    def tradable(self) -> bool:
        return self.lots >= 1


def calculate_lots(budget: float, premium: float, lot_size: int) -> SizingResult:
    if not (isfinite(float(premium)) and float(premium) > 0):
        raise ValueError("Premium must be finite and positive.")
    if int(lot_size) < 1:
        raise ValueError("Lot size must be at least 1.")
    if not (isfinite(float(budget)) and float(budget) >= 0):
        raise ValueError("Budget must be finite and not negative.")
    cost = _dec(premium) * int(lot_size)
    lots = int((_dec(budget) / cost).to_integral_value(rounding=ROUND_DOWN))
    deployed = cost * lots
    return SizingResult(
        budget=float(budget), premium=float(premium), lot_size=int(lot_size),
        cost_per_lot=float(cost), lots=lots, quantity=lots * int(lot_size),
        deployed=float(deployed), unallocated=float(_dec(budget) - deployed),
    )


def sizing_warning(result: SizingResult) -> Optional[str]:
    """A clear message when the budget cannot buy one whole lot, else None."""
    if result.tradable:
        return None
    short = result.cost_per_lot - result.budget
    return (f"Trade not taken: budget Rs {result.budget:,.2f} cannot buy one lot. "
            f"One lot ({result.lot_size} units at Rs {result.premium:,.2f}) costs "
            f"Rs {result.cost_per_lot:,.2f}; short by Rs {short:,.2f}. "
            f"Raise the allocation or wait for a cheaper premium.")


def amount_from_percent(balance: float, percent: float) -> float:
    if not (isfinite(balance) and balance > 0):
        raise ValueError("Balance must be positive.")
    if not (isfinite(percent) and 0 < percent <= 100):
        raise ValueError("Percent must be above 0 and at most 100.")
    return float((_dec(balance) * _dec(percent) / 100).quantize(_CENT, rounding=ROUND_HALF_UP))


def percent_from_amount(balance: float, amount: float) -> float:
    if not (isfinite(balance) and balance > 0):
        raise ValueError("Balance must be positive.")
    if not (isfinite(amount) and amount > 0):
        raise ValueError("Amount must be positive.")
    if amount > balance:
        raise ValueError(f"Amount Rs {amount:,.2f} is more than the balance Rs {balance:,.2f}.")
    return float((_dec(amount) / _dec(balance) * 100).quantize(_CENT, rounding=ROUND_HALF_UP))


@dataclass(frozen=True)
class BudgetDecision:
    requested: float
    budget: float
    limited_by: Optional[str]   # "balance", "cash" or None


@dataclass(frozen=True)
class AllocationSetting:
    mode: str      # "PERCENT" or "AMOUNT"
    value: float   # percent, or rupees

    def __post_init__(self) -> None:
        if self.mode == "PERCENT":
            if not (isfinite(self.value) and 0 < self.value <= 100):
                raise ValueError("Percent must be above 0 and at most 100.")
        elif self.mode == "AMOUNT":
            if not (isfinite(self.value) and self.value > 0):
                raise ValueError("Amount must be positive.")
        else:
            raise ValueError("mode must be PERCENT or AMOUNT.")

    @classmethod
    def from_percent(cls, percent: float) -> "AllocationSetting":
        return cls("PERCENT", float(percent))

    @classmethod
    def from_amount(cls, amount: float) -> "AllocationSetting":
        return cls("AMOUNT", float(amount))

    def requested(self, balance: float) -> float:
        return amount_from_percent(balance, self.value) if self.mode == "PERCENT" else self.value

    def view(self, balance: float) -> dict:
        """Both inputs for the two-way synced UI controls."""
        amount = self.requested(balance)
        over = amount > balance
        percent = self.value if self.mode == "PERCENT" else (100.0 if over else percent_from_amount(balance, amount))
        return {"mode": self.mode, "percent": percent, "amount": amount, "over_balance": over,
                "presets": list(PERCENT_PRESETS)}

    def budget(self, *, balance: float, available_cash: float) -> BudgetDecision:
        """Requested budget capped by the balance and by the cash not already deployed."""
        requested = self.requested(balance)
        ceiling, reason = requested, None
        if balance < ceiling:
            ceiling, reason = balance, "balance"
        if available_cash < ceiling:
            ceiling, reason = max(available_cash, 0.0), "cash"
        return BudgetDecision(requested=requested, budget=float(ceiling), limited_by=reason)


class AllocationStore:
    """Holds the current allocation setting; the owner's last choice survives a restart."""

    def __init__(self, default: AllocationSetting, journal_dir: str | Path | None = None) -> None:
        self._setting = default
        self._path = None if journal_dir is None else Path(journal_dir) / "allocation.json"
        if self._path is not None and self._path.exists():
            try:
                data = json.loads(self._path.read_text(encoding="utf-8"))
                self._setting = AllocationSetting(str(data["mode"]), float(data["value"]))
            except (ValueError, KeyError, TypeError) as exc:
                raise ValueError(f"{self._path} is unreadable; fix or delete it to use the default.") from exc

    @property
    def setting(self) -> AllocationSetting:
        return self._setting

    def set(self, setting: AllocationSetting) -> AllocationSetting:
        self._setting = setting
        if self._path is not None:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(json.dumps({"mode": setting.mode, "value": setting.value}), encoding="utf-8")
        return setting


__all__ = [
    "AllocationSetting", "AllocationStore", "BudgetDecision", "PERCENT_PRESETS", "SizingResult",
    "amount_from_percent", "calculate_lots", "percent_from_amount", "sizing_warning",
]
