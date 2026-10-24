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
Expected last line: about **559 passed, 5 skipped**.

## Every trading day, at about 9:00

**1. Log in to FYERS** (the folder that has your `.env` file):
```powershell
cd C:\Users\USER\Desktop\Kunal\KunalQuant
python fyers_auth.py
cd C:\Users\USER\Desktop\Kunal\kunal-quant-claude-version
```
A browser opens; log in; come back when it says the token was saved.

**2. Window 1: start trading (all three indexes):**
```powershell
python scripts\run_paper_session.py
```
Only some indexes: `python scripts\run_paper_session.py --index NIFTY,SENSEX`.
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

## Checking signals against TradingView

```powershell
python scripts\ktmi_check.py --date 2026-10-26 --timeframe 3 --index NIFTY
```
During the day the same values are in the dashboard tab "KTMI values per candle".

## Real orders

OFF. Monday is a dry run: the dashboard tab "Broker orders" lists what *would*
be sent. Real orders need a static IP registered with FYERS (SEBI rule) and two
deliberate steps: see `docs\LIVE_ORDERS.md`.
