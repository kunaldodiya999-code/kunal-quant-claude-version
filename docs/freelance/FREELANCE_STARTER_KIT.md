# Freelance Starter Kit - Kunal (TradingView & broker automation builder)

Made 12 Nov 2026. Everything here is ready to copy-paste. Change only the parts in [brackets].

---

## 1. What you sell (your one-line position)

**"I build custom TradingView indicators, backtests and broker automation (FYERS, Zerodha, Dhan) for traders."**

Why you: you trade, you read charts, and you have already built working tools (KTMI Cross over, BB Reversal R:R,
Position Sizer, and a full FYERS trading terminal with backtests and a kill switch). You understand what a trader
actually needs - most developers do not.

The one rule you never break (SEBI): **you build tools, you never give trade calls.** No "buy this", no tips, no
"this indicator makes 80% profit". Every delivery says: "This is a software tool. It is not investment advice."

---

## 2. Fiverr

### Gig 1 (start with this one)

**Title (max 80 characters):**
I will code a custom TradingView Pine Script indicator or strategy with alerts

**Category:** Programming & Tech > Software Development (or the "Trading" / "Pine Script" sub-category if offered)

**Search tags (5):** pine script, tradingview, tradingview indicator, trading strategy, tradingview alerts

**Packages (launch prices - raise them after 5 good reviews):**

| | BASIC | STANDARD | PREMIUM |
|---|---|---|---|
| Name | Simple indicator | Advanced indicator | Strategy + backtest |
| What | 1 idea, settings, alerts | several conditions, settings, alerts, signal arrows, info table | full `strategy()` with entries, stop, target, breakeven, backtest report - or a conversion from MT4 / another script |
| Delivery | 2 days | 3 days | 5 days |
| Revisions | 1 | 2 | 3 |
| Launch price | $30 | $70 | $140 |
| Price after 5 reviews | $60 | $150 | $300 |

(Fiverr keeps about 20% of each order. Market prices for this work are roughly $75-300 for a simple indicator and
$300-800 for a complex one - you start lower only to collect reviews.)

**Gig description (copy-paste):**

> Need a TradingView indicator or strategy built exactly the way you trade? I am a trader and a Pine Script builder, so
> I understand what you mean by "candle closes outside the band", "move the stop to breakeven at 1:1" or "only
> signals above the zero line" - you do not have to explain trading to me.
>
> **What I build**
> - Custom indicators (Pine Script v6) with clean settings - nothing hard-coded
> - Buy / sell arrows, risk-to-reward boxes, results tables
> - Alerts that fire on candle close (no repainting surprises)
> - Strategies with stop loss, target, breakeven and a backtest report
> - Conversions: MT4 / MT5 / another TradingView script / FYERS Smart Script
> - Fixes and changes to your existing script
>
> **How we work**
> 1. You describe the rules (a screenshot with marks helps a lot).
> 2. I confirm the rules back to you in plain words before coding.
> 3. You get the full source code, a short user guide and the settings explained.
>
> Every script is tested on real charts before delivery.
>
> Note: I build software tools. I do not give trading advice or buy/sell calls.

**FAQ (add these 4):**
- *Will I get the source code?* Yes, the full Pine Script code is yours.
- *Do your indicators repaint?* Signals are taken on the closed candle, so they do not change after the candle closes.
- *Can you make it work on my timeframe/market?* Yes - stocks, indices, options, crypto, forex, any timeframe.
- *Do you guarantee profits?* No. Nobody honest can. I guarantee the tool does exactly what your rules say.

**Requirements (questions the buyer must answer):**
1. Describe your rules step by step (entry, exit, stop, target).
2. Which timeframe and which symbols do you use?
3. Any screenshot of a chart with the signals marked? (optional but very helpful)
4. Do you need alerts? Arrows? Boxes? A results table?

### Gig 2 (add after the first 3-5 reviews)

**Title:** I will connect TradingView alerts to FYERS, Zerodha or Dhan for automated limit orders

**Short description:**
> Your TradingView alert places a real order at your broker - limit orders with a price buffer, stop loss, target,
> daily loss limit and a kill switch. Runs on your own PC with your own API keys (they never leave your computer).
> Includes paper-trading mode to test safely first. Note: Indian brokers need a whitelisted static IP for API orders
> (SEBI rule) - I guide you through it.

Packages: $100 / $220 / $450 (paper mode only / live with 1 instrument / multi-index with dashboard).

---

## 3. Upwork profile

**Title:**
TradingView Pine Script Developer | Trading Automation | FYERS, Zerodha, Dhan APIs

**Hourly rate:** start at **$20/hour**, move to $30 after 3 good reviews, $40+ after 10.

**Overview (copy-paste):**

> I build trading tools for traders - and I am a trader myself, so you will not have to explain what a "breakout on
> candle close" or "stop to breakeven at 1R" means.
>
> What I do:
> - Custom TradingView indicators and strategies (Pine Script v6): signals, alerts, risk/reward boxes, results tables
> - Backtests with real costs (slippage, brokerage, taxes) and clear reports
> - Conversions from MT4/MT5 or other scripts to TradingView
> - Broker automation for Indian markets: TradingView or your own signals -> FYERS / Zerodha / Dhan API, limit orders
>   only, stop loss, daily loss limit, kill switch, paper-trading mode first
> - Dashboards to watch your trades live
>
> Recent work:
> - A Bollinger Band reversal indicator with 5 selectable setups, risk/reward boxes, breakeven logic and a results table
> - A momentum cross-over indicator with an adjustable signal filter
> - A position-size calculator (capital limit + risk limit, whole lots)
> - A full trading terminal for FYERS: live option chain, charts, automated strategy, backtests on real option prices,
>   drag-to-modify stop orders and a one-click kill switch
>
> How I work: I write your rules back to you in plain words before I code, so we agree first. You get full source code,
> a short guide, and fixes if anything does not match your rules.
>
> I build software. I do not give trading advice.

**Skills to add:** Pine Script, TradingView, Python, Algorithmic Trading, Trading Automation, API Integration,
Backtesting, Technical Analysis, Data Visualization, Streamlit

**Portfolio (3 items, each with 2-3 screenshots + 3 lines of text):**
1. BB Reversal R:R indicator (screenshot of boxes + table on a chart)
2. Position Sizer (screenshot of the lines + table)
3. FYERS Trading Terminal (screenshots of the terminal, backtest report, risk desk)
   - Show screenshots only. Never share your FYERS keys, token or code with private strategy rules.

---

## 4. Five proposal templates (Upwork)

Rules: answer within the first hour of a job being posted, keep it short, start with THEIR problem, end with ONE
question. Send 3-5 good proposals a day, not 30 bad ones.

### A. New custom indicator
> Hi [name], I read your rules: [repeat their rule in one line, e.g. "arrow when the candle closes outside the upper
> Bollinger band and RSI is above 70"]. I am a trader and a Pine Script builder, so I can build this exactly, with
> settings for every number, alerts on candle close, and [extra they would like, e.g. a results table].
> I recently built a similar Bollinger reversal indicator with risk/reward boxes and breakeven logic - happy to show
> a screenshot.
> One question before I start: [e.g. "should the signal wait for the candle to close, or fire during the candle?"]
> Delivery: [2-3] days. - Kunal

### B. Conversion (MT4/MT5/other platform -> TradingView)
> Hi [name], I can convert your [MT4 indicator name] to TradingView Pine Script v6 and check it candle by candle
> against the original so the values match. You get the full code and a short note on any differences between the
> platforms (for example how each one calculates [EMA/ATR]).
> Could you share the source file (.mq4) or, if you only have the compiled file, screenshots with values?
> Delivery: [3] days. - Kunal

### C. Fix or change an existing script
> Hi [name], I can fix this. From your description the problem looks like [e.g. "the signal repaints because it uses
> the live candle"] - I will confirm once I see the code. You will get the corrected script plus a one-line
> explanation of every change.
> Can you share the script and one screenshot where it goes wrong?
> Usually done within [24 hours]. - Kunal

### D. Alert -> broker automation (India)
> Hi [name], I have built this for FYERS myself: TradingView/our own signals -> limit orders with a buffer (never
> market), stop loss at the exchange, daily loss limit, kill switch, and a paper-trading mode to test first. It runs
> on your PC with your own API keys.
> Important: Indian brokers now require a whitelisted static IP for API orders - do you already have one?
> Which broker do you use ([FYERS/Zerodha/Dhan]) and which instruments? - Kunal

### E. Backtest a strategy
> Hi [name], I can backtest [their strategy] on [market/timeframe] with realistic costs (slippage, brokerage, taxes)
> and give you a clear report: win rate, profit factor, drawdown, equity curve, results by day and by hour, and every
> trade listed. I trade myself, so I will flag anything that looks too good to be true.
> How many months of data would you like, and do you trade the [index/stock] itself or options on it? - Kunal

---

## 5. Publishing your 3 scripts on TradingView (your shop window)

TradingView's House Rules for scripts, in short: original work, a clear English description of what it does and how
to use it, a clean chart that shows only your script, no links, no advertising, no contact details, no profit
promises. Breaking them gets the script hidden - read the rules on TradingView once before you publish.

**How to publish:** open the script in the Pine Editor -> Add to chart -> clean the chart (remove other indicators) ->
"Publish script" -> choose visibility -> paste the title and description below -> Publish.

### Script 1: BB Reversal R:R - publish OPEN-SOURCE
**Title:** BB Reversal R:R - Bollinger band reversal setups with risk/reward boxes and breakeven

**Description:**
> This indicator marks Bollinger Band reversal setups and draws the full trade plan for each one: entry, stop,
> target, and a breakeven move.
>
> How it works
> - Bollinger Bands with adjustable length, multiplier, source and average type (defaults 20 and 2).
> - Five setups you can tick on or off: (1) candle opens and closes outside the band, (2) candle closes outside,
>   (3) the previous candle closed outside and this one closes back inside, (4) wick outside but close inside,
>   (5) the whole candle (open, high, low and close) outside the band.
> - Upper band = short setup, lower band = long setup (mirror image).
> - Entry at the close of the signal candle. Stop at the candle's high (short) or low (long), with an optional buffer.
> - Target at an adjustable R multiple (default 1:2). Optional move of the stop to breakeven once price reaches 1R.
> - One trade at a time. Green box = reward zone, red box = risk zone. A table shows trades, targets, stops,
>   breakevens, win rate and net R.
>
> Notes: signals are taken on closed candles. If the stop and the target are touched inside the same candle, the
> default assumes the stop (you can change this). This is an educational/analysis tool, not trading advice.

### Script 2: Position Sizer - publish OPEN-SOURCE
**Title:** Position Sizer: capital + risk limit, whole lots, R:R target

**Description:**
> How many lots should a trade be? This tool answers with two limits and takes the smaller one, in whole lots:
> - Capital limit: capital x allocation % / (entry x lot size)
> - Risk limit: max risk / (distance to stop x lot size)
>
> Click your entry and stop on the chart when you add it (drag them any time). The target follows your R:R. A table
> shows lots, quantity, which limit decided the size, money used, rupee risk and reward. "Strict" mode adds the
> limit-order buffer to both sides so the real loss stays inside your cap.
> Works for options (entry = premium), futures and shares (lot size 1). It only calculates; it places no orders.

### Script 3: KTMI Cross over - DO NOT publish the code openly
KTMI is your own strategy indicator - your edge. Options, safest first:
1. **Keep it private** (recommended for now) and only show screenshots in your portfolio.
2. Later, publish it as **protected** (people can use it, the code stays hidden) or **invite-only** (you choose who
   can use it - this is how indicator sellers charge a monthly fee). Check your TradingView plan for which options
   it allows.

Use these instead as script 3 for now: any small free utility a client asks for often (for example a "previous day
high/low + opening range" indicator). I can build it for you.

---

## 6. Your weekly routine (2-3 hours on weekdays, 6 on weekends)

| When | What |
|---|---|
| Every weekday morning (30 min) | Upwork: read new jobs for "pine script", "tradingview", "trading bot", "algo"; send 1-2 proposals |
| Every weekday evening (1-2 h) | Deliver work; improve one portfolio piece |
| Saturday (3 h) | Build or improve one public script / sample; write one helpful answer in a trading community |
| Sunday (3 h) | Review the week: proposals sent, replies, orders, money earned; plan next week |

Track it in one simple sheet: date - platform - job - proposal sent? - reply? - won? - amount.

**Targets:** month 1 = profiles live + 3 published scripts + 40 proposals; month 2 = first 3-5 orders (reviews);
month 3 = Rs 30-60k; then raise prices.

---

## 7. Money basics
- Fiverr/Upwork pay in USD; withdraw to your Indian bank (directly or via Payoneer). Keep every invoice.
- Freelance income is taxable. Once it becomes regular, talk to a CA once (they will also tell you about GST for
  export of services).
- 50% of every rupee earned goes to the loans (highest interest first) until they are gone.
- Keep the job until freelance income equals your salary for 3-6 months in a row.
