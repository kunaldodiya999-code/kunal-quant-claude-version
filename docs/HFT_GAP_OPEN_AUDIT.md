# HFT Gap-Open V1: audit against the requirements brief (25 Oct 2026)

Compared: `research/hft_gap_open_v1.py`, `config/hft_strategy.py`, `config/hft_data.py`,
`scripts/build_hft_10s_manifest.py` against "KunalQuant HFT Gap-Open & TSL Requirements"
(PDF of 24 Oct 2026, same content as the shared ChatGPT conversation).
The strategy stays **research-only and disabled by default**. Nothing here places orders.

| Brief requirement | Before this audit | Now |
|---|---|---|
| "HFT" = 10-second candles, not microsecond trading | 5-second FYERS history joined into 10 s (data layer) | unchanged, matches |
| Disabled by default, research only | `HFT_GAP_OPEN_ENABLED_DEFAULT = False` | unchanged, matches |
| Gap from NIFTY **futures** previous close vs open (spot has no seconds data) | `HFT_UNDERLYING_MODE = "NIFTY_FUTURES"` | unchanged, matches |
| Gap >= +50 -> CALL, <= -50 -> PUT, else nothing | implemented | unchanged, matches (threshold now a setting) |
| Current weekly expiry | `CURRENT_WEEKLY_ONLY = True` | unchanged |
| Setup: first 10 s candle Open = Low, next candle breaks its high | implemented for CALL **and wrongly also for PUT** | CALL unchanged; **PUT mirrored**: Open = High, next candle breaks its LOW (owner decision 25 Oct) |
| Initial stop = setup low, capped at 20 points | long-only formula used for both sides | CALL: setup low; **PUT: setup high**, each capped at 20 points |
| Targets 2R / 3R / 4R | only a constant, never used | `target_prices()`: entry +/- R x risk in the trade's direction; switchable |
| Entry limit +2, exit limit +2 points | entry offset used; **exit offset unused** | entry: +2 above the break (CALL) / -2 below it (PUT); exit: `exit_limit_price()` = option price - 2 (selling the bought option; never a market order) |
| Fill only if price trades through the limit | CALL only | both sides |
| Manual point trail: buffer 10, minimum lock 15 | long-only | CALL and mirrored PUT (`trailing_stop_price(..., side)`) |
| Ladder: ATM, +50 ... +250 for CE and PE (12 contracts) | +50 ... +250 for both (PE strikes in the money) | CE: ATM ... ATM+250; **PE: ATM ... ATM-250** (both out of the money, owner decision 25 Oct) |
| 10,000 per lot x 4 lots, lot size from contract metadata | implemented | unchanged |
| Nothing hard-coded | module constants | `HftGapOpenConfig` holds every number (defaults from `config/hft_strategy.py`) |

Tests: `tests/test_hft_gap_open_v1.py` (original CALL tests unchanged and passing, plus PUT mirror,
targets, trail, exit limit, ladder, configurable values).

## Still open (needs data, not code)

* No validated end-to-end backtest yet: bulk 10-second history has not been collected
  (the 28 Sep 2026 checkpoint proved the API routes only). The data sweep collects the last
  10 days of NIFTY futures 5-second candles each run (`scripts/sweep_market_data.py --source fyers`).
* Realistic fills: costs, slippage, latency and unfilled limits must be modelled in that backtest.
* Validation thresholds before ever enabling it: to be decided by the owner after the backtest.
