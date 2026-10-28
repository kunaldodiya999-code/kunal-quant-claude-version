"""KTMI Uni Lite settings, mirroring every input of KTMI_Uni_Lite_FINAL.pine.

Indicator configuration only. Calculations are delegated to the locked KTMI
Universal engine (``indicators.ktmi.universal``) restricted to EMA + TRIX,
which is exactly what Uni Lite allows.

Trigger values follow the Pine "empty box = off" rule: ``None`` disables that
arrow, like an empty text box in TradingView.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Optional

from indicators.ktmi.config import SOURCE_OPTIONS, KTMIConfig, MomentumConfig

LOCKED_PINE_FILE = "KTMI_Uni_Lite_FINAL.pine"
LOCKED_PINE_SHA256 = "47fcdf24c400d3b7f52595a0574091db81902d60df67ca9afe3ad3f979b50fbe"


@dataclass(frozen=True)
class UniLiteModule:
    """One of the three KTMI lines (Momentum, Long Momentum, Short Momentum)."""

    source: str = "Close"
    speed_length: int = 5
    signal_length: int = 9
    enabled: bool = True

    def __post_init__(self) -> None:
        if self.source not in SOURCE_OPTIONS:
            raise ValueError(f"source must be one of {SOURCE_OPTIONS}")
        if self.speed_length < 1 or self.signal_length < 1:
            raise ValueError("speed_length and signal_length must be >= 1")

    def to_momentum_config(self) -> MomentumConfig:
        # Uni Lite: EMA smoothing and TRIX calculation only.
        return MomentumConfig(
            source=self.source,
            speed_length=self.speed_length,
            signal_length=self.signal_length,
            smoothing="EMA",
            enabled=self.enabled,
            calculation="TRIX",
        )


@dataclass(frozen=True)
class UniLiteConfig:
    """All calculation and trigger inputs. Defaults = the Pine source defaults."""

    momentum: UniLiteModule = UniLiteModule(source="Close")
    long_momentum: UniLiteModule = UniLiteModule(source="High")
    short_momentum: UniLiteModule = UniLiteModule(source="Low")

    momentum_buy_trigger: Optional[float] = 0.5
    momentum_sell_trigger: Optional[float] = -0.5
    long_buy_trigger: Optional[float] = 0.5
    long_sell_trigger: Optional[float] = None
    short_buy_trigger: Optional[float] = 0.5
    short_sell_trigger: Optional[float] = None

    # Display-only inputs, kept so a saved profile round-trips every setting.
    center_level: float = 0.0
    upper_level: float = 0.5
    lower_level: float = -0.5
    oversold_scale: float = -3.0
    overbought_scale: float = 3.0

    def to_ktmi_config(self) -> KTMIConfig:
        return KTMIConfig(
            momentum=self.momentum.to_momentum_config(),
            long_momentum=self.long_momentum.to_momentum_config(),
            short_momentum=self.short_momentum.to_momentum_config(),
        )


def parse_trigger(text: str | None) -> Optional[float]:
    """Pine ``str.tonumber``: empty or non-numeric text means the arrow is off."""
    if text is None:
        return None
    try:
        return float(str(text).strip())
    except ValueError:
        return None


# Exact Pine source defaults.
UNI_LITE_DEFAULTS = UniLiteConfig()

# The owner's current trading profile (2026-10-24, matches the TradingView
# screenshots): only Long Buy (Long Speed crosses above +0.5 -> BUY CE) and
# Short Buy (Short Speed crosses above +0.5 -> BUY PE). Every other arrow is
# silent. Calculations are identical to the defaults.
UNI_LITE_CORE = replace(
    UNI_LITE_DEFAULTS,
    momentum_buy_trigger=None,
    momentum_sell_trigger=None,
)


__all__ = [
    "LOCKED_PINE_FILE",
    "LOCKED_PINE_SHA256",
    "UNI_LITE_CORE",
    "UNI_LITE_DEFAULTS",
    "UniLiteConfig",
    "UniLiteModule",
    "parse_trigger",
]
