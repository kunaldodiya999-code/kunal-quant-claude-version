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
