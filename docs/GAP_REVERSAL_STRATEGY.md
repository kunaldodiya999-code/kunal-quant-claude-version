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
| Exit | Reward 1:[box] (default 2) or EMPTY box = trailing stop (TSL) | same |
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

## Exit plan (same for every strategy, owner rule 25 Oct)

Per side (SHORT and LONG separately), on the Settings tab:

- **Reward 1 : [box]**: type 1.5, 2, 2.5, 3 or any other number = the whole trade closes at that target.
- **Empty box** = no fixed target: the **TSL method** you pick takes the trade out when a strategy candle (5 min)
  **closes** beyond its line (or touches it, if you choose "touch").
- TSL methods = the owner's list with the owner's numbers: Chandelier everget 9 x 1.5, Supertrend 5 x 1 and 7 x 1.5,
  Parabolic SAR 0.02/0.02/0.20 and 0.04/0.04/0.10, point trail 10/15 (all numbers editable).
- Box filled AND a TSL chosen: whichever comes first. The day's high (short) / low (long) is always the hard stop.
- The TSL is calculated on the stock's own chart (5-minute candles, the earlier days included for warm-up, like
  TradingView). A TSL value is known at its candle's close and protects the next candles; it only tightens; it starts
  once it is on the protective side of price (above price for a SHORT), so the up-trend values from before the reversal
  do not close the trade at once.
- Point trail 10/15 is in **points** (made for NIFTY). On a stock it means rupees: useful on a Rs 1,500 stock, never
  active on a Rs 120 stock. Prefer the indicator TSLs for stocks.

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
# 5-minute data, about 60 days (Yahoo, no login), and another amount per trade:
python scripts\gap_reversal_backtest.py --interval 5m
python scripts\gap_reversal_backtest.py --capital-per-trade 100000

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

## Backtest results (honest), every exit plan, Rs 50,000 per entry

Run of 25 Oct 2026: all 213 F&O stocks, default settings (gap 3%, 5-minute candles, first 10 candles, minimum
strength 60%), first qualifying setup per stock and day. Every trade was run once per exit plan. Money = Rs 50,000 per
entry (quantity = 50,000 / entry price); **net = after estimated intraday charges** (about Rs 52 per trade, see
`backtest/equity_costs.py`). Win rate = the probability that a trade ends in profit. Avg R = average result per trade
in multiples of the risk (the distance to the day's high / low).

**Main run: Yahoo 5-minute data, 31 Aug - 23 Oct 2026 (38 sessions), 33 trades on 16 days, 31 stocks.**
Entry = BREAK (default). Gross = before charges.

| Exit plan | Both sides: trades / win % / avg R / net Rs | SHORT only (13): win % / net Rs | LONG only (20): win % / net Rs |
|---|---|---|---|
| Fixed target 1:1.5 | 33 / 57.6% / +0.35 / **+920** | 76.9% / +2,757 | 45.0% / -1,837 |
| Fixed target 1:2 | 33 / 51.5% / +0.29 / **+532** | 69.2% / +3,039 | 40.0% / -2,507 |
| Fixed target 1:2.5 | 33 / 51.5% / +0.40 / **+2,121** | 69.2% / +3,902 | 40.0% / -1,781 |
| Fixed target 1:3 | 33 / 51.5% / +0.43 / **+1,935** | 69.2% / **+4,765** | 40.0% / -2,830 |
| TSL Chandelier everget 9 x 1.5 | 33 / 48.5% / +0.14 / **+159** | 38.5% / -1,673 | 55.0% / **+1,832** |
| TSL Supertrend A 5 x 1.0 | 33 / 48.5% / +0.25 / **+1,376** | 53.8% / -158 | 45.0% / +1,534 |
| TSL Supertrend B 7 x 1.5 | 33 / 42.4% / +0.25 / **+199** | 46.2% / +372 | 40.0% / -172 |
| TSL Parabolic SAR A 0.02/0.02/0.20 | 33 / 57.6% / **+0.54** / **+3,914** | 69.2% / +3,891 | 50.0% / +24 |
| TSL Parabolic SAR B 0.04/0.04/0.10 | 33 / 60.6% / +0.34 / **+3,159** | 69.2% / +2,352 | 55.0% / +807 |
| TSL Point trail 10 / 15 | 33 / 66.7% / +0.42 / **+837** | 76.9% / +3,745 | 60.0% / -2,909 |

With the CLOSE entry (wait for a candle to close beyond the setup) results are lower in almost every row (best: Parabolic
SAR A +1,839 net on 27 trades). Full tables (also worst drawdown, targets / stops / TSL exits) on the dashboard page
Gap Reversal > Backtest, data "5-minute", or `data/gap_reversal/backtest_summary_5m.csv`.

What it says, in plain words:
- **Best overall: TSL Parabolic SAR A (0.02/0.02/0.20)**: +Rs 3,914 net on 33 trades (about +Rs 119 per trade),
  57.6% winners, average +0.54R, worst drawdown about -Rs 2,500.
- **SHORT side (after a gap up) works best with a fixed target**: 1:3 made +Rs 4,765 on 13 trades (69% winners);
  PSAR A is close (+Rs 3,891). The indicator TSLs Chandelier / Supertrend gave back too much on shorts.
- **LONG side (after a gap down) only made money with a TSL**: Chandelier +Rs 1,832, Supertrend A +Rs 1,534 on 20
  trades; every fixed target lost money on longs.
- So a sensible first paper setting: SHORT = reward box 3 (or PSAR A), LONG = empty box + Chandelier or Supertrend A.
- Charges matter: about Rs 52 of every trade's result; the average gross trade was only Rs 70-170.
- Busy days: up to 9 setups on one day, i.e. up to Rs 4.5 lakh of positions at Rs 50,000 each (intraday MIS margin is
  a fraction of that).
- **The sample is still small (33 trades)**. Do not trust a single row yet; one or two big trades change the order.
  5-minute data makes entries and stops less exact than 1-minute data.

Check on 1-minute data (Yahoo, 28 Sep - 23 Oct, 13 trades, BREAK entry, net Rs, both sides): 1:1.5 -1,575;
1:2 -819; 1:2.5 -367; 1:3 -1,157; Chandelier -1,633; Supertrend A -1,058; Supertrend B -2,314; PSAR A -2,130;
PSAR B -162; point trail -3,211. On those 4 weeks nothing made money: too few trades to say more.

Next step before any decision: the FYERS 1-minute run over a long period on your PC (needs the daily FYERS login),
`python scripts\gap_reversal_backtest.py --source fyers --days 365`.

## Test with gaps of 1% or more (owner, 25 Oct 2026)

`python scripts\gap_reversal_backtest.py --gap-pct 1` (the saved dashboard setting is not changed). Same rules,
Rs 50,000 per entry, BREAK entry, net after estimated charges, long + short together.

| Exit plan | 5-min data, 28 Aug - 23 Oct: 661 trades | | | 1-min data, 29 Sep - 23 Oct: 268 trades | |
|---|---|---|---|---|---|
| | win % | net Rs | worst drawdown | win % | net Rs |
| Fixed 1:1.5 | 54.0% | +19,377 | -24,152 | 53.7% | +13,370 |
| Fixed 1:2 | 49.9% | +28,366 | -27,491 | 50.7% | +14,888 |
| Fixed 1:2.5 | 47.4% | +34,005 | -27,721 | 47.0% | +14,048 |
| Fixed 1:3 | 46.4% | +41,453 | -27,924 | 46.3% | +16,610 |
| TSL Chandelier 9 x 1.5 | 47.5% | +18,477 | -15,567 | 48.9% | +12,635 |
| TSL Supertrend 5 x 1 | 47.2% | +15,644 | -14,259 | 47.4% | +6,929 |
| TSL Supertrend 7 x 1.5 | 47.5% | +29,627 | -16,198 | 46.6% | +12,412 |
| TSL PSAR 0.02/0.02/0.20 | 50.7% | +39,985 | -14,000 | 48.1% | +17,976 |
| TSL PSAR 0.04/0.04/0.10 | 51.1% | **+40,789** | **-10,044** | 49.6% | **+18,738** |
| TSL Point trail 10/15 | 50.8% | +37,527 | -23,562 | 52.6% | +15,965 |

- Every exit plan was profitable on both data sets (at 3% the 1-minute check was negative).
- Best balance: **PSAR B (0.04/0.04/0.10)**: highest net on both data sets and the smallest drawdown. Fixed 1:3 made
  about the same on 5-minute data but with almost 3x the drawdown.
- SHORT (268 trades on 5-min): fixed 1:3 best (+33,879), PSAR A / point trail next (~+22,000). LONG (393): every
  TSL beat every fixed target; PSAR B best (+23,563).
- **Thin edge**: about Rs 60 net per trade on Rs 50,000 (0.12%); charges took Rs 34,000 of Rs 75,000 gross.
  Slippage is NOT included: 0.05% per trade (Rs 25 in, Rs 25 out) would remove about Rs 33,000 of the 5-min total.
- **Many trades at once**: on average 17 trades a day, up to 63 on one day (Rs 31 lakh of positions at Rs 50,000
  each). In practice a cap is needed (e.g. the strongest N setups per day).

## Daily trade cap (owner, 25 Oct 2026)

Settings tab: **Max trades per day** (default 5 = paper capital 1,00,000 at 20% per trade), **Max SHORT per day**,
**Max LONG per day** (0 = no limit). Trades are taken in the order they ENTER; at the same minute the stronger setup
goes first (no look-ahead: the scanner cannot know a later, stronger setup). Setups past the cap are still marked and
listed as "skipped (daily cap)". The live desk and the backtest use the same rule (`daily_cap` in
`strategies/gap_reversal.py`). Backtest another cap: `python scripts\gap_reversal_backtest.py --max-trades 3`.
Every run also writes `backtest_cap_study*.csv` (no cap, 1, 2, 3, 5, 10), shown on the Backtest tab.

Result at a 1% gap, BREAK entry, net Rs, Rs 50,000 per entry:

| Exit plan | 5-min (38 days): no cap | cap 3 | cap 5 | cap 10 | 1-min (17 days): no cap | cap 3 | cap 5 |
|---|---|---|---|---|---|---|---|
| Fixed 1:3 | 41,453 | 4,332 | 8,657 | 7,327 | 16,610 | 8,016 | 4,901 |
| TSL PSAR 0.02/0.02/0.20 | 39,985 | 3,949 | 5,788 | 9,416 | 17,976 | 7,890 | 7,095 |
| TSL PSAR 0.04/0.04/0.10 | 40,789 | 6,128 | 5,969 | 7,104 | 18,738 | 7,964 | 5,834 |
| TSL point trail 10/15 | 37,527 | 6,980 | 7,957 | 7,570 | 15,965 | 10,222 | 5,277 |

What it shows (honestly):
- A cap protects capital, but it cuts the total profit a lot: most of the profit came from a few BUSY days when
  many stocks gapped and reversed together. Without a cap, 11 Sep and 22 Oct alone made Rs 30,000 of the
  Rs 40,789 (PSAR B); the other 36 days made about Rs 10,000 together, and only 20 of 38 days were positive.
- The first trades of a day (09:20-09:30 entries) were the weakest; entries from 09:40 to 10:00 did best.
- With a cap of 3 to 5, every exit plan stayed profitable on 1-minute data; on 5-minute data the indicator TSLs
  (Chandelier, Supertrend A) turned negative at cap 5, PSAR and the fixed 1:3 stayed positive.

## Limits to know

- Yahoo gives only about 29 days of 1-minute data (60 days of 5-minute), so the sample is small. Use
  `--source fyers --days 365` before trusting any number.
- The money figures use Rs 50,000 per entry with no limit on trades per day; slippage is not included (stop exits at
  the stop price, or at the open when price jumped past it).
- Previous close in the backtest = the previous session's last 1-minute close (close to the official close, not
  identical). The live scanner uses FYERS' official previous close and open.
- Real cash trading needs short-selling in MIS for the SHORT side (allowed intraday for stocks). Not built yet.
