"""HFT Gap-Open Strategy V1 configuration.

Experimental/research-only configuration. The strategy is disabled by default
and is isolated from the locked KTMI, option resolver, lifecycle, accounting,
and normal option-trading modules.
"""
from __future__ import annotations

HFT_GAP_OPEN_ENABLED_DEFAULT = False

# Current research price path: actual historical NIFTY futures.
# This is explicit and switchable; it does not claim futures equal spot.
HFT_UNDERLYING_MODE = "NIFTY_FUTURES"
GAP_THRESHOLD_POINTS = 50.0
CURRENT_WEEKLY_ONLY = True
REQUIRE_FIRST_CANDLE_OPEN_EQUALS_LOW = True
ENTRY_ON_NEXT_CANDLE_HIGH_BREAK = True

ENTRY_LIMIT_OFFSET_POINTS = 2.0
EXIT_LIMIT_OFFSET_POINTS = 2.0

INITIAL_SL_MAX_POINTS = 20.0

TARGET_R_MULTIPLES = (2.0, 3.0, 4.0)
TARGET_SYSTEM_ENABLED_DEFAULT = True
MANUAL_TRAILING_ENABLED_DEFAULT = True

# Example: entry 100 -> current 125 -> +25 profit.
# 10-point buffer protects +15 points.
TRAIL_BUFFER_POINTS = 10.0
TRAIL_MIN_LOCK_POINTS = 15.0

CAPITAL_PER_LOT = 10_000.0
DEFAULT_LOTS = 4

# Historical contract lot size must come from instrument metadata.
USE_INSTRUMENT_LOT_SIZE = True
