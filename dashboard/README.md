# Kunal Quant Dashboard

Streamlit, dark theme, multi-page. Read-only — no order placement exists
anywhere in this dashboard, on purpose (see below).

## Run it

```
cd dashboard
pip install -r requirements.txt
streamlit run app.py
```

## Structure

```
dashboard/
├── app.py              # landing page: phase status, strategy registry
├── theme.py             # dark theme CSS, demo/real data banner helpers
├── data/source.py       # THE ONLY file pages import data from
└── pages/                # Streamlit auto-discovers these as nav entries
    ├── 1_Market_Overview.py
    ├── 2_Options_Chain.py
    ├── 3_Signals_and_Strategy.py
    ├── 4_Positions_and_Risk.py
    └── 5_Backtest_Summary.py
```

Pages never touch the database or FYERS directly — everything goes
through `data/source.py`. That's the only file that needs to change to
go from demo to real: each function's body gets replaced with a real
call, the function signature stays the same, and no page needs editing.

## Demo data vs real data

Most of this dashboard shows **DEMO DATA** — clearly banner'd on every
page, generated with a fixed random seed so it looks stable while being
built, not just labeled in a code comment. Two things are already real,
not demo:

- The **strategy registry** (locked/experimental status) — matches the
  project brief's actual section-42 status.
- The **Backtest Summary** page — pulled from the real 2026-09-24
  checkpoint (2,500 bars, 300 events, 84 completed, 198 unresolved, 16
  no-entry-candle), explicitly marked as not a performance conclusion.

## Why there's no order-placement UI

Per the project brief: live trading must be disabled by default, and
paper/live infrastructure comes *after* backtest validation, not before.
`api/fyers_client.py` in the canonical repo already has full read-only
broker connectivity (quotes, history, positions, funds, depth,
WebSocket) — that part of "connect to the broker" is done. Order
placement is the one piece that's genuinely missing, and it's missing on
purpose. This dashboard's Positions & Risk page is scoped to paper
positions for exactly that reason.

## Verified

Every page passes Streamlit's own `AppTest` framework with 0 exceptions
(`python3 -m streamlit.testing`-style check — see the session
checkpoint). That confirms the UI runs; it says nothing about whether the
demo numbers resemble anything real, because they're demo numbers.


## First-version platform UI prototype

To preview the UI based on the original Kunal Quant HTML prototype, run this as a separate app:

```
cd dashboard
streamlit run prototype_app.py
```

This is a visual/demo prototype with sample market candles, sample positions and sample P&L. It does not connect to FYERS, Dhan, any AI provider, or any order-placement API. Deploy/Edit and credential-save actions are intentionally disabled. The original validated `app.py` dashboard is preserved; use `streamlit run app.py` to return to it.

The Streamlit version follows the original prototype's sections and styling, but it is not yet a pixel-perfect conversion of the supplied HTML. Treat the HTML file as the design source of truth while we refine layout and then wire components to the approved data-source layer.
