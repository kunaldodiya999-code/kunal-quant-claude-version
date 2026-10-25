# Open High Low strategy (F&O stocks)

The owner's idea, built 25 Oct 2026. **OFF by default, research and paper only.** Run it when you want it.
It never places real orders.

## The rule

| | LONG | SHORT |
|---|---|---|
| Stock (spot) | open = low (never traded below the open) | open = high (never traded above the open) |
| Future (current month) | the same | the same |
| Calls (11 strikes) | open = low (call premium only went up) | open = high |
| Puts (11 strikes) | open = high (put premium only went down) | open = low |
| Stop | the day's low minus a buffer (0.2%) | the day's high plus a buffer |

1. When the **first 5-minute candle closes (09:20)** the program reads every F&O stock and its future.
2. A stock is a candidate when the spot **or** the future shows open = low / open = high.
3. "Spot and futures": **One is enough** (default, owner 25 Oct). Switch to **Both must agree** to tighten it.
4. Option chain: the nearest expiry, **11 strikes** (ATM, 5 ITM, 5 OTM; from the real strike list, because strike gaps
   differ per stock) for calls **and** puts = 22 options. It counts how many show the same picture (table above).
   **No minimum** (owner): every match counts. Matches = stock + future + calls + puts that agree, out of 24.
   Example: RELIANCE spot open = low, future not, 2 calls open = low, 4 puts open = high = **7/24**. A minimum can
   still be set ("Minimum options that must agree", default 0).
5. Liquidity: the future must have traded at least **Rs 5 crore** since the open; the ATM call and put bid-ask
   spread must be **less than 0.30%** of the premium (owner; switch to **less than 0.50%**); optional minimum option volume.
   Note: option prices move in steps of 5 paise, so a premium of Rs 16.7 or less can never be below 0.30% (Rs 10 or
   less for 0.50%). Cheap ATM options are therefore left out.
6. The candidates that pass are ranked: **most matches** first, then liquidity. The **top 5** are shortlisted.
7. **Entry (owner, 25 Oct):** LONG when the **next 5-minute candle** (09:20-09:25) crosses **above the first candle's
   high**; SHORT when it crosses **below the first candle's low**. Settings: the first candle's length (1-30 min) and
   how many candles may give the entry (default 1 = only the next one). No cross = **NO ENTRY** for that stock.
   Added rule: if a LONG's price goes **below the open** before the breakout (open = low broken), the setup is
   **CANCELLED** (SHORT: above the open).

"Equal" uses a tolerance: open within **0.05%** of the low counts as open = low for the stock and the future,
**0.5%** for options (premium ticks are coarse). Every number above is a setting.

## The trade

- **Trade in** (setting): **Stock** (intraday, Rs 50,000 per trade, default), **Future** (1 lot), or **Option**: buy
  1 lot of the ATM call for a LONG, the ATM put for a SHORT (owner rule: bearish = BUY PUT, never sell options).
- Entry: at the first candle's high (LONG) / low (SHORT) when it is crossed, or at that minute's open if price
  jumped past it. Option trades: the option's price in that minute.
- Stop: the day's low (LONG) / high (SHORT) at the entry plus the buffer, on the stock chart (on the futures chart for Future).
- Exit: the shared exit plan, per side: **Reward 1 : [box]** (a number = the whole trade closes at that target;
  **empty = no target, the TSL** you choose closes it when a 5-minute candle closes beyond it). Flat by 15:10.
- For Option trades the stop, target and TSL follow the stock; the P&L is the option premium.

## Run it (folder `C:\Users\USER\Desktop\Kunal\kunal-quant-claude-version`, `(.venv)` active, after the FYERS login)

```powershell
# Scan at 09:20 and paper-trade the top 5 (only when "Strategy ON" is ticked); follows them to 15:10:
python scripts\run_open_high_low.py
# Only look: scan now (or at 09:20), show the list, no trades:
python scripts\run_open_high_low.py --scan-only
# Or deploy it with the others (Strategies page, or):
python scripts\run_strategies.py --deploy KTMI_UNI_LITE,OPEN_HIGH_LOW
```

The scan needs about 10-20 seconds of FYERS quotes (all stocks + futures, then 22 options per candidate). The
dashboard page **Open High Low** shows the scan (spot / future yes-no, calls x/11, puts x/11, option score, futures
value, ATM spread, why a stock failed), the paper trades and every setting.

## Backtest (honest scope)

`python scripts\open_high_low_backtest.py` (uses the candles the Gap Reversal backtest downloaded; `--interval 5m`
for about 60 days; `--source yahoo` downloads first; `--scan-at 09:30`, `--top-n 3`).

**Only the stock (spot) part can be tested.** Free history has no stock-futures or stock-option candles, and FYERS
keeps no expired options. So the backtest checks open = low / high on the stock at 09:20, ranks the candidates by
liquidity (rupees traded the day before, at least Rs 50 crore) instead of the option score, and trades the top 5 with
every exit plan, Rs 50,000 per entry, estimated charges. The futures and option checks are judged from the live
program's daily journal (`data\open_high_low\journal\`).

Result with the breakout entry (25 Oct 2026, 213 F&O stocks, first candle 09:15-09:20, entry only in the next
candle, top 5, Rs 50,000 per entry, net Rs after charges):

| Exit plan | 5-min data, 38 days: 78 trades | | | 1-min data, 17 days: 38 trades | |
|---|---|---|---|---|---|
| | both | LONG (31) | SHORT (47) | both | win % |
| Fixed 1:1.5 | -1,860 | +697 | -2,557 | +2,856 | 52.6% |
| Fixed 1:2 | -790 | +1,413 | -2,204 | +3,167 | 52.6% |
| Fixed 1:2.5 | -361 | +1,698 | -2,059 | **+4,006** | 52.6% |
| Fixed 1:3 | -1,260 | +811 | -2,071 | +3,305 | 52.6% |
| TSL Chandelier 9 x 1.5 | -4,271 | -917 | -3,354 | +1,206 | 50.0% |
| TSL Supertrend 5 x 1 | -3,653 | -1,760 | -1,893 | +2,050 | 55.3% |
| TSL Supertrend 7 x 1.5 | -2,869 | -145 | -2,725 | +2,879 | 55.3% |
| TSL PSAR 0.02/0.02/0.20 | -1,116 | -272 | -844 | +2,375 | 55.3% |
| TSL PSAR 0.04/0.04/0.10 | -2,098 | -174 | -1,923 | +2,551 | 60.5% |
| TSL point trail 10/15 | **-224** | -182 | -42 | +1,844 | 52.6% |

- Of the shortlisted stocks only about 4 in 10 broke out in the next candle (5-min data: 157 of 380 entered, 186 no
  breakout, 37 cancelled), so a day has 2 trades on average instead of 5.
- 1-minute data (4 weeks): every exit plan positive (Rs +1,200 to +4,000). 5-minute data (8 weeks): every exit plan
  slightly negative (Rs -200 to -4,300). Too few trades to call it either way.
- Top 2 or 3 per day did better than top 5 on both data sets (e.g. fixed 1:2.5: top 3 +3,339 / +5,612).
- The 5-minute data cannot see inside the breakout candle (entry and stop on the same 5 minutes), so the 1-minute
  numbers are the more exact ones.
- Before the breakout rule (entry at 09:20 at once) the stock-only rule was also roughly break-even.
The futures and option confirmation is the part meant to lift the quality; only the live journal can show if it does.
