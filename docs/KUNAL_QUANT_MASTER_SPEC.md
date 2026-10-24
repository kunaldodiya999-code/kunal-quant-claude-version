# KUNAL QUANT — MASTER PROJECT SPECIFICATION
## KTMI Uni Lite Strategy, HFT Execution Engine, Risk Management, Paper Trading, FYERS Integration & Trading Terminal

Claude, you are working with me on **Kunal Quant**, a modular algorithmic trading research and execution platform. I want you to understand the complete vision, existing architecture, strategy requirements, execution rules, user-interface requirements, and future expansion plan before making changes to the codebase.

Do not treat this as a request to build a standalone indicator. We are building an integrated quantitative trading terminal with a configurable strategy engine, precise order execution, automatic risk management, paper trading, historical backtesting, and a complete trade journal.

Your responsibility is to help me develop this project incrementally, preserve working components, validate all changes, and build a reliable system that can be tested before real capital is exposed.

---

# 1. PROJECT OBJECTIVE

Build Kunal Quant as a customizable, data-driven algorithmic trading platform that initially trades:

1. NIFTY 50
2. BANK NIFTY
3. SENSEX

The initial strategy is based on **KTMI Uni Lite**, my custom TradingView Pine Script indicator, running on the 1-minute, 3-minute, and 5-minute timeframes.

The strategy will use configurable entry conditions, stop-loss, target, trailing stop-loss, risk-to-reward, capital allocation, quantity calculation, order execution, and trade management.

The system must be capable of:

- Detecting valid long and short entry signals.
- Capturing signals without silently dropping them because of time filters or data-quality warnings.
- Determining whether each signal is eligible for a trade.
- Calculating the correct quantity based on allocated capital and risk limits.
- Placing simulated orders in paper-trading mode.
- Managing stop-loss, targets, and trailing stop-loss automatically.
- Plotting the entry, stop-loss, target, and risk-to-reward box on the chart.
- Recording every signal, order, fill, modification, exit, and P&L event.
- Showing real-time positions and order status in an order-management side panel.
- Supporting historical backtesting and performance analysis.
- Using FYERS APIs for market data and, when explicitly enabled and validated, broker order execution.
- Allowing future instruments and strategies to be added without rewriting the entire application.

The platform must not depend on hard-coded instrument names, capital amounts, entry thresholds, stop-loss values, target values, or timeframes.

**Almost every operational and strategy parameter must be configurable from the application interface.**

# 2. PROJECT STATUS AND REPOSITORY DISCIPLINE

The project already contains code, database models, tests, broker integration work, market-data utilities, strategy components, and existing trading workflows.

The repository is named `KunalQuant`.

Before implementing anything:

1. Inspect the current Git branch, working tree, and recent commits.
2. Read the project architecture and existing documentation.
3. Inspect the current strategy engine, paper-trading engine, database schema, FYERS client, historical downloader, market-data components, charting implementation, and existing tests.
4. Locate the official KTMI Uni Lite source and all existing strategy integrations.
5. Identify the actual order lifecycle and current persistence implementation.
6. Determine which components already work and which are incomplete.
7. Report the current state before proposing changes.

Do not assume that a component is missing simply because it has not been mentioned in this prompt.

Do not create a parallel paper-trading engine, duplicate database models, or a second broker client if the repository already contains suitable implementations.

Do not rewrite working components unnecessarily.

Do not modify locked indicator source code to make integration easier. If an adapter is required, implement it separately.

Do not overwrite uncommitted user changes, reset branches, force-push, or make destructive database changes.

Preserve existing functionality and run relevant regression tests after each implementation stage.

# 3. KTMI UNI LITE — OFFICIAL STRATEGY INDICATOR

KTMI Uni Lite is my custom indicator and must remain the source of truth for its indicator calculations.

Its finalized characteristics include:

- EMA smoothing only.
- TRIX calculation method only.
- Configurable input source.
- Momentum, long-momentum, and short-momentum calculations.
- Configurable speed and signal parameters.
- Signal triggers and arrows.
- Adjustable overbought and oversold levels, with defaults of +3 and -3 in the locked Uni Lite version.
- Visible level lines and corresponding fill behavior.
- No confluence background.
- No confluence table.

The current locked defaults include speed 5 and signal 9, with EMA smoothing. Preserve the existing source, calculation order, initialization behavior, and signal semantics.

There are three official KTMI versions:

1. Original/base KTMI V6.
2. KTMI Universal V1 FINAL.
3. KTMI Uni Lite FINAL.

Do not merge experimental indicators or unrelated gamma/GEX experiments into the official indicator.

## Strategy timeframes

The strategy must support:

- 1-minute candles.
- 3-minute candles.
- 5-minute candles.

The timeframe must be selectable from the interface. Users must be able to enable or disable individual timeframes independently.

The platform must support testing each timeframe independently before running multiple timeframes together.

## Entry-trigger configuration

The currently established entry trigger from our previous replay work is:

**Long entry candidate**

- The selected long-speed series crosses above the configurable trigger level.
- Default trigger level: +0.5.
- Long speed is greater than its signal line.
- Long speed is greater than zero.

**Short entry candidate**

- The selected short-speed series crosses above the configurable trigger level.
- Default trigger level: +0.5.
- Short speed is greater than its signal line.
- Short speed is greater than zero.

These are the established baseline conditions from our signal-capture work. Verify their implementation against the official indicator and the current project code before integrating them into the strategy engine.

Do not assume that every other potential HFT filter has already been finalized.

The entry system should allow configuration of:

- Long trigger level.
- Short trigger level.
- Long speed versus signal requirement.
- Short speed versus signal requirement.
- Positive/negative momentum requirements.
- Cross-above versus cross-below behavior, where supported.
- Selected KTMI series.
- Signal confirmation requirements.
- Candle-close confirmation versus intrabar signal detection, where supported by the data feed.
- Timeframe selection.
- Trading-session window.
- Entry cutoff time.
- Maximum concurrent positions.
- Cooldown after an exit.
- Re-entry rules.
- Duplicate-signal prevention.
- Optional filters such as volume, VWAP, volatility, trend, or other indicators, provided they can be enabled or disabled independently.

Optional filters must not silently become mandatory. Each must have an explicit configuration setting.

Do not change the baseline entry rules without reporting the reason and obtaining my approval.

## Signal capture and eligibility

Keep signal detection separate from trade eligibility.

Record all detected signals during the configured observation window, even when:

- The signal occurs after the preferred entry cutoff.
- A trading-session restriction prevents an entry.
- A data-quality warning is present.
- Capital is insufficient.
- A position limit has been reached.
- An order is rejected or cannot be executed.

Store the signal and its metadata, then record the reason why a trade was or was not allowed.

This distinction is essential for debugging and statistical analysis.

# 4. HFT STRATEGY — FAST AND PRECISE EXECUTION

Our HFT strategy aims to act quickly when a valid KTMI trigger occurs, manage risk immediately, and minimize avoidable entry and exit delays.

For this project, implement the execution behavior as a configurable, low-latency intraday trading strategy. Do not describe it as exchange-colocated or guaranteed ultra-low-latency HFT unless the infrastructure actually supports that.

The system should minimize unnecessary computation and execution delay while preserving correct risk controls.

## Required execution sequence

The intended sequence is:

1. Receive market data through the appropriate FYERS feed.
2. Normalize and timestamp the market data.
3. Update the selected timeframe's candle state.
4. Calculate or retrieve the KTMI values using logic consistent with the official indicator.
5. Detect a new qualifying entry signal.
6. Confirm that the signal is not a duplicate.
7. Evaluate eligibility, market status, risk limits, and available capital.
8. Calculate quantity.
9. Calculate entry reference price, initial stop-loss, target, and risk-to-reward.
10. Create the trade and order records.
11. Submit the entry order through the selected execution mode.
12. Confirm the order status and actual fill.
13. Recalculate the position's actual risk and reward from the confirmed fill price.
14. Activate stop-loss, target, and trailing-stop management.
15. Monitor the position and order status continuously.
16. Trigger the appropriate exit workflow.
17. Confirm the exit fill and finalize P&L.
18. Persist the entire lifecycle and update the chart, order panel, and dashboard.

Use asynchronous or event-driven processing where appropriate. Avoid unnecessary polling, blocking API calls, repeated full-history calculations, and duplicate order submissions.

A signal is not a fill. An order submission is not a fill. The platform must distinguish all three states.

# 5. STOP-LOSS ENGINE

The stop-loss engine must be independent of the entry-signal engine.

It must support long and short trades, with separately configurable parameters.

The user must be able to select a stop-loss method from the interface.

Potential supported methods include:

- Fixed points.
- Percentage of entry price.
- Previous swing low/high.
- ATR-based distance.
- Risk-based stop distance.
- A custom strategy-provided stop price.

These are requested design options, not claims that every method is already implemented.

## Long-position stop-loss

The stop-loss is below the actual entry price, according to the selected method.

For a swing-based method, a long position can use a configurable recent swing low, subject to valid market structure and tick-size constraints.

## Short-position stop-loss

The stop-loss is above the actual entry price, according to the selected method.

For a swing-based method, a short position can use a configurable recent swing high.

## Stop-loss parameters

Make the following configurable where applicable:

- Stop-loss method.
- Stop-loss points or percentage.
- ATR period and multiplier.
- Swing lookback period.
- Swing confirmation rules.
- Minimum stop distance.
- Maximum stop distance.
- Tick-size rounding.
- Maximum rupee risk per trade.
- Maximum percentage of allocated capital at risk.
- Whether the stop is fixed after entry or can trail.
- Stop-loss order type and broker protection mechanism.
- Handling of invalid or missing stop prices.

Never permit a stop price that violates the instrument's price constraints or is on the wrong side of the position.

If a valid initial stop-loss cannot be calculated, reject the trade before entry unless an explicitly approved alternative protection procedure exists.

# 6. TARGET ENGINE

Targets must be configurable independently for long and short trades.

Support the following methods where implemented:

- Fixed points.
- Percentage target.
- Risk-to-reward target.
- ATR-based target.
- Custom target price.

The most important requirement is that the target can be derived from the actual filled entry price and initial stop distance.

For example, for a long position:

- Entry = 100.
- Initial stop-loss = 95.
- Initial risk distance = 5.
- Risk-to-reward = 1:2.
- Target = 110.

For a short position:

- Entry = 100.
- Initial stop-loss = 105.
- Initial risk distance = 5.
- Risk-to-reward = 1:2.
- Target = 90.

These are illustrative values, not live-market prices.

Allow the user to change the reward multiple, with an editable default such as 1:2. Do not assume that 1:2 must be the final setting.

The interface should support target selection independently of stop-loss selection, with validation for incompatible settings.

Display the planned reward, planned risk, and risk-to-reward ratio before the trade is submitted.

# 7. TRAILING STOP-LOSS — TSL ENGINE

Trailing stop-loss must be a dedicated position-management module, not an unstructured collection of exit conditions.

It must support independently configurable trailing behavior for long and short trades.

Potential trailing methods:

- Fixed-point trailing.
- Percentage trailing.
- ATR-based trailing.
- Swing-high/swing-low trailing.
- Breakeven followed by trailing.
- Risk-multiple-based trailing.
- Custom trailing logic.

## Required configurable TSL settings

Provide settings for:

- Enable/disable TSL.
- TSL activation condition.
- Activation in points, percentage, or R-multiple.
- Initial trailing distance.
- Trailing step.
- Minimum adjustment increment.
- ATR parameters, if selected.
- Swing lookback, if selected.
- Breakeven activation threshold.
- Breakeven offset to cover configured costs, if desired.
- Whether trailing starts immediately or only after a profit threshold.
- Whether the target remains active after TSL activation.
- Whether the target can be moved or extended.
- Maximum permitted risk exposure.
- Handling of gaps and missed prices.

## TSL invariants

For a long position, the protective stop must never move downward.

For a short position, the protective stop must never move upward.

The TSL engine must not widen risk simply because the market moves against the position.

Record every stop modification with its timestamp, old stop, new stop, reason, order ID, and broker acknowledgement where applicable.

If the broker supports a native protective order, evaluate whether it is safer and more reliable than local-only monitoring. Document the actual capabilities and limitations of the selected FYERS API and instrument.

Do not claim that a local stop is guaranteed to execute if the application, internet connection, or broker feed fails.

# 8. EXIT STRATEGY — LIMIT ORDERS WITH A PRICE BUFFER

This is a critical requirement.

**We do not intentionally exit positions using market orders. Our exit workflow must use limit orders with a configurable, market-aware price buffer designed to improve the likelihood of immediate execution.**

The system must not substitute a market order when an exit limit order is rejected, times out, or remains unfilled.

## Long-position exit

A long position is closed by selling.

The exit engine should use the current executable bid as its reference price, when reliable bid/ask data is available.

A configurable sell-side buffer is then applied to derive the limit price.

Conceptually:

Sell limit price = current bid − sell buffer.

This makes the limit price more aggressive than the bid and can improve execution probability, subject to exchange rules, tick size, liquidity, and price-band restrictions.

## Short-position exit

A short position is closed by buying.

The exit engine should use the current executable ask as its reference price, when reliable bid/ask data is available.

A configurable buy-side buffer is then applied.

Conceptually:

Buy limit price = current ask + buy buffer.

This makes the limit price more aggressive than the ask and can improve execution probability.

The exact formula, direction, and rounding must be validated against the broker's order conventions and the actual instrument.

## Exit-buffer configuration

Allow the user to choose the buffer method:

- Fixed price points.
- Number of ticks.
- Percentage of the reference price.
- Optional spread-aware buffer.

Allow independent buffer values for long exits and short exits.

Provide a configurable execution policy for:

- Initial exit-limit price.
- Order acknowledgement timeout.
- Maximum repricing attempts.
- Repricing interval.
- Maximum permitted price deviation.
- Maximum exit slippage.
- Handling of partial fills.
- Handling of rejected orders.
- Cancellation and replacement of stale orders.
- Handling of stale quotes or missing bid/ask prices.
- Handling of exchange price bands and tick-size rules.

The execution engine must avoid submitting duplicate exit orders or unintentionally exceeding the remaining position quantity.

When repricing an exit order, cancel or reconcile the previous order before submitting a replacement, in accordance with the broker's actual order lifecycle.

Every attempt must be recorded.

### Stop-loss execution

A stop-loss trigger and its actual execution are separate events.

When the stop-loss is triggered, initiate the configured limit-based exit process with the required price buffer. If the limit order is not filled, the position remains exposed.

The system must continue monitoring and applying the configured retry policy while recording the unfilled quantity, elapsed time, current exposure, and execution status.

**Never silently fall back to a market order.** If the configured limit-exit policy cannot close the position, raise a prominent execution-risk alert and follow the explicitly configured escalation procedure. Do not pretend the trade is closed until the fills confirm it.

The same execution discipline applies to target exits and discretionary exits.

# 9. AUTOMATIC POSITION SIZING AND CAPITAL ALLOCATION

Quantity must be calculated automatically. The user should not need to manually calculate quantity before every trade.

The order panel must allow the user to define:

- Total virtual or allocated trading capital.
- Capital allocated to the strategy.
- Capital allocated to each instrument.
- Capital allocated to each timeframe.
- Maximum capital per trade.
- Maximum risk per trade.
- Maximum daily loss.
- Maximum number of open positions.
- Maximum concurrent trades per instrument.
- Maximum total open exposure.
- Margin buffer.
- Whether quantity is determined by capital allocation, risk, or a stricter combination of both.

## Risk-based sizing

For a simple linear instrument:

Risk-based quantity = floor(allowed rupee risk / per-unit stop-loss risk).

For example:

- Allowed risk = ₹1,000.
- Entry price = 100.
- Stop-loss price = 95.
- Per-unit risk = ₹5.
- Risk-based quantity = 200 units before other constraints.

For derivatives, include the applicable lot size, contract multiplier, premium, margin requirements, and other instrument-specific constraints.

For options buying, account for the option premium and lot size. The system must not treat an index spot price as the option's purchase price.

## Combined sizing constraints

The final quantity must respect all applicable limits:

- Risk-based maximum quantity.
- Capital-allocation maximum quantity.
- Broker and instrument quantity constraints.
- Lot-size multiples.
- Available funds or paper-trading buying power.
- Margin requirements.
- Maximum exposure limits.
- Maximum daily-loss and portfolio-risk limits.

Use the most restrictive valid quantity.

For derivatives, round quantity to valid lot-size increments. Never round upward in a way that breaches the risk or capital limit.

Recalculate risk after the actual fill price is known.

If the resulting quantity is zero, reject the trade with a clear reason.

# 10. LONG AND SHORT RISK-TO-REWARD CHART BOX

This is a core user-interface requirement.

When a trade is opened, plot a risk/reward box directly on the chart for both long and short directions.

The box must be linked to the actual trade, not merely drawn as a decorative shape.

It should show:

- Entry price.
- Stop-loss price.
- Target price.
- Risk zone.
- Reward zone.
- Planned risk/reward ratio.
- Position direction.
- Quantity.
- Actual average entry price.
- Current price.
- Unrealized P&L.
- Current stop-loss and trailing-stop level.
- Exit status.

For a long trade, the reward zone appears above entry and the risk zone below entry.

For a short trade, the reward zone appears below entry and the risk zone above entry.

The box should be created when the entry is confirmed, updated when permitted stop/target changes occur, and finalized when the trade closes.

Support:

- Adjustable visual styling.
- Show/hide controls.
- Extend box until exit.
- Display numeric price labels.
- Display risk in rupees and points.
- Display reward in rupees and points.
- Display realized and unrealized P&L.
- Display order execution status.
- Link the drawing to its trade ID.
- Preserve historical completed trade boxes where desired.

The visualization must distinguish planned levels from actual fills and actual protective orders.

# 11. PAPER-TRADING ENGINE — COMPLETE TRADE LIFECYCLE

Paper trading is not just a signal logger. It must simulate and persist the full trade lifecycle.

Implement or extend the existing paper-trading engine rather than creating a duplicate.

The paper-trading engine must support the same strategy, sizing, risk, target, TSL, and exit-limit rules as the eventual live-trading engine wherever simulation can faithfully model them.

## Record every detected signal

Capture:

- Unique signal ID.
- Instrument.
- Strategy ID and version.
- Timeframe.
- Signal timestamp.
- Candle timestamp and candle state.
- Direction.
- Indicator source and parameter snapshot.
- Speed value.
- Signal-line value.
- Trigger level.
- Entry eligibility.
- Rejection reason.
- Data-quality warnings.
- Market-data source.

Do not delete a signal because it was not eligible for a trade.

## Record every trade

Capture:

- Unique trade ID.
- Signal ID.
- Instrument and contract identifier.
- Strategy and timeframe.
- Direction.
- Signal time.
- Order-submission time.
- Order acknowledgement time.
- Entry-fill time.
- Entry reference price.
- Actual average entry price.
- Quantity.
- Initial stop-loss.
- Initial target.
- Initial risk distance.
- Initial risk amount.
- Planned reward.
- Planned risk-to-reward ratio.
- Capital allocation.
- Entry fees and estimated costs.
- Strategy configuration snapshot.

## Record every order event

For each order, record:

- Unique order ID.
- Trade ID.
- Broker order ID, if applicable.
- Order type.
- Buy/sell side.
- Quantity.
- Limit price.
- Trigger price, if applicable.
- Submission timestamp.
- Acknowledgement timestamp.
- Status changes.
- Partial fills.
- Filled quantity.
- Remaining quantity.
- Average fill price.
- Rejections and error codes.
- Cancellation attempts.
- Repricing attempts.
- Order modifications.
- Retry reason.
- Final status.

## Record position-management events

Record:

- Initial stop placement.
- Every stop-loss modification.
- TSL activation.
- Breakeven activation.
- Target modification.
- Target trigger.
- Stop trigger.
- Exit-limit submission.
- Exit-limit repricing.
- Partial exit.
- Final exit.
- Manual intervention.
- Emergency or unresolved execution alert.

## Record complete P&L

Calculate and store:

- Gross realized P&L.
- Gross unrealized P&L.
- Brokerage.
- Exchange transaction charges.
- Applicable taxes and fees.
- Slippage.
- Net realized P&L.
- Net unrealized P&L.
- Maximum favorable excursion.
- Maximum adverse excursion.
- Holding duration.
- Initial planned risk.
- Actual risk at fill.
- R-multiple result.
- Exit reason.

Do not report a limit order's quoted price as its fill price. In paper mode, simulated fills must be based on an explicit fill model and available market data.

## Paper-trading integrity

The engine must:

- Prevent duplicate entries from the same signal.
- Prevent duplicate exits.
- Handle restarts without losing open positions.
- Reconcile open orders and positions on restart.
- Maintain transactional consistency.
- Use stable unique identifiers.
- Support audit trails.
- Preserve closed trades and configuration snapshots.
- Clearly label simulated fills versus real broker fills.
- Make database writes safe and testable.
- Avoid accidental writes to unrelated historical-data tables.

Paper trading must be the first end-to-end validation environment.

# 12. STRATEGY CONFIGURATION AND ORDER SIDE PANEL

I want a side panel or order-management panel where I can change settings without modifying Python files or Pine Script.

It must be a practical control panel, not a collection of hard-coded constants.

## Instrument settings

- Instrument selection.
- Enabled/disabled instruments.
- Exchange and segment.
- Instrument type.
- Contract/expiry selection where applicable.
- Lot size and tick size from validated instrument metadata.

## Strategy settings

- Strategy selection.
- KTMI entry trigger values.
- Long/short enablement.
- 1-minute, 3-minute, and 5-minute timeframe toggles.
- Entry confirmation mode.
- Optional filters.
- Trading-session window.
- Entry cutoff.
- Re-entry rules.
- Maximum concurrent positions.

## Risk settings

- Total allocated capital.
- Capital per instrument.
- Capital per strategy.
- Risk per trade in rupees.
- Risk per trade as a percentage.
- Stop-loss method and value.
- Target method and value.
- Risk-to-reward multiple.
- TSL enablement and parameters.
- Maximum daily loss.
- Maximum number of trades.
- Maximum drawdown guard.
- Maximum exposure.

## Execution settings

- Paper/live mode.
- Entry order type.
- Exit order type.
- Long and short exit buffers.
- Buffer units.
- Order acknowledgement timeout.
- Repricing policy.
- Maximum repricing attempts.
- Maximum price deviation.
- Partial-fill handling.
- Stale-market-data guard.
- Broker connection status.

## Configuration management

Allow configurations to be saved, loaded, duplicated, and versioned.

Support named profiles, such as:

- NIFTY KTMI 1m.
- NIFTY KTMI 3m.
- NIFTY KTMI 5m.
- BANK NIFTY KTMI.
- SENSEX KTMI.
- HFT paper profile.

These are example profile names, not hard-coded strategies.

Each trade must retain the exact parameter snapshot used when it was opened, so that changing the settings later does not rewrite the history of previous trades.

Validate every configuration before enabling the strategy.

Show warnings for incompatible settings and invalid values.

# 13. FYERS API INTEGRATION

FYERS is the broker/data integration we are using for the current project.

Inspect the existing `FyersClient` and related market-data and historical-data modules before implementing new API functionality.

Use the official FYERS APIs and current supported SDK/API behavior. Do not invent endpoint names, response formats, order capabilities, or rate limits.

## Market-data integration

Use the appropriate FYERS market-data capabilities for:

- NIFTY 50 index prices.
- BANK NIFTY index prices.
- SENSEX index prices, subject to actual symbol and segment support.
- Relevant instrument quotes.
- Bid/ask data where available.
- Volume and other supported fields.
- WebSocket market-data streaming.
- Historical OHLCV data.
- Option-chain or derivative contract information where supported.
- Order-book and position updates where supported.

Normalize incoming market data into a consistent internal schema.

Track:

- Source timestamp.
- Local receive timestamp.
- Quote freshness.
- Missing data.
- Duplicate messages.
- Reconnection events.
- Feed health.
- Candle completeness.

Never use stale prices for a new entry without an explicit policy allowing it.

## Authentication

Use the existing authentication mechanism where possible.

Protect access tokens and credentials through environment variables or an appropriate secrets-management mechanism.

Never log access tokens, app secrets, or other credentials.

Handle token expiry, authentication failure, reconnection, and session renewal according to the broker's actual requirements.

## Historical data

Use FYERS historical-data APIs where available for backtesting and replay.

Respect the API's supported history range, interval limits, symbol formats, and expired-contract availability.

Do not assume that live quotes can reconstruct historical intraday option-chain snapshots.

Clearly separate historical candle data, live quote data, and reconstructed/simulated data.

## Order execution

Use FYERS order APIs only after validating the exact API capabilities for the selected product and instrument.

Implement:

- Order placement.
- Order-status reconciliation.
- Modification and cancellation where supported.
- Partial-fill handling.
- Rejection handling.
- Position reconciliation.
- Broker order IDs.
- Idempotency and duplicate-submission protection.
- Retry policies that cannot create unintended duplicate positions.
- Broker rate-limit handling.

Do not assume that a stop-loss order, bracket order, trailing stop, or particular limit-order behavior is supported for every instrument. Confirm support and document the limitations.

Use a broker adapter so that future brokers can be added without rewriting the strategy engine.

**Paper trading must never submit real orders.** Live trading must require an explicit user-controlled enablement step and appropriate safeguards.

# 14. INITIAL INSTRUMENT SUPPORT AND FUTURE EXPANSION

## Phase 1 — Initial instruments

Focus on:

- NIFTY 50.
- BANK NIFTY.
- SENSEX.

The strategy should work with the underlying index's signal data and the actual tradable instrument selected for execution.

Do not confuse an index value with an executable asset.

For example, if the strategy generates a signal from an index, the order-routing layer must know whether the selected execution instrument is an index derivative, option, or another supported tradable instrument.

The instrument-selection rules must be configurable and must respect contract specifications.

## Phase 2 — Options and futures

Expand to the relevant F&O universe after the initial three-index implementation has passed validation.

Support instrument metadata, expiry dates, strikes, option types, lot sizes, tick sizes, and contract-specific risk rules.

Do not assume every contract is available through every API endpoint.

## Phase 3 — Commodities and additional assets

Later, I intend to include:

- Gold.
- Crude oil.
- Other eligible commodities.
- Additional futures and options instruments.
- Other supported asset classes.

The architecture must allow these instruments to be registered through configuration and validated metadata, rather than requiring a rewrite of the strategy engine.

Instrument-specific trading sessions, lot sizes, price ticks, order rules, and risk constraints must be respected.

# 15. BACKTESTING, REPLAY, AND PERFORMANCE ANALYTICS

The platform must support three principal operating modes:

1. Historical backtesting.
2. Paper trading.
3. Live trading, after explicit enablement.

Use the same core strategy and risk-management logic across modes wherever technically appropriate.

Separate data-source differences and execution simulation from the actual strategy rules.

Backtesting must account for:

- Candle timestamps and alignment.
- Indicator initialization.
- Signal timing.
- Look-ahead bias.
- Duplicate signals.
- Bid/ask spreads where data is available.
- Fees and taxes.
- Slippage.
- Limit-order fill assumptions.
- Unfilled and partially filled orders.
- Intrabar stop/target ambiguity.
- Missing candles.
- Session boundaries.
- Position sizing.
- Capital constraints.

Do not assume a limit order was filled just because the candle touched the limit price. Use an explicit, documented fill model.

Provide performance reports including:

- Total trades.
- Win rate.
- Gross and net P&L.
- Average win and loss.
- Profit factor.
- Maximum drawdown.
- Expectancy.
- Average R-multiple.
- Largest winning and losing trades.
- Average holding duration.
- Trade frequency.
- Results by instrument.
- Results by timeframe.
- Results by long and short direction.
- Results by exit reason.
- Slippage and transaction costs.
- Missed or rejected trades.
- Execution latency statistics.

The system must not claim profitability or guaranteed execution. The objective is to measure, validate, and improve the strategy using realistic assumptions.

# 16. DASHBOARD AND USER EXPERIENCE

Build a clean trading-terminal interface inspired by professional charting and order-management applications.

The main workspace should include:

### Chart area

- Candlestick chart.
- Timeframe selection.
- Instrument selection.
- KTMI Uni Lite visualization or a clearly validated equivalent.
- Long/short entry markers.
- Entry, stop-loss, target, and TSL lines.
- Risk/reward box.
- Volume and other enabled indicators.
- Historical trades and signal overlays.
- Data-quality warnings.

### Order-management panel

- Current instrument.
- Strategy and timeframe.
- Paper/live mode.
- Allocated capital.
- Calculated quantity.
- Entry trigger.
- Stop-loss.
- Target.
- TSL parameters.
- Exit buffer.
- Order status.
- Open position quantity.
- Average fill price.
- Unrealized P&L.
- Realized P&L.
- Manual close/management controls subject to the configured limit-order execution policy.

### Positions and orders

Display all open positions, pending orders, partial fills, completed orders, rejected orders, and unresolved exits.

### Trade journal

Provide filters by date, instrument, timeframe, strategy, direction, outcome, and exit reason.

Allow the user to inspect the full event timeline of any trade.

### System health

Show:

- FYERS connection status.
- Last market-data timestamp.
- Quote freshness.
- Feed reconnection state.
- Strategy state.
- Paper/live mode.
- Pending orders.
- Risk-limit status.
- Unresolved order or position discrepancies.

The interface must make it obvious whether the application is in paper mode or live mode.

# 17. RISK CONTROLS AND FAILURE HANDLING

Implement independent safety checks at the strategy, portfolio, and execution levels.

Required protections include:

- Maximum daily loss.
- Maximum risk per trade.
- Maximum open exposure.
- Maximum simultaneous positions.
- Duplicate-entry protection.
- Stale-data protection.
- Invalid-price protection.
- Broker-disconnection handling.
- Order rejection handling.
- Partial-fill reconciliation.
- Duplicate-exit prevention.
- Restart recovery.
- Position reconciliation.
- Daily trading cutoff.
- Configurable emergency trading disablement.

A daily-loss limit must prevent new trades according to its configured policy.

A risk limit must not automatically erase or abandon an existing position.

Open positions and outstanding exit orders require continued management and explicit reconciliation.

If the connection fails, the system must distinguish between:

- No open position.
- Open position with broker-side protection.
- Open position managed only by the application.
- Unknown position state.
- Pending or unresolved exit.

Never mark an order as completed without evidence from the simulated execution engine or broker confirmation.

# 18. DATA MODEL AND AUDITABILITY

Review the current database before proposing schema changes.

Reuse existing tables and persistence patterns where appropriate.

The design must support, directly or through suitable related records:

- Instruments.
- Strategies.
- Strategy configurations and versions.
- Signals.
- Trades.
- Orders.
- Order events.
- Fills.
- Position snapshots.
- Stop-loss and target modifications.
- TSL events.
- Execution attempts.
- P&L records.
- Market-data quality events.
- System health events.

Use consistent timestamps, unique IDs, and transaction-safe state changes.

Preserve historical audit records.

Do not place credentials or access tokens in the database, logs, or exported reports.

Keep research outputs and diagnostic datasets separate from the production trading database when possible.

# 19. TESTING REQUIREMENTS

Before declaring any component complete, write or update tests.

Test at least:

1. Long and short entry conditions.
2. Cross-above trigger behavior.
3. Duplicate signal handling.
4. Timeframe selection.
5. Signal capture versus entry eligibility.
6. Long and short stop-loss calculations.
7. Long and short target calculations.
8. Risk-to-reward calculations.
9. Quantity calculation and lot-size rounding.
10. Capital and risk-limit enforcement.
11. TSL activation and monotonic stop behavior.
12. Exit-limit price calculations and tick rounding.
13. Exit repricing and retry handling.
14. Partial fills.
15. Order rejection.
16. Unfilled exits.
17. Restart recovery.
18. Paper-trading P&L and transaction costs.
19. Historical replay and candle alignment.
20. FYERS authentication and feed failures.
21. Instrument-specific constraints.
22. Regression of existing project features.

Use mocked broker responses for deterministic tests and safe API smoke tests where needed.

Never use a real order to test the paper-trading engine.

Run the existing regression suite after meaningful changes. Report the exact commands and test results.

# 20. DEVELOPMENT PLAN

Work in controlled phases.

## Phase A — Audit and architecture

- Inspect the repository.
- Identify working and incomplete components.
- Trace the KTMI signal path into the strategy engine.
- Trace the paper-trading lifecycle.
- Trace FYERS market-data and order interfaces.
- Identify existing UI and charting components.
- Document the current architecture and missing pieces.

Deliver an implementation plan before making broad changes.

## Phase B — KTMI strategy integration

- Integrate the locked KTMI Uni Lite entry logic through an appropriate adapter.
- Support 1m, 3m, and 5m.
- Add configurable long and short trigger parameters.
- Separate signal detection from eligibility.
- Add deterministic replay tests.
- Validate calculations and signal timing against the official indicator.

Do not modify the locked Pine Script to compensate for a faulty adapter.

## Phase C — Risk and position sizing

- Implement configurable stop-loss methods.
- Implement target methods and R-multiple calculations.
- Implement TSL.
- Implement automatic quantity sizing.
- Implement risk limits.
- Add tests for long and short positions.

## Phase D — Paper-trading lifecycle

- Integrate the strategy with the existing paper engine.
- Persist signals, trades, orders, fills, modifications, and exits.
- Implement realistic limit-order simulation.
- Implement recovery and duplicate protection.
- Validate complete trade lifecycles.

## Phase E — Exit execution engine

- Implement configurable limit-order buffers.
- Add retry, cancellation, and replacement policies.
- Handle partial fills and rejected orders.
- Integrate broker status reconciliation.
- Add execution-risk alerts.
- Verify the no-market-order-fallback rule.

## Phase F — Chart and order panel

- Plot long and short risk/reward boxes.
- Display entry, stop, target, and TSL.
- Implement the configuration side panel.
- Show orders, positions, and P&L.
- Persist named strategy profiles.

## Phase G — FYERS integration validation

- Validate current authentication.
- Validate required market-data fields.
- Validate WebSocket behavior.
- Validate supported instrument symbols.
- Validate order APIs and supported order types.
- Test disconnections, rejected orders, and reconciliation.

## Phase H — Initial instrument rollout

Start with NIFTY 50, BANK NIFTY, and SENSEX.

Validate each instrument and each timeframe independently.

Run historical replay, then paper trading, before enabling live trading.

## Phase I — Expansion

After the initial system is stable, extend instrument metadata and execution support to the broader F&O universe and later to gold, crude oil, and additional commodities.

# 21. IMPORTANT IMPLEMENTATION RULES

Follow these rules throughout development:

1. Do not hard-code settings that should be user-configurable.
2. Do not change the locked KTMI Uni Lite formula without explicit approval.
3. Do not silently change entry or exit rules.
4. Do not create duplicate strategy or paper-trading engines.
5. Do not write to production tables during a read-only diagnostic.
6. Do not run database migrations without reviewing their effects.
7. Do not place real orders during development or testing.
8. Do not silently fall back to market exits.
9. Do not assume an order was filled.
10. Do not discard signals that failed eligibility checks.
11. Do not hide data-quality warnings.
12. Do not invent unsupported FYERS API capabilities.
13. Do not claim that an unimplemented feature works.
14. Do not claim an HFT performance level that has not been measured.
15. Do not report a task as complete without test evidence.
16. Preserve uncommitted changes and avoid destructive Git operations.
17. Keep implementation changes focused and reviewable.
18. Prefer reusable, instrument-independent modules.
19. Keep strategy logic separate from broker-specific logic.
20. Keep chart visualization separate from execution decisions.

When a requirement is unclear, inspect the existing code and available documentation first. If it remains unresolved, identify the exact uncertainty and propose a configurable design instead of inventing a hidden default.

# 22. REQUIRED RESPONSE FORMAT FOR EACH DEVELOPMENT TASK

For every implementation stage, provide:

**A. Current state**
- What already exists.
- What works.
- What is missing.
- Relevant files and modules.

**B. Proposed changes**
- Files to modify or create.
- Why each change is needed.
- How the change fits the existing architecture.

**C. Implementation**
- Focused, maintainable code changes.
- No unrelated refactoring.
- No silent changes to locked behavior.

**D. Validation**
- Exact commands to run.
- Test results.
- Any failures and their causes.
- Any API assumptions that still need verification.

**E. Next step**
- The single most important next action.
- Any user action needed, if applicable.

If you cannot directly access or modify the local repository, state that clearly and provide precise PowerShell commands or patch instructions. Never claim that you changed a local file or ran a local test when you did not.

# 23. FIRST TASK — AUDIT BEFORE CODING

Start by auditing the existing KunalQuant repository.

Do not begin by rewriting the strategy or building a new interface from scratch.

Return:

1. A concise architecture map.
2. The current KTMI Uni Lite integration status.
3. The current paper-trading engine and its persistence model.
4. The existing FYERS market-data, historical-data, and order-execution capabilities.
5. The current charting and order-panel status.
6. The existing risk-management, target, and TSL implementation.
7. The missing requirements from this specification.
8. Any conflicts between existing code and this specification.
9. A prioritized implementation plan with exact file paths.
10. The first smallest, safest implementation step.

Wait for my review of the audit before making broad changes.

Our objective is not merely to produce more code. It is to build a reliable, configurable, testable trading system in which signal generation, risk management, order execution, and trade records remain consistent.

**Kunal Quant must be designed around accurate signals, disciplined risk management, realistic limit-order execution, complete auditability, and extensibility to additional instruments.**