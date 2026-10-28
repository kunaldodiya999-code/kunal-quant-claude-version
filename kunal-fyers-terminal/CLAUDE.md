# Notes for Claude (read first)

- Owner: Kunal, about 10% coding knowledge, Windows + VS Code + PowerShell. Explain step by step, plain words, always
  give the folder: `C:\Users\USER\Desktop\Kunal\kunal-fyers-terminal` (its own `.venv`).
- Tests: `python -m pytest tests -q` (tests/conftest.py keeps every test in a temporary data folder).
- Strategy = owner's rules 28 Oct 2026, see README and `terminal/strategy.py`: BBP_NM Direction cross above 0 -> CALL,
  below 0 -> PUT, finished candles only, SL = option's signal-candle low, exit on the opposite cross, 09:30-15:00,
  15:10 exit. One strike mode at a time (RANGE cheapest inside / PER_LOT nearest at or below). KTMI = chart only.
- NEVER market orders; limit + buffer (2). Real orders need Settings "Real orders" AND `arm_real_orders.py` (today).
  Bearish = BUY PUT, never sell options.
- `indicators/ktmi_uni_lite/KTMI_Uni_Lite_FINAL.pine` must never change (SHA test). `indicators/ktmi/` calculations
  and `live_trading/` are copies from kunal-quant-claude-version: change them there first.
- FYERS data only. Index has no volume: VWAP uses the nearest FUTURES volume (owner rule).
- Never commit `.env`, `data/`, tokens.
