# Time Machine (odds of a trade, off the chart)

Built 25 Oct 2026 at the owner's request, after checking the MIT "day-trader-skill" (US only; its Time Machine idea
was rebuilt here for NSE, our data and our exit plans). Information only: it never places, picks or skips a trade.

## What it does

For one trade (side, entry, stop and the strategy's exit plan) it replays the rest of the day 1,000-2,000 times.
Each 5-minute candle of a replay is taken from the same stock's own 5-minute candles at the same time of day
(+- 2 candles) over its last ~60 sessions, as a move from the previous close, chained from the entry. Each replay
runs through the same trade engine as the strategies (hard stop, Reward 1:[box] or the TSL, flat by 15:10).

## Where you see it (no lines on the chart)

- **Gap Reversal** page, Today tab: column **time machine** in the paper trades (e.g. `win 45% · target 28%`),
  and a closed box **"Time Machine: chance of reaching each target before 15:10"** under the tables.
- **Open High Low** page, Today tab: the same column for the shortlisted stocks (worked out at the 09:20 scan, entry
  at the first candle's high / low) and the same closed box.
- The programs' windows print it next to each trade (`time machine win 45% · target 28%`).
- Any idea, any time: `python scripts\time_machine.py --symbol RELIANCE --side LONG --entry 1190 --stop 1180`
  (FYERS login first; `--tsl PSAR_0.04_0.04_0.10` for a TSL plan; `--source cache --day 2026-10-23 --at 10:00` for
  a past day from the research data). The live programs fetch 90 days of 5-minute candles per symbol once a day;
  `--no-odds` turns it off.

## Is it right? (the honest check)

`python scripts\time_machine_check.py` gives each past backtest trade the odds it would have had at its entry
(only earlier data) and compares with what happened. Result, 25 Oct 2026, 360 Gap Reversal + Open High Low trades
per exit plan (Yahoo 5-minute data):

| | predicted | real |
|---|---|---|
| Win chance, all trades (1:2) | 41% | 49% |
| Trades it called "GOOD" (1:2) | 57% | **37%** (net -2,471) |
| Trades it called "COIN FLIP" (1:2) | 42% | 50% (net +16,478) |
| Reach 1:1.5 / 1:2 / 1:3 before 15:10 | 29% / 20% / 10% | 41% / 29% / 16% |

- The **target chances rank correctly** (a higher predicted chance really hit more often) but are **cautious**: the
  real rate was 6-15 points higher. Use them to choose a realistic reward for the day (e.g. 1:3 at 4% = unlikely).
- The **win chance did not pick winners**: trades it liked most did worst. It knows the stock's usual movement, not
  your setup. So it is NOT a filter. Re-run the check on longer FYERS history before ever using it as one.
