# Gap Reversal strategy (stocks and indexes)

The owner's idea, built in October 2026. **Research and paper only.** It never places real orders.

When a stock (or index) opens with a big gap, trapped buyers (after a gap up) or trapped sellers (after a gap down)
often give the move back. The strategy waits for a **reversal setup** in the first candles of the day, rates it with a
**reversal strength %**, and trades it with the stop at the day's extreme.

| | SHORT side | LONG side |
|---|---|---|
| When | gap UP of `gap_pct`% or more (default 3%) | gap DOWN of `gap_pct`% or more |
| Setup | bearish reversal in the opening window | bullish reversal (the mirror) |
| Stop | the day's HIGH so far (+ optional buffer) | the day's LOW so far (- optional buffer) |
| Target | 1:1.5, 1:2 (default), 1:2.5 or 1:3 of the risk | same |
| Flat by | 15:10 (setting) | same |

Gap % = (today's open - previous close) / previous close x 100.
Opening window = the first **10 candles of 5 minutes** (09:15-10:05) or the first **16 candles of 3 minutes**
(09:15-10:03). Both numbers are settings. The two sides have **separate settings** (on/off, setups, minimum strength,
entry, target, stop buffer).

## The 10 setups (the picture `docs/reversal_setups.png`)

The sheet was sent to the owner to check. Each SHORT setup has a LONG mirror (the same candles upside down).

| # | SHORT after a gap up | LONG after a gap down | What it means |
|---|---|---|---|
| 1 | Shooting star / pin bar | Hammer | long wick at the extreme: price was pushed back |
| 2 | Doji at the top | Doji at the bottom | buyers and sellers equal after a strong run (owner's HCLTECH/SWIGGY examples) |
| 3 | Bearish engulfing | Bullish engulfing | one candle swallows the previous one |
| 4 | Evening star | Morning star | up candle, small candle, strong down candle |
| 5 | Dark cloud cover | Piercing line | opens above, closes deep into the previous candle |
| 6 | Tweezer top | Tweezer bottom | two candles fail at the same price |
| 7 | Bearish harami | Bullish harami | small candle inside a big one: momentum stops |
| 8 | Failed breakout (bull trap) | Failed breakdown (bear trap) | new high, then a close back below the old high |
| 9 | Volume climax / absorption | Selling climax | huge volume but price does not go further (owner's ADANIENT examples) |
| 10 | Double top / lower high | Double bottom / higher low | second push fails, close below the middle low |

The trigger price (the level the entry waits for) is the setup's low for a SHORT (high for a LONG); for the double top
it is the middle low (neckline).

## Reversal strength %

Four parts, each 0 to 100%, mixed by weights (all settings):

| Part | Weight | Measures |
|---|---|---|
| Rejection | 25 | how far the setup closed back from its extreme (close near the low of the setup = 100%) |
| Absorption | 30 | the biggest-volume candle of the setup vs the average volume before it (3x or more = full), times how little price moved on that volume. Huge volume + small progress = buyers absorbed by sellers. Indexes have no volume: neutral 50%. |
| Location | 20 | half for being at the day's extreme (within 0.5%), half for how stretched price is above VWAP (1% = full) |
| Confirmation | 25 | the next candle: closes beyond the trigger = 100%, only trades beyond it = 60% |

Strength = weighted average x a pattern weight (harami 0.8, tweezer 0.9, double top 0.9, others 1.0).
A setup **qualifies** when strength >= the side's minimum (default 60%). The scanner marks every setup; only the
**first qualifying** setup of the day is traded.

## Entry (owner: "keep both options switchable")

- **BREAK** (default): enter the moment price trades beyond the trigger, within `entry_valid_bars` candles (default 3).
- **CLOSE**: enter at the close of the first candle that closes beyond the trigger (later, but fewer false starts).

Stop = the day's extreme up to the entry. Risk = stop - entry. Target = entry - RR x risk (SHORT).
`max_risk_pct` (0 = off) skips trades whose stop is too far away. If one 1-minute candle touches both stop and target,
the backtest counts the STOP (the honest assumption).

## Where everything is

| What | File |
|---|---|
| Setups, strength, trade plan, settings | `strategies/gap_reversal.py` |
| F&O stock list (FYERS public master) | `market_data/stock_universe.py` |
| Backtest maths / command | `research/gap_reversal_backtest.py`, `scripts/gap_reversal_backtest.py` |
| Live scanner (+ paper trades) | `scripts/run_gap_reversal.py`, `paper_trading/gap_reversal_paper.py` |
| Dashboard page | `dashboard/pages/8_Gap_Reversal.py` (tabs Today, Settings, Backtest, Chart) |
| Setup picture | `docs/reversal_setups.png` (`scripts/draw_reversal_setups.py` makes the HTML) |
| Settings / results | `data/gap_reversal/` (settings.json, status.json, backtest_*.csv) |

## Commands (folder `C:\Users\USER\Desktop\Kunal\kunal-quant-claude-version`, `(.venv)` active)

```powershell
# Backtest on all F&O stocks, free Yahoo 1-minute data (last ~29 days, no login). Takes 10-20 minutes.
python scripts\gap_reversal_backtest.py
# Longer history from FYERS (needs today's FYERS login):
python scripts\gap_reversal_backtest.py --source fyers --days 90
# Only some stocks / re-run on downloaded data after changing settings:
python scripts\gap_reversal_backtest.py --symbols HCLTECH,ADANIENT,SWIGGY
python scripts\gap_reversal_backtest.py --source cache

# Live scanner on a trading day (needs today's FYERS login). Start before 09:15; it waits until 09:16,
# finds today's gaps, then scans every minute until 15:35.
python scripts\run_gap_reversal.py
```

The dashboard page **Gap Reversal** shows today's gaps, setups with their strength %, paper trades, the settings form,
the backtest tables and a **Chart** tab: pick any marked setup and see it on the TradingView-style chart with a yellow
arrow and its strength %.

The strategy is **OFF** by default: the scanner only marks setups. Tick "Strategy ON" in Settings to paper-trade
(paper capital 1,00,000, 20% per trade, as settings). Owner plan: scanner + paper first; later intraday cash (MIS);
if proven, CE/PE options.

## Backtest results (honest)

BACKTEST_RESULTS

## Limits to know

- Yahoo gives only about 29 days of 1-minute data, so the sample is small. Use `--source fyers --days 90` (or more)
  before trusting any number.
- Previous close in the backtest = the previous session's last 1-minute close (close to the official close, not
  identical). The live scanner uses FYERS' official previous close and open.
- Real cash trading needs short-selling in MIS for the SHORT side (allowed intraday for stocks). Not built yet.
