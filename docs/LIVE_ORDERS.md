# Real broker orders (FYERS): how they work and how they stay OFF

Built 2026-10-24. **OFF by default.** Code: `live_trading/`.

## Two locks, both needed for a real order

1. `python scripts\live_switch.py arm`: you type `I ACCEPT REAL MONEY RISK`.
   Valid **for today only**; it is OFF again tomorrow.
2. Start the day with `python scripts\run_paper_session.py --live-orders`.

Without both, every order is a **DRY RUN**: listed per index in
`data\live_trading\<INDEX>\live_orders.csv` and `orders_log.csv` as `WOULD_PLACE`, never sent.
The switch (`data\live_trading\live_switch.json`) covers all indexes.
`--live-orders` without the switch refuses to start.

## What happens to each paper trade (mirror mode)

| Paper engine | Broker order |
|---|---|
| Opens a trade (BUY CE / BUY PE) | LIMIT BUY at fresh option price + 1.00, re-priced up to 3 times (every 2 s) but never above first price + 3.00. Not filled: rest cancelled. |
| Exits (stop, target, trailing, 15:10) | LIMIT SELL at fresh price - 2.00, re-priced up to 3 times. Not filled: **order left working + ALERT**. |

- **Never a market order**, not even as a fallback (tested: a test fails if any request is not type 1).
- A sell is never bigger than what was really bought. Entry not filled = exit skipped.
- Prices snap to the 0.05 tick: buys round up, sells round down.
- Safety caps: max 10 lots per order, 40 orders a day; FYERS calls paced well under 10/second.
- FYERS "201 not acknowledged" is never re-sent automatically: check the FYERS order book.
- Settings: `LiveOrderPolicy` in `live_trading/orders.py` (buffer in points, ticks or percent).

## Owner's live rules for KTMI (27 Oct 2026)

| Rule | Where | Setting |
|---|---|---|
| Strike = ATM or ATM+1, whichever buys MORE lots, never beyond ATM+1 (equal lots: ATM) | `strategies/funds_strike.py`, entry step `paper_trading/pending_entry_orchestrator.py` | dashboard Order window "AUTO", or `paper_settings.py --strike AUTO` |
| 1 NIFTY lot may cost at most Rs 8,000 (Rs 15,000 free -> 2 lots of Rs 115) | same | "Max cost of 1 lot", or `--max-lot-cost 8000` |
| Lots by the money we have: live = the REAL FYERS "Available Balance" (`live_trading/funds.py`, asked at most every 15 s; unknown = no entry) x the "money per trade" % (set 100% to use all of it) | `paper_trading/session.py` `funds_provider` | dashboard money-per-trade |
| New entries 09:30-15:00, force exit 15:10 | strategy settings (defaults) | `--start 09:30 --end 15:00 --force-exit 15:10` |
| Stop = 30% of the entry price; target 1:2 (whole trade) | trade_management.json | dashboard: Initial stop 30%, "Reward 1:[2]", TSL OFF |
| LIMIT orders with a buffer, never market: BUY at CMP + 1, re-priced up to CMP + 2 at most; SELL (stop, target, 15:10) at CMP - 2, re-priced | `live_trading/orders.py` (`max_entry_chase_points` 1.0) | - |

Each AUTO decision is journaled (`pending_entries.csv`, status STRIKE_CHOSEN, with both prices and lot counts).

## FYERS Smart Script / Automate (checked 27 Oct 2026)

- **Smart Script** (FYERS charts, beta) runs Pine-v6-style `indicator()` scripts: KTMI Uni Lite can be DRAWN there.
  It cannot trade: `strategy()` scripts are refused and script alerts are "not yet sent as notifications".
- **Automate** places orders (options ATM/ITM/OTM, lots, SL / target / trailing), but its indicator triggers are
  built-in ones (RSI, EMA, MACD...), not custom scripts, and it has no "lots by available funds" or
  "ATM or ATM+1 by more lots" rule. A webhook trigger exists (outside signal -> Automate order).
- So the KTMI live rules stay in THIS program (same orders through the FYERS API, every rule above, tested).

## Known limits (honest list)

- Mirror mode: the paper engine decides entries/exits from its own simulated fills;
  real fill prices can differ. Real P&L is what FYERS shows.
- Buffers use the last traded price; bid/ask is not used yet.
- Paper trades restored after a restart are not known to the mirror, so their
  exits are skipped (journaled). Close such positions in FYERS yourself.

## SEBI rules since 1 April 2026 (FYERS notice)

- **Orders are accepted only from an API app mapped to a whitelisted STATIC IP.**
  A normal home or office connection usually has a changing IP: real orders
  would be **rejected by FYERS**. Market data and paper trading are NOT affected.
  To trade live you need a static IP (ask your internet provider), registered in
  your FYERS API app.
- Maximum 10 orders per second; 2FA login once every trading day; market orders
  become MPP orders (we never send market orders anyway).
- Your FYERS API app must have **Order Placement** permission.

Sources: FYERS API v3 docs (single order, modify, cancel, order book, rate limits)
and the FYERS support article on the SEBI retail algo framework.
