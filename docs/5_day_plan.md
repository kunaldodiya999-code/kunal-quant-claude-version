# 5-Day Plan

Requested: project "up and running" in 5 days, including a dashboard and
broker connectivity. This plan takes that timeline seriously while
keeping the sequencing the project brief itself specifies (section 43)
and its live-trading gating (section 60) — see the note in today's chat
response for why those aren't optional.

## Day 1 (today) — done

- Dashboard scaffolded: 5 pages, dark theme, demo-data banners,
  verified with Streamlit's AppTest (0 exceptions across every page).
- Data access layer (`dashboard/data/source.py`) built so real data can
  replace demo data later without touching any page.

## Day 2 (needs you: run the diagnostics on your machine)

- Classify the real 198 unresolved + 16 no-entry-candle events.
- Feed real classification counts into the Signals & Strategy and
  Backtest Summary pages, replacing demo numbers on those two specifically.
- Everything else on the dashboard stays demo for now.

## Day 3

- Depending on what the classification shows: close remaining option
  coverage gaps, or move to running the full historical backtest (not
  just the 2,500-bar sample).
- Wire Market Overview and Options Chain pages to real, read-only FYERS
  data via the existing `api/fyers_client.py` — quotes/history/depth,
  nothing that places an order.

## Day 4

- Validate trade-level backtest results; upgrade the economic execution
  model (real brokerage/STT/GST/slippage) per section 36.
- Start the paper execution adapter (section 30) — same strategy + risk
  engine, simulated fills, no broker order sent.

## Day 5

- Wire Positions & Risk to real paper positions.
- Review pass on everything built this week.
- **Live trading is explicitly out of scope for day 5.** It's gated
  behind its own checklist (section 32) and an explicit go/no-go from
  you once backtest + paper are both validated — not a timeline item.

## What "up and running" realistically means after 5 days

A working dashboard showing real market data, real options chain data,
a validated (not just sample) backtest, and a running paper-trading
loop. Not: a system placing real orders. That's a deliberate, separate
milestone — rushing it is the one part of this plan that would actually
put capital at risk.
