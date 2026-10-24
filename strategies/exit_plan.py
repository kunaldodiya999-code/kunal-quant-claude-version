"""Exit plan shared by every Kunal Quant strategy (owner rule, 25 Oct 2026).

    Reward  1 : [ box ]     a number (1.5, 2, 2.5, 3 or any other): exit the whole trade at that
                            reward:risk target.
                            EMPTY: no fixed target, the trailing stop (TSL) takes the trade out.
    TSL method              one of the owner's TSL presets (paper_trading/tsl_methods.PRESETS),
                            or NONE. Exit when a candle CLOSES beyond the TSL line.

The strategy's own stop (day's high for Gap Reversal, 30% of premium for KTMI options ...) always
protects the trade. With a target AND a TSL, whichever comes first closes the trade.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Optional

from paper_trading.tsl_methods import PRESETS, PRESET_LABELS

NO_TSL = "NONE"
TSL_CHOICES = (NO_TSL, *PRESETS)
TSL_TRIGGERS = ("CLOSE", "TOUCH")
TSL_LABELS = {NO_TSL: "No TSL (stop and target only)", **PRESET_LABELS}


def parse_rr(value) -> Optional[float]:
    """Text or number from the box -> a positive reward ratio, or None for an empty box."""
    if value is None:
        return None
    if isinstance(value, str):
        value = value.strip().replace(",", ".")
        if value.startswith("1:"):
            value = value[2:].strip()
        if value == "":
            return None
    rr = float(value)
    if not rr > 0:
        raise ValueError("the reward ratio must be above 0 (or leave the box empty for a TSL exit)")
    return rr


def default_params() -> dict:
    return {key: dict(params) for key, (_, params) in PRESETS.items()}


@dataclass(frozen=True)
class ExitPlan:
    target_rr: Optional[float] = 2.0            # None (empty box) = no fixed target
    tsl_method: str = "CHANDELIER_9_1.5"        # NONE or a preset key
    tsl_trigger: str = "CLOSE"                  # owner: out when a candle closes beyond the TSL
    method_params: dict = field(default_factory=default_params)

    def __post_init__(self) -> None:
        object.__setattr__(self, "target_rr", parse_rr(self.target_rr))
        if self.tsl_method not in TSL_CHOICES:
            raise ValueError(f"tsl_method must be one of {TSL_CHOICES}")
        if self.tsl_trigger not in TSL_TRIGGERS:
            raise ValueError(f"tsl_trigger must be one of {TSL_TRIGGERS}")
        if self.target_rr is None and self.tsl_method == NO_TSL:
            raise ValueError("with an empty reward box a TSL method is needed (it is the exit)")
        merged = default_params()
        for key, params in (self.method_params or {}).items():
            if key in merged and isinstance(params, dict):
                merged[key].update(params)
        object.__setattr__(self, "method_params", merged)

    @property
    def uses_tsl(self) -> bool:
        return self.tsl_method != NO_TSL

    def method(self) -> tuple[str, dict]:
        kind, _ = PRESETS[self.tsl_method]
        return kind, dict(self.method_params[self.tsl_method])

    def describe(self) -> str:
        target = f"target 1:{self.target_rr:g}" if self.target_rr else "no fixed target"
        tsl = "no TSL" if not self.uses_tsl else f"TSL {TSL_LABELS[self.tsl_method]} ({self.tsl_trigger.lower()})"
        return f"{target}, {tsl}"

    def to_dict(self) -> dict:
        return asdict(self)


__all__ = ["ExitPlan", "NO_TSL", "TSL_CHOICES", "TSL_LABELS", "TSL_TRIGGERS", "default_params", "parse_rr"]
