# HFT Gap-Open Strategy V1

Status: **Experimental / research-only**  
Default: **DISABLED**

## Current underlying decision

The current research build uses the **actual historical NIFTY futures contract**
as the HFT underlying price path. This is an explicit data-source choice because
the tested FYERS historical NIFTY spot-index route returned no seconds data.

This does **not** claim that futures and spot are identical. A future legitimate
spot-seconds source can be added as a separately switchable source without
changing the strategy rules.

## Rules

1. Calculate the opening gap using the configured HFT underlying. Current build:
   NIFTY futures previous close versus NIFTY futures open.
2. Gap up >= 50 points activates CALLs; gap down <= -50 activates PUTs.
3. Current weekly NIFTY expiry only.
4. Approved ladder: ATM, ATM+50, ATM+100, ATM+150, ATM+200, ATM+250.
5. After the first complete 10-second **underlying** candle, require **Open == Low**.
6. The next 10-second underlying candle must break the setup candle high.
7. Enter the selected option with an aggressive configurable limit order, not a market order.
8. Initial SL uses the setup candle low when risk is within the cap; otherwise risk
   is capped at the configurable default of 20 points from entry.
9. Position sizing defaults to ₹10,000 capital per lot and 4 lots. Both are configurable.
   Actual historical lot size comes from instrument metadata.
10. Optional targets remain 2R, 3R and 4R.
11. Manual point-based trailing is independently configurable.
12. HFT strategy remains disabled by default.

## Execution model

A limit order is not assumed filled merely because a signal occurs. The backtest
must verify that future market data actually traded through the requested limit.
Execution/slippage assumptions remain configurable.

## Data model

FYERS historical F&O data is fetched at **5S** and locally aggregated into **10S**
candles. The targeted universe remains 6 CE + 6 PE options plus the actual NIFTY
futures contract. The NIFTY spot row may remain as reference metadata but is not
required for the HFT seconds-price path.

## Isolation

Do not modify locked KTMI, Strategy A/B, Option Trade Management V1, Option Contract
Resolver V2, lifecycle, accounting, or analytics modules.
