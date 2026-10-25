# Trading-day guide (paper trading on live prices)

Everything runs in **`C:\Users\USER\Desktop\Kunal\kunal-quant-claude-version`**
unless a step says otherwise. You need two VS Code terminal windows.

## Once, before the first day (about 2 minutes)

```powershell
cd C:\Users\USER\Desktop\Kunal\kunal-quant-claude-version
.\.venv\Scripts\Activate.ps1
git pull origin claude/affectionate-bardeen-3k5sls
pip install -r requirements.txt
python -m pytest tests -q --ignore=tests/expiry_isolation_test.py
```
Expected last line: about **707 passed** plus 5 errors / skips (the 5 tests that need the price database).

## Every trading day, at about 9:00

**1. Log in to FYERS** (the folder that has your `.env` file):
```powershell
cd C:\Users\USER\Desktop\Kunal\KunalQuant
python fyers_auth.py
cd C:\Users\USER\Desktop\Kunal\kunal-quant-claude-version
```
A browser opens; log in; come back when it says the token was saved.

**2. Window 1: start every DEPLOYED strategy** (dashboard page **Strategies** chooses which; default = KTMI only):
```powershell
python scripts\run_strategies.py
```
It starts each deployed strategy in this window; every line starts with its name, e.g. `[KTMI_UNI_LITE]`,
`[GAP_REVERSAL]`. Ctrl+C stops all. Deploy from the command line too:
`python scripts\run_strategies.py --deploy KTMI_UNI_LITE,GAP_REVERSAL` (or `--deploy all`, `--deploy none`);
`--list` only shows the choice.
Only KTMI, as before: `python scripts\run_paper_session.py` (it does nothing if KTMI is not deployed).
Only some indexes: `python scripts\run_strategies.py --index NIFTY,SENSEX`.
The first start of the day downloads the FYERS contract lists (~100 MB, a minute or two).
Leave this window open. It stops by itself at 15:35.

**3. Window 2: the dashboard** (click `+` in the VS Code terminal panel for a new terminal):
```powershell
cd C:\Users\USER\Desktop\Kunal\kunal-quant-claude-version
.\.venv\Scripts\Activate.ps1
cd dashboard
streamlit run app.py
```
Open **Live Paper Trading** in the browser.

## What you should see in window 1

```
FYERS login OK
NIFTY 50: lot 65, expiry Tue 27 Oct, 3-min, BOTH, 09:30-15:00, strikes CALL ATM / PUT ATM
BANK NIFTY: lot 30, expiry Tue 27 Oct, ...
SENSEX: lot 20, expiry Thu 29 Oct, ...
NIFTY 50: warm-up ... bars of history
Connecting to FYERS live data... leave this window open.
```

## If something goes wrong

| Message | What to do |
|---|---|
| `FYERS login failed` | Run step 1 again, then step 2. |
| `FYERS login files not found` | Run step 1 in the folder that has `.env`. |
| `WARNING ... no live price for ...` | Check the internet. The program reconnects by itself (up to 50 tries). |
| Dashboard: "trading program is not running" | Window 1 was closed or stopped: run step 2 again. Open trades are restored. |
| Anything else | Copy the red text and send it to Claude. |

## Settings (any time, also from the dashboard)

```powershell
python scripts\paper_settings.py                                  # show all three
python scripts\paper_settings.py --index SENSEX --timeframe 5     # one index
python scripts\paper_settings.py --index ALL --direction LONG     # all indexes
```

## Which indexes trade ("Trade in")

Start the program as usual (it watches all three). On the dashboard page **Live Paper Trading**,
box **Trade in**: tick **All indexes**, or untick it and choose one or two indexes, then
**Save trade-in choice**. Each chosen index takes its own KTMI Uni Lite signals. Indexes not
chosen are still watched (prices, KTMI, chart) but take no new trades; their signals appear
under "Rejected signals" with the reason. Open trades always run to their exit.
Same from PowerShell: `python scripts\paper_settings.py --index BANKNIFTY --trade OFF`.

## Stop-loss, trailing stop (TSL) and 2R booking

Dashboard page **Live Paper Trading**, box **Trade management and trailing stop (TSL)** (per index).
Defaults: stop 30% of premium, Chandelier Exit 9 x 1.5 on the SPOT chart (choose Spot / Futures / Option), exit when a candle closes
beyond it, 50% booked at 2R then stop to entry, 20% of available cash per trade.
**Reward 1 : [box]** (every strategy has it): a number = the whole trade closes at 1:number; EMPTY (default) =
no fixed target, the partial booking (if on) and the TSL take the trade out. Changes apply to new
trades. Tab **TSL comparison** shows how every TSL method would have done on each trade.
Full guide: `docs/TSL_AND_TRADE_MANAGEMENT.md`.
If you saved this box before 25 Oct 2026, your saved choice may still say "Option chart": pick "Spot chart"
once in "Calculate TSL on" and press save.

## Chart with drawing tools

Dashboard page **Chart** (TradingView style, full guide: `docs/CHART_GUIDE.md`): timeframe buttons
1m-1D, signal filter Both / Long / Short / Off, indicators (futures volume, KTMI Uni Lite, VWAP with
1/2/3 SD bands, Bollinger Bands, OI profile, Smart Money Concepts), tools (horizontal, vertical,
rectangle, path, measure, volume profile with POC / VAH / VAL / high / low). Updates itself every
few seconds. The trading program now also saves futures volume, daily candles and option-chain OI
for it. The chart only shows; it never places a trade.

## Gap Reversal scanner (stocks; started by run_strategies.py when deployed, or by hand)

Gap of 3% or more at the open, then a reversal setup in the first candles (full guide: `docs/GAP_REVERSAL_STRATEGY.md`).
Third PowerShell window, folder `C:\Users\USER\Desktop\Kunal\kunal-quant-claude-version`, `(.venv)` active, after
the FYERS login, before 09:15:

```powershell
python scripts\run_gap_reversal.py
```

It waits until 09:16, lists today's gap stocks, then checks every minute until 15:35. Dashboard page **Gap Reversal**
shows the gaps, setups with their strength %, and paper trades (only when "Strategy ON" is ticked in its Settings tab;
OFF by default = marking only). Paper only, never real orders.

## Open High Low scanner (stocks; OFF by default, run it when you want it)

Open = low (long) / open = high (short) on the stock and its future, confirmed by 22 options, top 5 shortlisted at
09:20, each entered when the next 5-minute candle breaks the first candle's high (long) / low (short), on paper
(full guide: `docs/OPEN_HIGH_LOW_STRATEGY.md`). Folder `C:\Users\USER\Desktop\Kunal\kunal-quant-claude-version`,
`(.venv)` active, after the FYERS login, before 09:20:

```powershell
python scripts\run_open_high_low.py               # trades only when "Strategy ON" is ticked
python scripts\run_open_high_low.py --scan-only   # just the list
```

Dashboard page **Open High Low**.

## Time Machine (odds, off the chart)

Gap Reversal and Open High Low show a **time machine** column (`win 45% · target 28%`) and a closed box with the
chance of reaching 1:1.5 / 1:2 / 1:2.5 / 1:3 before 15:10. Information only (guide: `docs/TIME_MACHINE.md`). Any idea:
`python scripts\time_machine.py --symbol RELIANCE --side LONG --entry 1190 --stop 1180`
(folder `C:\Users\USER\Desktop\Kunal\kunal-quant-claude-version`, after the FYERS login).

## Checking signals against TradingView

```powershell
python scripts\ktmi_check.py --date 2026-10-26 --timeframe 3 --index NIFTY
```
During the day the same values are in the dashboard tab "KTMI values per candle".

## Real orders

OFF. Monday is a dry run: the dashboard tab "Broker orders" lists what *would*
be sent. Real orders need a static IP registered with FYERS (SEBI rule) and two
deliberate steps: see `docs\LIVE_ORDERS.md`.
