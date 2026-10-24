# Kunal Quant — Project Handover
**Status date:** 21 October 2026  
**Purpose:** Project vision, architecture, strategy rules, current status, risks and roadmap.

> **Progress estimate:** Approximately 35–40% toward the full intended platform. This is an engineering estimate, not an audited metric, profitability claim, or production-readiness score. Existing code is not necessarily independently validated.

## 1. Vision and end goal

Kunal Quant is intended to become a modular quantitative research and trading workstation focused initially on buying Indian index options. It should connect verified historical/live market data, locked KTMI signals, contract selection, risk sizing, paper execution, trailing-stop research, persistent journals, analytics and a dashboard.

The objective is not to promise a holy grail. The objective is to measure whether strategies have a repeatable statistical edge after realistic transaction costs, spread, slippage, expiry/contract effects and risk controls.

Target capabilities:
- Historical data acquisition, quality checks, replay and backtesting.
- Deterministic KTMI signal calculations on completed candles.
- Verified option-contract selection and buyer-only CE/PE trading.
- Paper execution, initial SL, TSL, target, partial exits if approved, EOD close and durable trade journal.
- Risk limits, duplicate prevention, stale-quote rejection, emergency halt and restart safety.
- TSL comparison lab, performance analytics and an explainable dashboard.
- Independent broker adapters so FYERS and Dhan work can proceed without binding strategy logic to one broker.

## 2. Repository boundaries

- **Protected/original repository:** `KunalQuant`. Do not modify without explicit approval.
- **Development repository:** `kunal-quant-claude-version`.
- **Working branch:** `feature/paper-buyer-engine`.
- **PR #1:** buyer-only paper lifecycle and signal execution coordinator; open/unmerged at report time.
- **UI prototype:** `dashboard/prototype_app.py`.
- **Existing dashboard:** `dashboard/app.py` and its pages remain separate.
- **Locked historical lifecycle:** `backtest/option_trade_lifecycle.py` must remain byte-for-byte unchanged unless explicitly authorized.
- User-reported latest local suite: 333 passed, 6 skipped, 1 warning, 6 subtests passed. This report did not rerun the suite.

The UI prototype and README run instructions are committed on the development feature branch. A feature-branch commit is not the same as merging the PR.

## 3. Locked KTMI entry signals

Keep strategy sources separate; do not silently merge events or alter trigger semantics.

| Source | Bullish trigger | Bearish trigger | Contract bought |
|---|---|---|---|
| Strategy A | Long Speed crosses upward through +0.50 | Short Speed crosses upward through +0.50 | LONG → CE; SHORT → PE |
| Strategy B | Long Momentum Speed crosses upward through +0.49 | Short Momentum Speed crosses downward through −0.49 | LONG → CE; SHORT → PE |

- **Bullish/LONG underlying signal buys a Call (CE).**
- **Bearish/SHORT underlying signal buys a Put (PE).**
- Both are long-premium positions. A bearish signal does not mean shorting the option or selling option premium.
- Evaluate completed bars only unless a separate intrabar mode is explicitly specified and tested.
- Keep signal-candle bucket timestamp separate from the actual decision timestamp to prevent look-ahead.
- Preserve simultaneous A/B events as separate strategy events.
- Intended entry window: after 09:45 IST; stop new entries after 15:00 IST. Forced exit target is 15:10 IST and still requires end-to-end confirmation.

## 4. Contract selection and entry checks

Resolve the exact contract using underlying, valid expiry, strike, CE/PE type and verified instrument metadata. Do not hard-code lot size. Session configuration requires an explicit lot size. The resolver's default strike step of 50 is not universal and must be checked against actual instruments.

Strike policy (ATM, one strike OTM or another) must be explicit and tested. Planning notes mention ATM or one-strike-out, but a final default is not locked.

Current paper defaults include:
- Allocation: ₹15,000.
- Maximum option quote age: 5 seconds.
- Pending-entry timeout: 8 seconds.
- Bar resolution default: 3 minutes (supported session values: 1, 3 or 5 minutes).

Before entry, validate signal identity/timestamp, session, exact contract symbol, expiry/lot size, fresh positive quote, risk/quantity limits and duplicate-signal state. Log rejected signals with specific reasons. Pending entries currently fail closed on restart instead of resuming.

Final sizing formula is not locked. A conservative candidate is to calculate affordable whole lots from allocation and premium × lot size, then apply risk caps. If a lot breaches allocation/risk limits, reject rather than round up.

## 5. SL, target and exit conditions

Current buyer-lifecycle research defaults:
- Initial stop: 20% below entry premium.
- Target: 3R, enabled by default.
- Partial exit: 50% in lifecycle notes; rounding and follow-on behavior need explicit tests.
- KAMA exit: keep aside for now; not part of the current approved baseline.
- EOD forced exit target: 15:10 IST; end-to-end behavior remains to be verified.

Example only: buy a CE at ₹100; 20% stop = ₹80; initial risk R = ₹20; 3R target = ₹160. A PE bought at ₹100 has the same premium arithmetic. This is illustrative, not a claim that the settings are optimal.

Exit conditions to support:
1. Initial premium SL.
2. Configured R-multiple target.
3. Selected TSL candidate.
4. Forced session close.
5. Explicitly defined emergency-halt/open-position handling.
6. Fault handling when quotes/data are stale or disconnected.
7. Partial exit with clear remaining quantity and P&L accounting.

**No-look-ahead:** a stop calculated from the current completed candle's high/low/close cannot trigger retroactively inside that same candle; it becomes eligible for the next candle. If a candle touches both stop and target, choose a deterministic conservative assumption unless lower-timeframe data resolves order. Log PSAR close-based reversals separately from intrabar stop touches.

## 6. TSL shadow lab

Six candidates are evaluated in parallel without controlling the active paper lifecycle:

| Candidate | Parameters | Status |
|---|---|---|
| Chandelier | ATR 9 × 1.5 | Wilder/RMA ATR and recent 9-candle extreme/ratchet corrections; independent parity pending |
| Supertrend A | ATR 5, factor 1.0 | In-house recurrence; TradingView parity not proven |
| Supertrend B | ATR 7, factor 1.5 | In-house recurrence; TradingView parity not proven |
| PSAR A | 0.02 / 0.02 / 0.20 | Deterministic tests, no independent TradingView fixture yet |
| PSAR B | 0.04 / 0.04 / 0.10 | Deterministic tests, no independent TradingView fixture yet |
| Kunal Quant structural trail | ATR 5, swing 2.5 ATR, buffer 0.25 ATR | Adapted from isolated research source; fixture parity pending |

Known limitations:
- Shadow P&L is gross; costs and slippage are not yet included.
- No forced EOD close in shadow evaluator.
- No restoration of active candidate state after restart.
- Summary waits until all candidates exit.
- PSAR tests are not proof of TradingView parity; Supertrend and Chandelier also need trusted reference fixtures.
- Shadow records are not a complete historical replay of all past trades.

Do not rank candidates until reference parity, costs and exit assumptions are validated.

## 7. Data and backtest discipline

FYERS acquisition/repair has been explored; Dhan is planned as an additional source. The practical plan is to start with one complete, verified year rather than a larger incomplete dataset.

Required research gates:
- Record instrument, expiry, strike, option type, interval, source, timestamps and missing bars.
- Verify contract mapping and session boundaries.
- Separate tuning from out-of-sample evaluation; use walk-forward checks where appropriate.
- Include fees, spread, slippage and realistic fills.
- Report expectancy, win rate, average win/loss, profit factor, drawdown, trade count, time in market and sensitivity to costs.
- Previously stated goals of profit factor >1.8 and max drawdown below roughly 10–15% are targets, not achieved results or guarantees.

Existing dashboard notes record a 24 September 2026 checkpoint: 2,500 bars, 300 KTMI events, 84 completed, 198 unresolved and 16 no-entry-candle. These are resolution counts, not performance results, and need refreshing.

## 8. Architecture and key files

| Component | Role / caveat |
|---|---|
| `paper_trading/market_data_pipeline.py` | Ticks → completed bars → resampling → signal evaluation |
| `market_data/live_ticks.py` | Minute-bar builder |
| `market_data/fyers_quote_cache.py` | Exact-symbol quote cache; timestamp normalization/stale handling |
| `paper_trading/fyers_feed.py` | FYERS WebSocket wrapper; real SDK compatibility still needs validation |
| `paper_trading/pending_entry_orchestrator.py` | Contract resolution, option subscription, fresh quote, pending journal/dedup |
| `paper_trading/coordinator.py` | Entry coordination, duplicate/no-lookahead checks |
| `paper_trading/entry_adapter.py` | Quote, symbol, price and timestamp validation |
| `paper_trading/buyer_lifecycle.py` | Buyer-only CE/PE lifecycle |
| `paper_trading/session.py` | Composition root for feed/pipeline/resolver/engine/coordinator/recorder/TSL |
| `paper_trading/recorder.py` | CSV event/trade recording |
| `paper_trading/tsl_shadow_lab.py` | Six-candidate research evaluator |
| `paper_trading/TSL_SHADOW_AUDIT.md` | Shadow-lab caveats |
| `paper_trading/PSAR_REFERENCE_VALIDATION.md` | PSAR validation procedure |
| `strategies/option_contract_resolver.py` | Underlying-to-option mapping |
| `dashboard/prototype_app.py` | First-version UI prototype; sample data only |
| `dashboard/app.py` | Existing separate dashboard |
| `backtest/option_trade_lifecycle.py` | Locked historical V1 lifecycle |

## 9. UI prototype

Six sections reflect the first supplied design: Dashboard, Strategies, Orders, Portfolio, AI research and Settings. It uses a dark navy/blue theme, illustrative chart/positions/P&L and a prototype kill switch. It has no broker connection, no AI provider and no order placement. Deploy/edit and credential-save controls are disabled.

Run from the development checkout:
```powershell
cd C:\Users\USER\Desktop\Kunal\kunal-quant-claude-version
.\.venv\Scripts\Activate.ps1
cd dashboard
streamlit run prototype_app.py
```

The HTML source remains the visual source of truth until the user approves deviations. Keep business logic out of UI pages, label demo data clearly, never commit secrets, and do not enable live trading before a separate approval gate.

## 10. Progress estimate

| Workstream | Estimate | Main remaining work |
|---|---:|---|
| Foundations / locked rules | 70% | End-to-end traceability/reproducibility |
| Historical data quality | 35% | Complete verified coverage, gap audit, provider parity |
| Backtesting/statistical validation | 30% | Event resolution, realistic costs/fills, out-of-sample robustness |
| Buyer-only paper lifecycle | 55% | Integration, restart persistence, risk controls |
| FYERS streaming/paper quote path | 45% | Real SDK/reconnect/end-to-end validation |
| Risk/session management | 35% | Daily caps, forced EOD, fault policy, persistence |
| TSL shadow research | 40% | Independent parity, costs/slippage, restart/EOD |
| Dashboard visual prototype | 60% | Pixel-level comparison, local verification, refinement |
| Dashboard/data integration | 10% | Real service/data-source connection |
| AI strategy assistant | 10% | Provider, validated strategy schema, review/deploy flow |
| Dhan data-source integration | 15% | Auth, adapter, normalization and quality audit |
| Live execution/production readiness | 0% | Intentionally disabled; all gates and broker safeguards |

**Overall estimated completion: approximately 35–40%.** This is not a profitability or production-readiness score.

## 11. Prioritized roadmap

1. **Preserve branch/review boundary:** inspect diff/tests; protect original repo and locked lifecycle; merge only after review.
2. **Data-quality baseline:** choose instrument/period, download data, quantify gaps, independently verify a sample, publish coverage report.
3. **KTMI event resolution:** resolve against correct option candles, enforce no-lookahead and explain all unresolved/no-entry cases.
4. **TSL reference fixtures:** compare trusted exported OHLC/indicator values bar by bar before ranking.
5. **Paper lifecycle integration:** synthetic signal → contract → fresh quote → sizing → entry → exits → journal; test faults and restart.
6. **FYERS feed validation:** read-only connection; verify payloads, symbols, timestamps, reconnect and quote freshness.
7. **Dhan historical adapter:** safe authentication, defined download period, normalized schema and independent comparison.
8. **Dashboard data service:** replace demo source; display true freshness, connection status, signals, positions, P&L and errors.
9. **Paper trial:** pre-agreed sessions; reconcile events, costs, exit semantics, limits and restart behavior.
10. **Live gate:** only after previous gates—broker order adapter, reconciliation, idempotency, kill-switch tests and explicit approval.

## 12. Safety and handover checklist

- Paper mode is default; live mode remains disabled.
- Never claim an order or close without broker confirmation.
- Keep secrets out of source control.
- Define kill-switch handling for both new entries and existing positions.
- Persist signal IDs, open positions and exits across restart.
- Test disconnect/reconnect, stale data, timestamp units, missing bars, quote mismatch, partial fills and session close.
- Use exchange timestamps and Asia/Kolkata session boundaries.
- Separate simulated fills from real broker positions.
- New collaborators should read this file, the TSL audit and PSAR validation note, inspect the PR, run tests locally and preserve locked logic.

## Closing

Kunal Quant is a staged engineering and research program. The next milestone is a trustworthy end-to-end paper run backed by verified data and auditable exits, followed by measured out-of-sample research. Live trading should remain disabled until those gates are satisfied.
