# Kunal FYERS Terminal

One simple screen connected to FYERS:

* **Login page first** (FYERS token, once per trading day).
* **Chart** (TradingView look): candles + **VWAP**, **BBP_NM** (bull / bear columns, Direction line) and
  **KTMI Uni Lite**. Timeframes **1 min, 3 min, 5 min**. Index: **NIFTY 50, BANK NIFTY, SENSEX**.
* **Option chain** on the right for the index on the chart, nearest expiry, prices only:
  NIFTY and BANK NIFTY: 5 ITM + ATM + 5 OTM. SENSEX: 8 ITM + ATM + 8 OTM. ATM row is highlighted.
* **Funds available** (live from FYERS), **Funds to utilize per new entry**, **Funds utilized %**.
* **Trade option**: Call box, Put box. **Premium select**: price range `[from] - [to]` or per lot amount.

All prices come live from the FYERS API. **Paper trades by default** (nothing is sent to FYERS).

## The strategy (owner's rules, 28 Oct 2026)

| When | What happens |
|---|---|
| BBP_NM **Direction crosses above 0** (on a FINISHED candle) | exit an open PUT; buy a CALL if the Call box is ticked |
| BBP_NM **Direction crosses below 0** (on a FINISHED candle) | exit an open CALL; buy a PUT if the Put box is ticked |
| Only Call ticked | calls are bought and exited; on a cross below 0 the call is exited and NO put is bought |
| Stop loss | the **low of the option's own candle** (same timeframe) that closed with the signal. Option price at or below it: exit |
| Time | new entries 09:30 to 15:00, everything closed at 15:10 (Settings tab) |
| Orders | **LIMIT only, never market**: buy at price + 2, sell at price - 2 (buffer in Settings) |

**Which strike** (choose one mode):

* **Price range** e.g. `180 - 200`: of the strikes priced inside the range, the **lower price** is bought
  (73000 CE at 195 and 72900 CE at 182: buys 72900 CE).
* **Per lot amount** e.g. `6500`: NIFTY lot 65, so it buys the price nearest to Rs 100 without going above.

**How many lots**: whole lots that "Funds to utilize per new entry" buys (Rs 20,000 at Rs 6,500 a lot = 3 lots),
never more than the funds available. KTMI Uni Lite is shown on the chart only; it does not trade.

## Install (one time) — on your PC, PowerShell

1. Open PowerShell and go to your Kunal folder:
   ```
   cd C:\Users\USER\Desktop\Kunal
   ```
2. Download this project:
   ```
   git clone https://github.com/kunaldodiya999-code/kunal-fyers-terminal.git
   cd kunal-fyers-terminal
   ```
   You are now in `C:\Users\USER\Desktop\Kunal\kunal-fyers-terminal`. All the commands below run here.
3. Make its own Python box (venv) and switch it on:
   ```
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   ```
   The line must now start with `(.venv)`.
4. Install the parts:
   ```
   pip install -r requirements.txt
   ```
5. Check everything works (should end with `passed`):
   ```
   python -m pytest tests -q
   ```

## Your FYERS app (one time)

On **myapi.fyers.in** > Dashboard you need an app (you may already have one for KunalQuant: the same one works).
Note its **App ID** (like `ABCD1234-100`), **Secret ID** and **Redirect URL**. The Redirect URL you type in the
terminal must be exactly the same as in the FYERS app (e.g. `http://127.0.0.1:8000`).

## Every trading day

1. Folder `C:\Users\USER\Desktop\Kunal\kunal-fyers-terminal`, PowerShell:
   ```
   .\.venv\Scripts\Activate.ps1
   streamlit run app.py
   ```
   The browser opens the terminal (if not, open http://localhost:8501). Keep this PowerShell window open.
2. **Login page**:
   * Step 1 (first time only): App ID, Secret ID, Redirect URL, then **Save app details**
     (saved in `.env` in this folder; never uploaded to GitHub).
   * Step 2: **Open FYERS login**, log in (mobile, PIN, OTP), allow the app.
   * Step 3: the browser opens your Redirect URL; the page may say "This site can't be reached" — that is fine.
     Copy the **whole address** from the address bar (it has `auth_code=` in it), paste it, click **Authorize**.
3. The terminal opens. The first start of the day downloads FYERS' contract lists (a minute or so).
4. Fill **Funds to utilize per new entry**, tick **Call** / **Put**, choose the **premium** mode and fill it.
   Everything you type is saved and used straight away.
5. Tabs under the chart: **Today's trades**, **What happened** (every signal and why a trade was or was not taken),
   **Settings** (times, buffer, BBP lookback, Real orders).

To stop: close the browser tab and press `Ctrl + C` in the PowerShell window.

## Real orders (later, only when you decide)

Two locks, both needed, every day:
1. Settings tab: switch **Real orders** ON.
2. In a second PowerShell window (same folder, venv on): `python arm_real_orders.py` and type the phrase it shows.
   It is valid for TODAY only. `python arm_real_orders.py --off` switches it off.

FYERS only accepts API orders from your **whitelisted static IP** (SEBI rule 2026): set it up with FYERS first.
Orders are LIMIT orders only (buy price + buffer, re-priced at most Rs 1 higher, sell price - buffer). Never market.

## Files

| Path | What |
|---|---|
| `app.py` | the screen (login + terminal) |
| `terminal/engine.py` | the loop: prices, chain, candles, signals, stop loss, 15:10, chart data |
| `terminal/strategy.py` | the owner's rules (strike pick, lots, crosses) |
| `terminal/indicators.py` | BBP_NM (from the owner's Pine code), VWAP, KTMI Uni Lite |
| `terminal/fyers.py` | FYERS login, quotes, history, funds, contract list |
| `terminal/broker.py` | paper fills and real limit orders |
| `indicators/ktmi*`, `live_trading/` | copied unchanged from kunal-quant-claude-version (KTMI is locked) |
| `data/` (on your PC only) | token, settings, open trade, trades.csv, events.log |

Charts by TradingView Lightweight Charts™ (Apache 2.0, `static/lightweight-charts/LICENSE`).
