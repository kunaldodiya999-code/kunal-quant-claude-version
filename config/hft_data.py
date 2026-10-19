"""Kunal Quant HFT historical-data configuration.

This module is intentionally isolated from the locked strategy and
normal option-trading configuration. It defines the research data
universe for the future 10-second HFT strategy.
"""

from __future__ import annotations

HFT_RESOLUTION = "10S"
HFT_FETCH_RESOLUTION = "5S"  # FYERS historical API source; 10S is derived locally.

# Exact user-approved strike ladder, applied identically to CE and PE:
# ATM, ATM+50, ATM+100, ATM+150, ATM+200, ATM+250.
HFT_STRIKE_OFFSETS = (0, 50, 100, 150, 200, 250)

HFT_OPTION_TYPES = ("CE", "PE")

# FYERS does not currently return historical seconds candles for the
# NIFTY spot-index History API route tested by the project. For the HFT
# price path, use the actual historical NIFTY futures contract instead.
# The spot index remains available as reference metadata in the manifest.
HFT_UNDERLYING_MODE = "NIFTY_FUTURES"
HFT_UNDERLYING_SYMBOL = "NSE:NIFTY50-INDEX"

# NIFTY futures are stored as their actual historical contracts. The
# acquisition planner must not manufacture a synthetic future.
HFT_FUTURES_UNDERLYING = "NIFTY"

# The acquisition planner uses the maximum period that the FYERS API
# actually returns for 5-second F&O candles. It must never silently invent
# a retention period.
HFT_MAX_LOOKBACK_DAYS = None

HFT_SOURCE = "FYERS_HFT_HISTORY"

# Research mode only: no existing strategy is enabled by this config.
HFT_STRATEGY_ENABLED_DEFAULT = False
