# Trailing stop (TSL) and trade management

Written 25 Oct 2026 from the owner's requirements brief (PDF + shared ChatGPT conversation) and the
owner's answers. Every number below is a **setting**; nothing is fixed in the code.

Where to change them: dashboard page **Live Paper Trading**, box **"Trade management and trailing
stop (TSL)"** (one set per index: NIFTY, BANK NIFTY, SENSEX). Saved in
`data\paper_trading\<INDEX>\trade_management.json`. **Changes apply to new trades only**; every
trade keeps a copy of the settings it was opened with (also after a restart).

## Defaults

| Setting | Default | Choices |
|---|---|---|
| **Reward 1 : [box]** | **empty** = no fixed target (partial + TSL exit) | any number: the whole trade closes at 1:number (no partial) |
| Initial stop-loss | 30% of the option premium | any % |
| TSL | ON | on / off |
| TSL mode | Indicator | Indicator / Manual (you move the stop) |
| TSL method | Chandelier Exit (everget) ATR 9 x 1.5 | see the method list below |
| Calculate TSL on | **Option chart** (the traded CE / PE) | **dropdown: Option chart / Spot chart** |
| TSL candles | same as the strategy timeframe (3 or 5 min) | dropdown: same as strategy, 1, 3, 5, 10, 15, 30, 60 min |
| Exit when | a candle **closes** beyond the stop | closes beyond / price touches |
| Partial booking | ON at **2R**, **50%** of the lots | any R, any % |
| One-lot trade at 2R | close the whole lot | close the whole lot / keep it and trail |
| After the partial | stop to **breakeven** (entry), then the TSL trails | breakeven / entry + 1R / leave the stop |
| Forced exit | ON at 15:10 (no new trades from 15:00) | on / off; times in Strategy settings |
| Allocation per trade | **20% of available cash**, starting capital 1,00,000 | any %; of available cash or of balance |
| Daily-loss cutoff | OFF | on / off, % of the day's opening equity |

## TSL methods (owner's list; Donchian and rolling-swing stops excluded)

| Method | Numbers (default) | How it trails |
|---|---|---|
| Chandelier Exit (everget) | ATR 9, multiplier 1.5, extremes from closes | highest close of the last 9 candles - 1.5 x ATR (for a falling-index PUT: lowest close + 1.5 x ATR) |
| Supertrend A | ATR 5, factor 1.0 | TradingView `ta.supertrend` lower band (upper band for a PUT on the spot chart) |
| Supertrend B | ATR 7, factor 1.5 | same |
| Parabolic SAR A | 0.02 / 0.02 / 0.20 | TradingView `ta.sar`; also exits when the SAR switches sides |
| Parabolic SAR B | 0.04 / 0.04 / 0.10 | same |
| Point trail (HFT brief) | buffer 10, lock 15 | once 15 points in profit: stop 10 below price, never below entry + 15 |

Every number of every method can be changed (expander "Numbers of every TSL method").
KAMA was discussed separately and is not a TSL method here.

## How a trade is managed

1. **Entry**: unchanged (KTMI Uni Lite, after the signal candle closes).
2. **Initial stop**: 30% below the premium paid, checked on every 1-minute option candle.
3. **TSL**: when a TSL candle finishes (strategy timeframe by default) on the chosen chart, the
   stop is recalculated. It only ever tightens. A stop known at a candle's close protects only
   the following candles (no peeking).
   * **Option chart**: the trade is a bought option, so the stop sits below the option price.
   * **Spot chart**: a CALL trade's stop sits below the index, a PUT trade's above it. When the
     index crosses it, the option is sold at its latest price.
   * **Exit when "closes beyond"**: exit at that candle's close. **"touches"**: exit at the stop
     (or at the candle's open if it jumped past the stop).
4. **2R partial**: 2R = entry + 2 x the initial risk. Example: entry 100, stop 70 (risk 30), 2R =
   160. At 160, 50% of the lots are sold (4 lots -> 2, 3 lots -> 2, 2 lots -> 1). A one-lot trade
   is closed in full. The rest: stop moves to entry (breakeven), then the TSL trails it.
5. **Manual mode**: the stop is the level you type for that open trade (box under the settings).
   You may move it freely (up or down). Option chart: an option price; spot chart: an index level.
6. **Forced exit** 15:10 (switchable), no new entries from 15:00.

Every exit is written to `exit_events.csv` with the reason (`TSL_EXIT`, `PARTIAL_TARGET`, ...).

## Which TSL captures the most? Two ways to compare

1. **Live comparison (option and spot chart)**: for every paper trade the trading program also
   follows all six methods side by side with the trade's own chart, timeframe and trigger, until
   each would have exited (or 15:10). Dashboard: Live Paper Trading, tab **"TSL comparison"**.
   File: `data\paper_trading\<INDEX>\tsl_shadow\tsl_shadow_summary.csv`.
2. **TSL Lab (history, spot chart)**: `python scripts\tsl_lab.py` replays every KTMI Uni Lite signal
   on the clean history with every method and both triggers. Dashboard: Research Backtest, tab
   **"TSL Lab"**. On the 5-year KunalQuant data: `python scripts\tsl_lab.py --source kq-db --index NIFTY`.

First TSL Lab run (Yahoo, 17 clean days, 28 Sep - 23 Oct 2026, index points, spot chart):

| Index / signal TF | Best | Points | PF | Kept of best moves |
|---|---|---|---|---|
| NIFTY 3m | Chandelier everget 9 x 1.5, close | +803 | 1.55 | 17% |
| NIFTY 5m | Supertrend B 7 x 1.5, close | +945 | 1.89 | 24% |
| BANK NIFTY 3m | PSAR B, touch | +835 | 1.20 | 7% |
| BANK NIFTY 5m | PSAR A, touch | +1041 | 1.29 | 11% |
| SENSEX 3m | PSAR A, touch | +2730 | 1.58 | 20% |
| SENSEX 5m | Supertrend B 7 x 1.5, close | +3450 | 1.97 | 28% |

Across all runs PSAR A and B and Supertrend B kept the most; "closes beyond" beat "touches" overall;
the point trail (10 / 15 NIFTY points) is too tight for 3-5 minute KTMI trades. **One month is too
little to choose**: run the TSL Lab on the 5-year data and watch the live comparison before switching.

## Checking the numbers against TradingView

`python scripts\tsl_check.py --date 2026-10-23 --timeframe 3` prints every candle's Chandelier,
Supertrend and PSAR values for that day (`--symbol` for an option chart, `--database` for the
KunalQuant database). Put the same indicators on TradingView and compare the Data Window.

Validation done here: ATR and Parabolic SAR match an independent open-source library exactly
(PSAR from the 3rd candle; the first two candles follow TradingView's own start rule). Chandelier
(everget) and Supertrend follow the Pine code line by line and are checked with hand-calculated
candles (`tests/test_tsl_methods.py`). A TradingView export comparison is the last check.

## Files

`paper_trading/tsl_methods.py` (maths), `paper_trading/trade_management.py` (settings + trail),
`paper_trading/exit_manager.py` (live exits), `paper_trading/tsl_shadow_lab.py` (live comparison),
`paper_trading/buyer_lifecycle.py` (initial stop, 2R partial), `research/tsl_lab.py` + `scripts/tsl_lab.py`,
`scripts/tsl_check.py`, tests `tests/test_tsl_methods.py`, `tests/test_trade_management.py`, `tests/test_tsl_lab.py`.
