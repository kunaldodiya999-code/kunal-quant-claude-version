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

1. At the scan time (default **09:20**, after the first 5 minutes) the program reads every F&O stock and its future.
2. A stock is a candidate when the spot **or** the future shows open = low / open = high.
3. The other one must show the same thing ("Spot and futures": **Both must agree** by default, or "One is enough").
4. Option chain: the nearest expiry, **11 strikes** (ATM, 5 ITM, 5 OTM; from the real strike list, because strike gaps
   differ per stock) for calls **and** puts = 22 options. It counts how many show the same picture (table above).
   At least **11 of 22** must agree (setting).
5. Liquidity: the future must have traded at least **Rs 5 crore** since the open; the ATM call and put bid-ask
   spread must be at most **1%** of the premium; optional minimum option volume.
6. The candidates that pass are ranked: most agreeing options first, then liquidity. The **top 5** are traded.

"Equal" uses a tolerance: open within **0.05%** of the low counts as open = low for the stock and the future,
**0.5%** for options (premium ticks are coarse). Every number above is a setting.

## The trade

- **Trade in** (setting): **Stock** (intraday, Rs 50,000 per trade, default), **Future** (1 lot), or **Option**: buy
  1 lot of the ATM call for a LONG, the ATM put for a SHORT (owner rule: bearish = BUY PUT, never sell options).
- Entry: at the scan, at the current price.
- Stop: the day's low (LONG) / high (SHORT) plus the buffer, on the stock chart (on the futures chart for Future).
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

Result (25 Oct 2026, 213 F&O stocks, scan 09:20, top 5, net Rs after charges):

| Exit plan | 5-min data, 38 days: 190 trades (84 LONG, 106 SHORT) | | | 1-min data, 17 days: 85 trades | |
|---|---|---|---|---|---|
| | both | LONG | SHORT | both | win % |
| Fixed 1:1.5 | -3,448 | -3,418 | -30 | +1,514 | 50.6% |
| Fixed 1:2 | +1,456 | -3,070 | +4,527 | +4,748 | 48.2% |
| Fixed 1:2.5 | **+4,101** | -1,775 | **+5,876** | +5,312 | 48.2% |
| Fixed 1:3 | +2,828 | -2,846 | +5,674 | **+5,440** | 48.2% |
| TSL Chandelier 9 x 1.5 | -6,143 | -5,036 | -1,107 | +689 | 45.9% |
| TSL Supertrend 5 x 1 | -7,876 | -6,074 | -1,802 | +1,267 | 50.6% |
| TSL Supertrend 7 x 1.5 | -4,145 | -4,173 | +28 | +3,474 | 47.1% |
| TSL PSAR 0.02/0.02/0.20 | -6,926 | -6,660 | -266 | -1,264 | 47.1% |
| TSL PSAR 0.04/0.04/0.10 | -6,479 | -5,910 | -570 | +219 | 50.6% |
| TSL point trail 10/15 | -294 | -4,096 | +3,802 | +4,007 | 50.6% |

What it says: the stock-only rule is roughly break-even. Fixed targets 1:2.5 / 1:3 were slightly positive on both data
sets (about Rs 20-60 per trade); the TSLs were negative on the 60-day data. Open = high (SHORT) did better than
open = low (LONG) on the 60-day data. Taking 10 a day instead of 5 lost money on both data sets. The futures and
option confirmation is the part meant to lift the quality; only the live journal can show if it does.
