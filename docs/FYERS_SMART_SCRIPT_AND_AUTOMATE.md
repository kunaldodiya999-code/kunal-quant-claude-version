# KTMI Uni Lite on FYERS: Smart Script (chart) and Automate (orders)

Checked 27 Oct 2026 against FYERS' own pages (sources at the end). FYERS changes these features often: if a
screen looks different, the idea is the same.

## What FYERS can and cannot do with KTMI

| Want | FYERS today | How |
|---|---|---|
| See KTMI on a FYERS chart | **Yes** | Smart Script (Part A) |
| Automate trades on the KTMI arrows | **Yes, through a webhook** | Automate cannot read Smart Script indicators, and its 20 built-in indicators do not include TRIX (KTMI's core). The KTMI arrow must come from OUTSIDE: a TradingView alert (Part B) or our program. Smart Script alerts are "not yet sent as notifications". |
| Backtest KTMI in Automate | **No** | Automate backtests its own triggers; it has no history of outside (webhook) signals. Keep using `scripts\report_card.py`. |
| Buy ATM option, SL, target, square off 15:10, time window | Yes | Automate "Place options order with SL & Tgt", schedule window, "Wait till time" + "Square off" |
| ATM **or ATM+1, whichever buys more lots**, Rs 8,000 max per lot, lots from available funds | **No** | Automate takes a FIXED number of lots and one strike rule. Our program does this (docs/LIVE_ORDERS.md). |
| Limit order with a buffer (CMP + 1 / + 2) | Unclear | Not in FYERS' public pages; check the order-type box in the Place order node. |
| Static IP | Reported not needed for Automate (a community answer, not official: confirm with FYERS) | Our program's API orders DO need it. |

## Part A: plot KTMI on a FYERS chart (5 minutes)

1. On your PC open `C:\Users\USER\Desktop\Kunal\kunal-quant-claude-version\indicators\ktmi_uni_lite\KTMI_Uni_Lite_FYERS_SmartScript.pine`
   in VS Code. Press Ctrl+A, then Ctrl+C (copy everything).
2. FYERS Web -> open a NIFTY 50 chart -> **Indicators** -> **Smart Script** -> **Write or Paste a Script**.
3. Click in the editor, Ctrl+A, Delete, then Ctrl+V. Save it with the name **KTMI Uni Lite**.
4. Add it to the chart. Set the chart to **5 minutes** (the report card's best timeframe; 3 also works).
5. Check: three coloured lines in a pane below the price, and small triangles. The trades are the **green triangle
   at the bottom (Long Momentum Buy = BUY CALL)** and the **red triangle at the bottom (Short Momentum Buy = BUY PUT)**.
   Momentum Buy / Sell are OFF (empty boxes), as on your TradingView chart.
6. Compare a few arrows with our dashboard (page Chart) or `python scripts\ktmi_check.py --date 2026-10-27 --timeframe 5`.
   If FYERS refuses the script, it names the missing part in red: send Claude a screenshot.
7. Later it is under **Indicators -> My Smart Scripts**.

**Arrows on the price candles** (owner 27 Oct 2026): the script also draws the two trade signals ON THE PRICE CHART:
green up-triangle BELOW the candle = BUY CALL, red down-triangle ABOVE the candle = BUY PUT (setting "Arrows on the
price chart", on by default). If FYERS shows them in the KTMI pane instead, use the small backup script
`indicators\ktmi_uni_lite\KTMI_Uni_Lite_FYERS_Arrows.pine` (same maths, arrows only, sits on the price chart):
paste it as a second Smart Script named **KTMI Arrows**.

## Part B: KTMI arrow -> FYERS Automate order (TradingView route)

You already have KTMI on TradingView. TradingView sends the alert, FYERS Automate places the order.
Needs a TradingView plan that allows webhook alerts.

**B1. Create the automation in FYERS** (FYERS Web -> Automate -> **Create Automation**). Make TWO automations,
one for calls and one for puts (simplest to check):

| Node | Setting for "KTMI CALL" (the PUT one: CE -> PE) |
|---|---|
| Schedule | Weekdays, market hours, restricted window **09:30 to 15:00** (no new entries after 15:00) |
| Trigger | **Webhook** -> **TradingView Webhook**. Copy the URL it shows. |
| Condition (optional) | Portfolio / Orderbook check: no open position of this automation (one trade at a time) |
| Action | **Place options order with SL & Tgt**: Underlying NIFTY, expiry = current week, strike **ATM** (or OTM1 = ATM+1), option **CE**, lots **1** (or 2: Rs 8,000 a lot means 1 lot per Rs 8,000 of funds), **stop loss 30%**, **target 60%** (= 1:2), order type **Limit** if offered |
| Exit | **Wait** till **15:10** -> **Square off automation positions** |
| Notify | Mail / app alert on entry, SL, target |

Click **Validate**. Start it on a quiet day with 1 lot only.

**B2. Create the alert in TradingView**: open NIFTY (same timeframe as Part A) with KTMI Uni Lite ->
Alert (clock icon) -> Condition **KTMI Uni Lite** -> **Long Momentum Buy** (for PUT: **Short Momentum Buy**) ->
trigger **Once Per Bar Close** (our rule: enter only after the candle closes) -> Notifications: **Webhook URL** =
the URL from B1 -> Message, for example:

```
{"signal": "KTMI BUY CALL", "ticker": "{{ticker}}", "close": "{{close}}", "time": "{{timenow}}", "lots": "1"}
```

FYERS reads the fields as `@Webhook0.output.<name>` inside Automate (community example; lots as a TEXT "1").

**B3. Test first**: with the automation in a test / paper mode if FYERS offers it, or 1 lot, watch the first
signals and compare with our program's paper trades on the same day.

## Part C: what stays in our program

The money rules (ATM or ATM+1 by more lots, Rs 8,000 per lot, lots from the funds you have), limit orders with
a capped buffer, the trailing stops and all backtests (report card) run in `kunal-quant-claude-version`.
If you want FYERS Automate to place the orders but with these rules, our program can send the webhook itself
(no TradingView), with the strike and the lots it chose: ask Claude to build it (OFF by default).

## Sources

- Smart Script reference and FAQ: https://fyers.in/web/smartscript/ , https://fyers.in/web/smartscript/faq.html
- Automate: https://fyers.in/automate
- Indicator-based triggers (indicator list): https://fyers.in/community/t/introducing-indicator-based-triggers-in-automate/12281
- Place order action: https://support.fyers.in/portal/en/kb/articles/how-do-i-use-place-order-action-in-automate
- Automate workflow guide: https://fyers.in/community/t/automate-build-and-execute-rule-based-workflow-on-fyers-web/22929
- TradingView signals into trades (payload example): https://fyers.in/community/t/turn-tradingview-signals-into-trades/24459
- Backtest in Automate: https://fyers.in/community/t/introducing-backtest-in-fyers-automate-available-now/23164
