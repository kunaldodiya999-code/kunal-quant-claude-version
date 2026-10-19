"""Opening Breakout V2 configuration.

Experimental only. This file defines the complete user-facing rule schema for
the configurable opening-breakout strategy. It does not place orders.

All research features are independently switchable. V2 is intentionally kept
separate from the existing V1 implementation and locked production modules.
"""

# ---------------------------------------------------------------------------
# 1. Capital allocation
# ---------------------------------------------------------------------------
CAPITAL_ALLOCATION_PERCENT = 100.0

# ---------------------------------------------------------------------------
# 2. Signal timeframes
# ---------------------------------------------------------------------------
TIMEFRAME_OPTIONS = ("5S", "10S", "20S", "30S", "1M", "3M", "5M")
SELECTED_TIMEFRAMES = ("1M",)

# If more than one timeframe is selected, high/low/VWAP/BB calculations use
# the 1-minute aggregation as the common calculation timeframe.
MULTI_TIMEFRAME_CALCULATION_TIMEFRAME = "1M"

# ---------------------------------------------------------------------------
# 3. Market bias
# ---------------------------------------------------------------------------
MARKET_BIAS = "NEUTRAL"  # UP / DOWN / NEUTRAL

# ---------------------------------------------------------------------------
# 4. Trade instrument
# ---------------------------------------------------------------------------
TRADE_INSTRUMENT = "CALL"  # CALL / PUT / FUTURES / SPOT
SPOT_EXCHANGE = "NSE"

# ---------------------------------------------------------------------------
# 5. Opening-candle filters
# ---------------------------------------------------------------------------
FILTER_OPEN_HIGH = False
FILTER_OPEN_LOW = True
OPEN_EQUAL_TOLERANCE_POINTS = 0.05

# Opening filters are candidate generators:
#   OPEN_LOW  -> bullish/call-side candidate
#   OPEN_HIGH -> bearish/put-side candidate
# If both are enabled, either qualifying side may generate an alert.
# No position is opened by this filter alone.

# ---------------------------------------------------------------------------
# 6. Breakout / confirmation triggers
# ---------------------------------------------------------------------------
BREAKOUT_TRIGGER_OPTIONS = (
    "CANDLE_HIGH",
    "CANDLE_LOW",
    "ABOVE_VWAP",
    "BELOW_VWAP",
    "CLOSE_ABOVE_UPPER_BB",
    "CLOSE_BELOW_LOWER_BB",
    "KTMI",
    "DMI",
)
SELECTED_BREAKOUT_TRIGGERS = ("CANDLE_HIGH",)

# Multiple selected triggers are AND conditions.
# CANDLE_HIGH/CANDLE_LOW/VWAP/BB use the selected calculation timeframe.
# When multiple timeframes are selected, they use 1M as the common calculation
# timeframe as defined above.

# ---------------------------------------------------------------------------
# 7. KTMI / DMI gated parameters
# ---------------------------------------------------------------------------
KTMI_BUY_CALL_BUYING_SPEED = 0.5
KTMI_BUY_PUT_SELLING_SPEED = 0.5
KTMI_BUY_CALL_MOMENTUM_SPEED = 0.5
KTMI_BUY_PUT_MOMENTUM_SPEED = -0.5

DMI_LENGTH = 14
DMI_ADX_SMOOTHING = 14
DMI_BUY_CALL_PLUS_DI = 25.0
DMI_BUY_PUT_MINUS_DI = 25.0
DMI_ADX_THRESHOLD = 25.0

# The UI should disable KTMI fields unless KTMI is selected.
# The UI should disable DMI fields unless DMI is selected.

# ---------------------------------------------------------------------------
# 8. Option strike selector
# ---------------------------------------------------------------------------
STRIKE_SELECTOR_MODE = "LOT_VALUE"  # LOT_VALUE / PRICE_RANGE / ATM_DISTANCE
LOT_VALUE_TARGET = 10000.0
OPTION_PRICE_MIN = 80.0
OPTION_PRICE_MAX = 100.0
ATM_DISTANCE_POINTS = 0.0

# Suggested extension:
#   ATM_DISTANCE selects strikes by distance from ATM (0, 50, 100, ...).
# It is especially useful for index options and avoids mixing contract price
# with strike distance.

# ---------------------------------------------------------------------------
# 9. Stop loss
# ---------------------------------------------------------------------------
SL_MODE = "CUSTOM_POINTS"
CUSTOM_SL_POINTS = 20.0
SL_VALUE_CAP = 10000.0  # whole-position risk cap when SL_MODE == VALUE

# OFF / CUSTOM_POINTS / CANDLE_1_HIGH / CANDLE_1_LOW / VWAP / VALUE

# ---------------------------------------------------------------------------
# 10. Take profit
# ---------------------------------------------------------------------------
TP_MODE = "RR_RATIO"  # OFF / CUSTOM_POINTS / VALUE / RR_RATIO
CUSTOM_TP_POINTS = 20.0
TP_VALUE_TARGET = 10000.0
RR_MULTIPLIER = 2.0

# ---------------------------------------------------------------------------
# 11. Trailing stop
# ---------------------------------------------------------------------------
TRAILING_ENABLED = False
TRAILING_MODE = "POINTS"  # POINTS / RR_STEPS
TRAIL_TRIGGER_POINTS = 40.0
TRAIL_DISTANCE_POINTS = 20.0  # distance added above planned SL
TRAIL_TO_COST = False

# RR trailing steps: when RR reaches trigger, move SL to the configured
# locked RR level. 0.0 means cost; 1.0 means 1R; 2.0 means 2R.
TRAIL_RR_STEPS = (
    (2.0, 0.0),
    (3.0, 1.0),
)

# ---------------------------------------------------------------------------
# 12. Execution and risk
# ---------------------------------------------------------------------------
ENTRY_BUFFER_OPTIONS = (1.0, 1.5, 2.0)
ENTRY_BUFFER_POINTS = 1.0

EXIT_BUFFER_POINTS = 2.0
MAX_SLIPPAGE_POINTS = 2.0

FILL_TIMEOUT_OPTIONS_SECONDS = (5, 10, 20, 30, 60, 180, 300)
ENTRY_FILL_TIMEOUT_SECONDS = 10

ENTRY_CUTOFF_START_HHMM = "09:15"
ENTRY_CUTOFF_END_HHMM = "15:10"
FORCE_EXIT_HHMM = "15:15"

RISK_METHOD = "FIXED_AMOUNT"  # FIXED_AMOUNT / PERCENT_OF_CAPITAL
RISK_PER_TRADE_VALUE = 10000.0
RISK_PER_TRADE_PERCENT = 1.0

# ---------------------------------------------------------------------------
# 13-14. Chart-managed SL/TP overrides
# ---------------------------------------------------------------------------
CHART_TRADE_TOOL_ENABLED = True
ALLOW_MANUAL_SL_OVERRIDE = True
ALLOW_MANUAL_TP_OVERRIDE = True
SHOW_SL_WHEN_FILTER_OFF = True
SHOW_TP_WHEN_FILTER_OFF = True
# If SL/TP filters are OFF, these configurable chart-only seed distances
# populate the draggable SL/TP lines at entry. They are not strategy filters.
CHART_MANUAL_SL_SEED_POINTS = 20.0
CHART_MANUAL_TP_SEED_POINTS = 20.0

# Research-only feature switch. Disabled until independently validated.
OPENING_BREAKOUT_V2_ENABLED_DEFAULT = False
