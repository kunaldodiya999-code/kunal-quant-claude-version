# Chart guide (dashboard page "Chart")

A TradingView-style chart for NIFTY 50, BANK NIFTY and SENSEX. It only shows; it never places a trade.

Open it: in VS Code, folder `C:\Users\USER\Desktop\Kunal\kunal-quant-claude-version\dashboard`,
run `streamlit run app.py`, then click **Chart** on the left.

## Above the chart (page controls)
- **Index**: NIFTY 50, BANK NIFTY or SENSEX.
- **Data**: "Trading program" (today, live), "Research data" or "KunalQuant database" (past days).
- **Days**: how many trading days the intraday timeframes show (1D always shows about a year).

## Top bar of the chart
- **1m 3m 5m 10m 15m 30m 1h 1D**: switch timeframe instantly. Each timeframe has its own
  KTMI Uni Lite values (the locked calculation, closed candles only, same as the trading engine).
- **ƒx Indicators**: tick an indicator to add it; ⚙ opens its settings.
- **Signals Both / Long / Short / Off**: which KTMI Uni Lite arrows are drawn
  (green "BUY CALL" = Long Speed crossed above +0.5, red "BUY PUT" = Short Speed crossed above +0.5).
- **live**: the chart updates itself every few seconds (no reload, your drawings stay).

The legend at the top-left shows the values under the mouse. Each indicator line has ⚙ (settings) and ✕ (remove).

## Volume
The spot index has no volume. The chart shows the **nearest futures contract's volume** for the
same minute (for example NSE:NIFTY26OCTFUT) under the spot candles. VWAP and the volume profile use it.
The trading program saves it (`futures_minute_candles.csv`). If a data source has no futures
volume, the chart says so; VWAP then uses equal weights and the profile counts time instead.

## Indicators (any number at once)
| Indicator | Settings |
|---|---|
| Volume (futures) | moving average on/off and length, colours |
| KTMI Uni Lite | momentum lines on/off (they are silent, not traded) |
| VWAP | anchor (Session, Week, Month, Quarter, Year), source, offset, bands mode (standard deviation or percentage), **band #1, #2, #3 on/off** with multipliers 1, 2, 3, hide on 1D, fill, colours |
| Bollinger Bands | length 20, basis MA type (SMA, EMA, SMMA (RMA), WMA, VWMA), source, StdDev 2, offset, background, colours |
| OI Profile | option-chain open interest per strike at the right edge: OI, change in OI or both; strikes each side; width; values; highest call OI (resistance) and highest put OI (support) marked; colours. Refreshed every minute by the trading program (`oi_chain.json`). Only for today (live data). |
| Smart Money Concepts | internal and swing structure (BOS / CHoCH, filter All / BOS / CHoCH), swing length 50, internal length 5, swing points (HH / HL / LH / LL), strong / weak high and low, internal and swing order blocks (how many, mitigation Close or High/Low), equal highs / lows (bars, threshold), fair value gaps (auto threshold, extend), premium / discount zones, mode Historical / Present, colours |

## Drawing tools (left toolbar)
| Tool | How |
|---|---|
| Cursor | drag to move the chart; click a drawing to select it; drag it or its dots; **Delete** key removes it |
| Horizontal line | one click at the price |
| Vertical line | one click at the time |
| Rectangle | click one corner, then the opposite corner |
| Path | click each point; click the last point again (or Enter) to finish; Esc cancels |
| Measure (scale) | click start, then end: shows points, %, number of bars and time |
| Volume profile (fixed range) | click the first candle, then the last candle. Shows **POC** (red), **VAH / VAL** (value area, blue), **High / Low** of the range. Settings (⚙ on the left, or double-click it): rows layout (number of rows / ticks per row), row size 24, volume Up/Down / Total / Delta, value area 70%, extend right, show profile, show values, width, placement left/right, show high/low, developing POC, developing VA, colours |

Colour square: colour of the next drawing or of the selected one. Bin: delete the selected drawing.
Double bin: remove all drawings of this index (click twice).

Everything you choose (timeframe, indicators, settings, signal filter, drawings, zoom) is saved in
this browser, separately for each index.

## Files
- `dashboard/pages/7_Chart.py` (page), `dashboard/chart_component.py` (layout),
  `dashboard/static/kq_chart.js` (chart), `dashboard/static/kq_indicators.js` (indicator maths),
  `dashboard/data/chart.py` (data), `paper_trading/chart_feeds.py` (futures volume, daily candles, OI).
- Chart library: TradingView Lightweight Charts 4.2.3 (Apache 2.0), stored in `dashboard/static/lightweight-charts`.
- Live updates need `enableStaticServing = true` (in `dashboard\.streamlit\config.toml`, already set).
