# TSL comparison ("shadow lab") — status 2026-10-25

Superseded by the trade-management rewrite. See `docs/TSL_AND_TRADE_MANAGEMENT.md`.

* All methods now come from `paper_trading/tsl_methods.py` with configurable numbers.
* Chandelier follows everget's Pine script (highest CLOSE of the last `length` candles, ratchet
  rule `close[1] > longStopPrev`), not the earlier lifetime/rolling-high variant.
* The comparison uses the SAME rules as the live trail (`TslTracker`): the trade's chart (option or
  spot), TSL timeframe and trigger; stop known at a close protects only later candles.
* State of the live trail is saved in `trade_management_state.json` and survives a restart.
* P&L is gross (no costs); spot-chart exits are valued at the option's latest 1-minute close.
