"""
Kunal Quant Dashboard — Data Source Layer

Single point of contact between the dashboard UI and actual data. Right
now every function returns clearly-labeled DEMO data, generated
deterministically (seeded) so the UI is stable to look at while being
built. Nothing here touches the real database or the FYERS API yet.

To go live: each function's body gets replaced with a real call --
`market_overview()` would call `api.fyers_client.FyersClient.quotes()`,
`options_chain()` would query the `instruments`/`candles`/`option_analytics`
tables, etc. The function signatures are designed so that swap doesn't
require touching any page code -- pages only ever import from here.

IS_DEMO_DATA is exported so every page can render a visible "DEMO DATA"
banner. That flag is the actual safety mechanism, not a comment: nobody
should be able to look at this dashboard and mistake demo numbers for a
real position, a real P&L, or a real signal.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

IS_DEMO_DATA = True

_RNG = random.Random(42)  # fixed seed -> stable demo numbers across reruns


# ---------------------------------------------------------------------
# MARKET OVERVIEW
# ---------------------------------------------------------------------


@dataclass
class IndexQuote:
    symbol: str
    ltp: float
    change: float
    change_pct: float


def market_overview() -> list[IndexQuote]:
    base = {"NIFTY 50": 25150.0, "BANK NIFTY": 55200.0, "SENSEX": 82300.0, "INDIA VIX": 13.4}
    quotes = []
    for symbol, price in base.items():
        change_pct = _RNG.uniform(-1.2, 1.2)
        change = price * change_pct / 100
        quotes.append(IndexQuote(symbol, round(price + change, 2), round(change, 2), round(change_pct, 2)))
    return quotes


def intraday_series(symbol: str, points: int = 75) -> list[tuple[datetime, float]]:
    now = datetime.now(timezone.utc)
    start_price = 25150.0 if "NIFTY" in symbol.upper() and "BANK" not in symbol.upper() else 55200.0
    price = start_price
    series = []
    for i in range(points):
        price += _RNG.uniform(-8, 8)
        ts = now - timedelta(minutes=(points - i) * 3)
        series.append((ts, round(price, 2)))
    return series


# ---------------------------------------------------------------------
# OPTIONS CHAIN
# ---------------------------------------------------------------------


@dataclass
class OptionRow:
    strike: int
    ce_ltp: float
    ce_oi: int
    ce_iv: float
    pe_ltp: float
    pe_oi: int
    pe_iv: float


def options_chain(underlying_price: float = 25150.0, strike_step: int = 50, width: int = 8) -> list[OptionRow]:
    atm = round(underlying_price / strike_step) * strike_step
    rows = []
    for i in range(-width, width + 1):
        strike = atm + i * strike_step
        moneyness = abs(strike - underlying_price)
        base_iv = 12.5 + moneyness / 400
        rows.append(
            OptionRow(
                strike=strike,
                ce_ltp=round(max(underlying_price - strike, 0) + _RNG.uniform(15, 60), 2),
                ce_oi=int(_RNG.uniform(50_000, 900_000)),
                ce_iv=round(base_iv + _RNG.uniform(-0.5, 0.5), 2),
                pe_ltp=round(max(strike - underlying_price, 0) + _RNG.uniform(15, 60), 2),
                pe_oi=int(_RNG.uniform(50_000, 900_000)),
                pe_iv=round(base_iv + _RNG.uniform(-0.5, 0.5), 2),
            )
        )
    return rows


def pcr_and_gex() -> dict:
    return {"pcr_oi": round(_RNG.uniform(0.8, 1.3), 2), "net_gex": round(_RNG.uniform(-2.5, 2.5), 2)}


# ---------------------------------------------------------------------
# KTMI SIGNALS / STRATEGY STATUS
# ---------------------------------------------------------------------


@dataclass
class StrategyStatus:
    name: str
    state: str  # LOCKED / IN PROGRESS / EXPERIMENTAL
    enabled: bool
    note: str


def strategy_registry() -> list[StrategyStatus]:
    # These reflect the actual section-42 status from the 2026-09-24
    # checkpoint, not demo numbers -- this list is real, everything below
    # it (the event feed) is demo.
    return [
        StrategyStatus("KTMI Strategy A/B (options)", "LOCKED", True, "Core locked strategy; math unchanged"),
        StrategyStatus("Inside Bar", "EXPERIMENTAL", False, "Earlier research component"),
        StrategyStatus("5-Minute Breakout", "EXPERIMENTAL", False, "Earlier research component"),
        StrategyStatus("Triple Momentum (RMI)", "EXPERIMENTAL", False, "Independent indicator, not a strategy"),
        StrategyStatus("Liquidity Sweep / SMC filter", "EXPERIMENTAL", False, "Research filter only"),
        StrategyStatus("IV Percentile filter", "EXPERIMENTAL", False, "Research filter only"),
        StrategyStatus("GEX regime filter", "EXPERIMENTAL", False, "Research filter only"),
    ]


@dataclass
class SignalEvent:
    timestamp: datetime
    direction: str
    price: float
    classification: str  # RESOLVED_WITH_CANDLE / NO_OPTION_DATA / DATA_GAP / EXPIRY_NOT_FOUND / CONTRACT_NOT_FOUND


def recent_signal_events(n: int = 12) -> list[SignalEvent]:
    classes = [
        "RESOLVED_WITH_CANDLE", "RESOLVED_WITH_CANDLE", "RESOLVED_WITH_CANDLE",
        "NO_OPTION_DATA", "DATA_GAP", "EXPIRY_NOT_FOUND", "CONTRACT_NOT_FOUND",
    ]
    now = datetime.now(timezone.utc)
    events = []
    for i in range(n):
        events.append(
            SignalEvent(
                timestamp=now - timedelta(minutes=i * 17),
                direction=_RNG.choice(["LONG", "SHORT"]),
                price=round(25150 + _RNG.uniform(-120, 120), 2),
                classification=_RNG.choice(classes),
            )
        )
    return events


# ---------------------------------------------------------------------
# POSITIONS / RISK / P&L  (paper only -- no live mode exists yet)
# ---------------------------------------------------------------------


@dataclass
class PaperPosition:
    symbol: str
    direction: str
    qty: int
    entry_price: float
    ltp: float
    unrealized_pnl: float


def paper_positions() -> list[PaperPosition]:
    return [
        PaperPosition("NIFTY 25150 CE", "LONG", 75, 118.5, 132.0, round((132.0 - 118.5) * 75, 2)),
        PaperPosition("NIFTY 25050 PE", "SHORT", 75, 96.0, 88.5, round((96.0 - 88.5) * 75, 2)),
    ]


@dataclass
class RiskSnapshot:
    starting_capital: float
    capital_deployed: float
    daily_pnl: float
    daily_loss_limit: float
    max_positions: int
    open_positions: int
    kill_switch_armed: bool


def risk_snapshot() -> RiskSnapshot:
    return RiskSnapshot(
        starting_capital=500_000.0,
        capital_deployed=30_000.0,
        daily_pnl=round(sum(p.unrealized_pnl for p in paper_positions()), 2),
        daily_loss_limit=15_000.0,
        max_positions=5,
        open_positions=len(paper_positions()),
        kill_switch_armed=True,
    )


# ---------------------------------------------------------------------
# BACKTEST SUMMARY (from the real 2026-09-24 checkpoint, not demo)
# ---------------------------------------------------------------------


@dataclass
class BacktestSummary:
    as_of: str
    sample_bars: int
    ktmi_events: int
    completed_trades: int
    open_trades: int
    unresolved: int
    no_entry_candle: int
    gross_pnl: float
    is_conclusive: bool
    note: str


def latest_backtest_summary() -> BacktestSummary:
    return BacktestSummary(
        as_of="2026-09-24",
        sample_bars=2500,
        ktmi_events=300,
        completed_trades=84,
        open_trades=2,
        unresolved=198,
        no_entry_candle=16,
        gross_pnl=-3534.70,
        is_conclusive=False,
        note=(
            "From the real checkpoint, not demo data. Explicitly NOT a "
            "performance conclusion -- 198 unresolved + 16 no-entry-candle "
            "events out of 300 haven't been classified yet."
        ),
    )
