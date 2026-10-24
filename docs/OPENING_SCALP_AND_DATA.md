# Opening Scalp, Clean Data Sweep and KTMI Accuracy

Written 2026-10-24. Everything here is **research only**. The Opening Scalp is **OFF by default**
(`OpeningScalpConfig.enabled = False`) and is **not connected to the live/paper runner yet**.
Nothing in this document places an order.

All commands run in VS Code, PowerShell, folder
`C:\Users\USER\Desktop\Kunal\kunal-quant-claude-version`, with `(.venv)` showing.

---

## 1. What the HFT checkpoints in KunalQuant say (summary)

Read from the KunalQuant repo (read-only): `docs/HFT_10S_HISTORICAL_DATA_PLAN.md`,
`HFT_10S_PIPELINE.md`, `HFT_CONTRACT_DISCOVERY.md`, `HFT_GAP_OPEN_STRATEGY_V1.md`,
`docs/checkpoints/2026-09-28_hft_10s_data_layer_checkpoint.md`, `config/hft_strategy.py`,
`config/hft_data.py`, `research/hft_gap_open_v1.py`.

- **Seconds data:** FYERS gives no seconds history for the spot index. The plan therefore uses
  **NIFTY futures** as the price path, downloads **5-second** candles and joins them into 10-second.
  FYERS keeps seconds history for only a short time, so it must be collected every day.
- **Gap-Open V1 rules:** gap of 50+ points at the open; the first 10-second candle has Open == Low
  (or Open == High for a gap down); the next candle breaks that high (low); stop capped at 20 points;
  targets 2R/3R/4R; trailing (buffer 10, minimum lock 15). Disabled by default, never traded.
- **Status at the checkpoint:** data layer built, no profit result yet, because there were not
  enough clean seconds days.

What this repo adds: the same idea (catch the first big move after 09:15) but on **1-minute data
that we actually have clean**, with **three entry styles**, honest exits and a walk-forward check.
The futures 5-second download is in the sweep (last 10 days) so the 10-second version can be
tested once enough days are collected.

---

## 2. Clean historical data (the sweep)

Command (downloads and checks everything; FYERS needs today's login first):

```
python scripts\sweep_market_data.py --source both --days 730
```

- `--source yahoo` needs no login. `--source fyers` needs `fyers_access_token.txt`
  (`--credentials-folder C:\Users\USER\Desktop\Kunal\KunalQuant` if the token lives there).

What it collects:

| Source | What | How far back |
|---|---|---|
| Yahoo (free) | NIFTY, BANK NIFTY, SENSEX, INDIA VIX | 1-minute about 30 days, 5-minute 60 days, 60-minute 2 years |
| FYERS | Spot index 1-minute for all three, INDIA VIX | as far as FYERS allows (up to `--days`) |
| FYERS | Nearest futures, continuous, 1-minute | up to `--days` |
| FYERS | Nearest futures, 5-second | last 10 days |
| FYERS | Option ladder (5 strikes each side, 2 expiries), 1-minute | last 45 days |

Everything goes into `data\research\market_data.db` (local, not on GitHub) and a table
`data\research\sweep_report.csv`.

**What "clean day" means** (`market_data/day_quality.py`):

- all 375 minutes from 09:15 to 15:29 present, no duplicate minutes;
- every candle valid (low <= open, close <= high);
- no frozen run of 10+ identical candles and no jump over 2% in one candle;
- Yahoo freezes NIFTY/BANK NIFTY around 15:15-15:27 and stamps the official close on the last bars.
  That dead tail is cut off. If the cut starts **before 15:10** the day is dirty.

When Yahoo and FYERS both have a day, the sweep compares them (tolerance 0.05%) and marks
the day verified.

**Result on 24 Oct 2026 (Yahoo only, this cloud machine cannot log in to FYERS):**

| Series | 1-minute clean days | 5-minute clean days | 60-minute clean days |
|---|---|---|---|
| NIFTY | 17 of 18 (28 Sep - 23 Oct) | 37 of 39 | 486 of 490 (2 years) |
| BANK NIFTY | 17 of 18 | 37 of 39 | 486 of 490 |
| SENSEX | 17 of 18 | 37 of 39 | 486 of 490 |
| INDIA VIX | 17 of 18 | 36 of 39 | 485 of 490 |

Yahoo 1-minute joined into 5-minute matched Yahoo 5-minute exactly.
The **best long, clean source is the KunalQuant database** (`data\database\kunal_quant.db`,
5 years of NIFTY 1-minute from FYERS). The research scripts read it directly with `--source kq-db`
and check every day with the same clean rules.

---

## 3. KTMI Uni Lite accuracy

Command:

```
python scripts\ktmi_accuracy.py                       (Yahoo data from the sweep)
python scripts\ktmi_accuracy.py --source kq-db --index NIFTY     (5 years, from KunalQuant)
```

How it works (`research/ktmi_accuracy.py`):

1. Builds 3- and 5-minute candles from the 1-minute history (same code as the live engine).
2. Runs the locked KTMI Uni Lite, profile `UNI_LITE_CORE` (Long Speed crosses above 0.5 = BUY CALL,
   Short Speed crosses above 0.5 = BUY PUT).
3. Keeps signals on clean days only, between 09:30 and 15:00.
4. Enters at the **open of the next candle after the signal candle closes** (no peeking).
5. Measures: was the index moving the right way after 5, 15 and 30 minutes; and the result of
   fixed target/stop pairs (stop counted first if one candle touches both; exit by 15:10).

Saved in `data\research\results\ktmi_accuracy_summary.csv` (one row per index, timeframe,
target and stop) and `ktmi_accuracy_signals.csv` (every signal).

**Result on 17 clean days (28 Sep - 23 Oct 2026):**

| Index | TF | Signals | Right way after 5 / 15 / 30 min | Best profit factor (target/stop) |
|---|---|---|---|---|
| NIFTY | 3m | 107 | 44% / 48% / 51% | 1.32 (40/20) |
| NIFTY | 5m | 58 | 50% / 40% / 47% | 1.32 (50/15) |
| BANK NIFTY | 3m | 117 | 40% / 42% / 46% | 0.92 |
| BANK NIFTY | 5m | 69 | 42% / 49% / 42% | 1.12 |
| SENSEX | 3m | 100 | 49% / 50% / 49% | 1.46 (50/20) |
| SENSEX | 5m | 56 | 43% / 36% / 49% | 1.03 |

**Honest reading:** on this one month the core signal alone is about a coin toss for direction.
The best target/stop pairs are picked after the fact, so the 1.3-1.5 figures are optimistic.
This does **not** say KTMI is bad: one month is small, and the other KTMI parts (kept silent for now)
are filters that may help. Run it on the 5-year KunalQuant data before deciding.

---

## 4. Opening Scalp (new, OFF by default)

Code: `strategies/opening_scalp.py` (rules), `research/opening_scalp_backtest.py` (test).

Goal: one quick trade of 40-50 NIFTY points in the first minutes after the open.
Points are NIFTY-sized; for BANK NIFTY and SENSEX they are scaled by price (about 2.4x and 3.2x).

### The three styles (`mode`)

| Mode | Rule | Direction |
|---|---|---|
| `ORB_CLOSE` (default) | Opening range = 09:15 to 09:25. Wait for a 1-minute candle that **closes** above the range high + 2 points (or below the low - 2). | Close above = BUY CALL, below = BUY PUT |
| `DRIVE` | If the first minutes close near their high (low) with a body of 60%+ of the range, follow it at the next open. | With the opening push |
| `FADE` | If the first minutes ran 60+ points one way, trade back the other way. | Against the push |

### Risk rules (default)

- Stop = distance back to the other side of the range, but **at most 20** and **at least 10** points.
- Target **50** points.
- After a candle **closes** 20 points in profit, the stop moves to the entry price (no loss).
- New entries only until **09:45**; anything still open closes at **10:15**.
- One trade per index per day. If the 09:15 candle is missing, no trade.

Why "close beyond the range" instead of "touch": in the first minutes a touch is often a wick that
snaps back. Waiting for the close avoids most of those false breaks (see the Gap-Open V1 idea of
waiting for the next candle to confirm).

### How the test is kept honest

- Only clean days; decisions use finished candles only.
- Entry at the next minute's open.
- If one candle touches both the stop and the target, the **stop** is counted.
- If the price jumps past the stop, the worse price is used.
- Results are in **index points**. Option profit is only an **estimate**: ATM option moves about
  half the index points, minus 1.5 points for costs and spread.
- **Walk-forward:** pick the best settings on the first half of the days, then test them on the
  second half, which they have never seen.

### Results on 24 Oct 2026

1-minute data, 17 clean days per index (28 Sep - 23 Oct), default settings:

| Group | Trades | Win rate | Profit factor | Avg index points |
|---|---|---|---|---|
| All three indexes | 37 | 43% | **4.0** | +16.2 |
| LONG (BUY CALL) | 16 | 50% | 6.7 | +21.3 |
| SHORT (BUY PUT) | 21 | 38% | 2.9 | +12.4 |
| NIFTY | 11 | 55% | 5.0 | +21.8 |
| BANK NIFTY | 11 | 36% | 2.5 | +10.9 |
| SENSEX | 15 | 40% | 5.0 | +16.0 |
| First half of days | 16 | 44% | 2.9 | |
| Second half of days | 21 | 43% | 5.6 | |

Every ORB_CLOSE setting tried on 1-minute data had a profit factor above 1 (middle value 2.8).

5-minute data, 37 clean days per index (27 Aug - 23 Oct), default settings: 65 trades,
profit factor **1.28**; first half **0.6** (lost), second half 1.94. BANK NIFTY lost (0.74).

`DRIVE` made money mainly on the SHORT side (a falling month); `FADE` lost.

### Honest verdict

- **Promising, not proven.** One month of 1-minute data is about 37 trades. The 5-minute test on the
  earlier weeks shows a losing stretch, so expect losing months.
- On 5-minute data the range and the entry are coarse; the 1-minute version is the real strategy.
- Option profit is roughly **half** of the index points shown, before slippage at the open,
  which is the most expensive time to trade.
- **Before turning it on:** run it on the 5-year KunalQuant NIFTY data (command below). Look for a
  profit factor above 1.3 in most years and in the walk-forward test. Then paper trade it.

```
python scripts\opening_scalp_backtest.py --source kq-db --index NIFTY
```

Other options: `--resolution 5m`, `--index BANKNIFTY`, `--kq-db <path to kunal_quant.db>`.

### Ideas tried and possible next steps

1. Gap filter (trade only when the open gaps 50+ points, as in Gap-Open V1): test on 5 years.
2. INDIA VIX filter: skip days with very low VIX (small moves) or very high VIX (wild wicks).
3. 10-second version on NIFTY futures once enough 5-second days are collected (the sweep stores
   them; FYERS keeps only a short history, so the sweep must run daily).
4. Wire into the paper engine: needs exits in index points and a 1-minute evaluator. Not done yet,
   on purpose, until the 5-year test passes.

---

## 5. Dashboard

Page **"Research Backtest"** (`dashboard/pages/6_Research_Backtest.py`) has three tabs: Clean data,
KTMI Uni Lite accuracy and Opening Scalp. It only reads the result files. If a file is missing,
it shows the command that makes it. Results are saved locally in `data\research` (not on GitHub),
so run the commands once on your PC.

## 6. Files

| File | Purpose |
|---|---|
| `market_data/sources/yahoo.py` | Free Yahoo history download |
| `market_data/sources/fyers_history.py` | FYERS history in safe chunks, futures and option symbols |
| `market_data/day_quality.py` | Clean-day rules |
| `market_data/research_store.py` | `data/research/market_data.db` |
| `scripts/sweep_market_data.py` | The sweep command |
| `research/trade_outcomes.py` | Shared honest entry/exit rules and profit factor |
| `research/ktmi_accuracy.py`, `scripts/ktmi_accuracy.py` | KTMI accuracy |
| `strategies/opening_scalp.py` | Opening Scalp rules (OFF) |
| `research/opening_scalp_backtest.py`, `scripts/opening_scalp_backtest.py` | Opening Scalp test |
| `research/data_loader.py` | Reads the research database or the KunalQuant database |
| `dashboard/pages/6_Research_Backtest.py`, `dashboard/data/research.py` | Dashboard page |
| `tests/test_market_data_sweep.py`, `tests/test_research_backtests.py`, `tests/test_dashboard_research_page.py` | Tests |
