"""Open High Low (OHOL) confluence strategy for F&O stocks. OFF by default; research + paper only.

Owner's rules (25 Oct 2026):
  LONG  = OPEN = LOW  (price never traded below the open)    SHORT = OPEN = HIGH (never traded above it)
  1. Spot chart OR futures chart shows the condition -> the stock is a candidate (no trade yet).
  2. The other one must show the SAME condition (setting: BOTH by default, or EITHER).
  3. Option chain: 11 strikes (ATM, 5 ITM, 5 OTM) of the nearest expiry, calls AND puts.
       LONG:  calls with open = low  (call premium only went up)   + puts with open = high (put only went down)
       SHORT: calls with open = high                              + puts with open = low
     Score = matching options out of 22.
  4. Liquidity of the F&O stock: futures traded value since the open, ATM option bid-ask spread, option volume.
  5. Everything is scanned when the FIRST candle closes (default 5 minutes: 09:15-09:20, scan at 09:20); the best
     ``top_n`` (5) by option score (then liquidity) are shortlisted.
  6. Entry (owner, 25 Oct): LONG when the NEXT candle (09:20-09:25) crosses above the first candle's HIGH, SHORT when
     it crosses below its LOW (``entry_valid_candles`` = how many candles may give the entry, default 1). Before the
     breakout, a LONG is cancelled if price goes below the open (open = low broken); a SHORT if it goes above.
Trade: instrument = STOCK (intraday, default), FUTURE (1 lot) or OPTION (buy 1 lot ATM CE for LONG, ATM PE for
SHORT: owner rule, bearish = BUY PUT, never sell options). Entry at the first candle's high (low), or at the
minute's open if price jumped past it. Stop = the day's low (LONG) / high (SHORT) at the entry minus / plus a buffer, on the spot (STOCK, OPTION) or futures chart (FUTURE). Exit = the shared exit plan
(strategies/exit_plan.py): Reward 1:[box] or empty = TSL. Flat by 15:10.

"Equal" uses a tolerance (settings): open within 0.05% of the low counts as open = low (stocks); options 0.5%
(premium ticks are coarse).
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, replace
from datetime import date, datetime, time
from pathlib import Path
from typing import Optional, Sequence
from zoneinfo import ZoneInfo

from strategies.exit_plan import NO_TSL, ExitPlan, parse_rr

IST = ZoneInfo("Asia/Kolkata")
SETTINGS_FILE = "settings.json"
INSTRUMENTS = ("STOCK", "FUTURE", "OPTION")
CONFIRM = ("BOTH", "EITHER")
STOCK_OPTION_TYPE = 15            # FYERS exInstType of stock options


@dataclass(frozen=True)
class OHOLSide:
    enabled: bool = True
    sl_buffer_pct: float = 0.2          # stop this % beyond the day's low (LONG) / high (SHORT)
    target_rr: Optional[float] = 2.0    # Reward 1:[box]; None = TSL exit
    tsl_method: str = NO_TSL
    tsl_trigger: str = "CLOSE"
    method_params: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.sl_buffer_pct < 0:
            raise ValueError("sl_buffer_pct must be 0 or more")
        plan = self.exit_plan()
        object.__setattr__(self, "target_rr", plan.target_rr)
        object.__setattr__(self, "method_params", plan.method_params)

    def exit_plan(self) -> ExitPlan:
        return ExitPlan(target_rr=parse_rr(self.target_rr), tsl_method=self.tsl_method, tsl_trigger=self.tsl_trigger,
                        method_params=self.method_params)


@dataclass(frozen=True)
class OpenHighLowSettings:
    enabled: bool = False                 # OFF by default: run it when needed
    first_candle_minutes: int = 5         # the first candle (09:15-09:20); the scan is at its close
    entry_valid_candles: int = 1          # entry only in the next N candles of that size after it (owner: the next one)
    scan_at: str = "09:20"                # = 09:15 + first_candle_minutes (set automatically)
    exit_time: str = "15:10"
    timeframe: int = 5                    # TSL candles
    confirm: str = "BOTH"                 # spot AND futures must agree (EITHER: one is enough)
    tolerance_pct: float = 0.05           # spot / futures: open within this % of the low (high) = equal
    option_tolerance_pct: float = 0.5     # options: the same, on premium
    strikes_each_side: int = 5            # 5 ITM + ATM + 5 OTM = 11 strikes, calls and puts
    min_days_to_expiry: int = 0           # skip an expiry closer than this (0 = nearest expiry, even today)
    min_option_matches: int = 11          # of the 22 options at least this many must agree (50%)
    top_n: int = 5                        # trades per day: the best N candidates
    min_fut_value_cr: float = 5.0         # liquidity: futures traded value since the open, Rs crore
    max_atm_spread_pct: float = 1.0       # liquidity: ATM CE / PE bid-ask spread, % of premium
    min_option_volume: int = 0            # liquidity: total volume of the 22 options (contracts x lot), 0 = off
    instrument: str = "STOCK"
    capital_per_trade: float = 50_000.0   # STOCK: rupees per trade
    lots: int = 1                         # FUTURE / OPTION: lots per trade
    long: OHOLSide = field(default_factory=OHOLSide)
    short: OHOLSide = field(default_factory=OHOLSide)

    def __post_init__(self) -> None:
        if isinstance(self.long, dict):
            object.__setattr__(self, "long", OHOLSide(**self.long))
        if isinstance(self.short, dict):
            object.__setattr__(self, "short", OHOLSide(**self.short))
        if self.first_candle_minutes not in (1, 3, 5, 10, 15, 30) or self.entry_valid_candles < 1:
            raise ValueError("first_candle_minutes must be 1, 3, 5, 10, 15 or 30; entry_valid_candles at least 1")
        minutes = 15 + self.first_candle_minutes
        object.__setattr__(self, "scan_at", f"{9 + minutes // 60:02d}:{minutes % 60:02d}")
        if not time.fromisoformat(self.scan_at) < time.fromisoformat(self.exit_time):
            raise ValueError("the first candle must close before exit_time")
        if self.confirm not in CONFIRM:
            raise ValueError(f"confirm must be one of {CONFIRM}")
        if self.instrument not in INSTRUMENTS:
            raise ValueError(f"instrument must be one of {INSTRUMENTS}")
        if self.timeframe not in (1, 3, 5, 10, 15):
            raise ValueError("timeframe must be 1, 3, 5, 10 or 15")
        if not 1 <= self.strikes_each_side <= 10:
            raise ValueError("strikes_each_side must be 1 to 10")
        if not 0 <= self.min_option_matches <= 2 * (2 * self.strikes_each_side + 1):
            raise ValueError("min_option_matches must be between 0 and the number of options checked")
        if self.top_n < 1 or self.lots < 1 or self.capital_per_trade <= 0:
            raise ValueError("top_n, lots and capital_per_trade must be positive")
        if min(self.tolerance_pct, self.option_tolerance_pct, self.min_fut_value_cr, self.max_atm_spread_pct,
               self.min_option_volume) < 0:
            raise ValueError("tolerances and liquidity limits must be 0 or more")

    @property
    def options_checked(self) -> int:
        return 2 * (2 * self.strikes_each_side + 1)

    def side(self, side: str) -> OHOLSide:
        return self.long if side == "LONG" else self.short

    def to_dict(self) -> dict:
        return asdict(self)


class OpenHighLowStore:
    def __init__(self, folder: str | Path) -> None:
        self.folder = Path(folder)
        self.path = self.folder / SETTINGS_FILE
        self.settings = OpenHighLowSettings()
        if self.path.exists():
            self.settings = replace(OpenHighLowSettings(), **json.loads(self.path.read_text(encoding="utf-8")))

    def update(self, **changes) -> OpenHighLowSettings:
        self.settings = replace(self.settings, **changes)
        self.folder.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.settings.to_dict(), indent=2, default=str), encoding="utf-8")
        return self.settings


# ------------------------------------------------------------------ the condition

@dataclass(frozen=True)
class Quote:
    symbol: str
    open: float
    high: float
    low: float
    ltp: float
    volume: float = 0.0
    bid: float = 0.0
    ask: float = 0.0

    @property
    def traded(self) -> bool:
        return self.open > 0 and self.high > 0 and self.low > 0


def open_is_low(q: Optional[Quote], tol_pct: float) -> bool:
    return bool(q and q.traded and q.high > q.low and (q.open - q.low) <= q.open * tol_pct / 100)


def open_is_high(q: Optional[Quote], tol_pct: float) -> bool:
    return bool(q and q.traded and q.high > q.low and (q.high - q.open) <= q.open * tol_pct / 100)


def condition(q: Optional[Quote], side: str, tol_pct: float) -> bool:
    return open_is_low(q, tol_pct) if side == "LONG" else open_is_high(q, tol_pct)


def side_of(q: Optional[Quote], tol_pct: float) -> Optional[str]:
    lo, hi = open_is_low(q, tol_pct), open_is_high(q, tol_pct)
    return "LONG" if lo and not hi else ("SHORT" if hi and not lo else None)


# ------------------------------------------------------------------ option strikes

def option_strikes(master: dict, stock: str, spot: float, today: date, each_side: int = 5, min_days: int = 0
                   ) -> tuple[Optional[date], list[tuple[float, str, str]]]:
    """Nearest-expiry stock options around the price: [(strike, CE symbol, PE symbol)] for the ATM strike and
    ``each_side`` strikes below and above it (from the real strike list: gaps differ per stock)."""
    by_expiry: dict[date, dict[float, dict]] = {}
    for symbol, row in master.items():
        if row.get("underSym") != stock or row.get("optType") not in ("CE", "PE"):
            continue
        try:
            expiry = datetime.fromtimestamp(int(row["expiryDate"]), IST).date()
            strike = float(row["strikePrice"])
        except (KeyError, ValueError, TypeError):
            continue
        if (expiry - today).days >= min_days:
            by_expiry.setdefault(expiry, {}).setdefault(strike, {})[row["optType"]] = str(row.get("symTicker") or symbol)
    if not by_expiry:
        return None, []
    expiry = min(by_expiry)
    strikes = sorted(k for k, v in by_expiry[expiry].items() if "CE" in v and "PE" in v)
    if not strikes:
        return expiry, []
    atm = min(range(len(strikes)), key=lambda i: (abs(strikes[i] - spot), strikes[i]))
    chosen = strikes[max(0, atm - each_side):atm + each_side + 1]
    return expiry, [(k, by_expiry[expiry][k]["CE"], by_expiry[expiry][k]["PE"]) for k in chosen]


def option_lot(master: dict, symbol: str) -> int:
    for key, row in master.items():
        if (row.get("symTicker") or key) == symbol:
            return int(row.get("minLotSize") or 1)
    return 1


# ------------------------------------------------------------------ one stock

@dataclass
class Candidate:
    stock: str
    side: Optional[str]                 # LONG / SHORT / None (no condition)
    spot_ok: bool
    fut_ok: bool
    call_matches: int
    put_matches: int
    options_checked: int
    fut_value_cr: float
    atm_spread_pct: Optional[float]
    option_volume: float
    liquidity_ok: bool
    passes: bool
    reasons: list
    spot: Optional[Quote] = None
    fut: Optional[Quote] = None
    atm_strike: Optional[float] = None
    atm_call: Optional[str] = None
    atm_put: Optional[str] = None
    atm_call_ltp: Optional[float] = None
    atm_put_ltp: Optional[float] = None

    @property
    def option_matches(self) -> int:
        return self.call_matches + self.put_matches

    @property
    def option_score(self) -> float:
        return round(100 * self.option_matches / self.options_checked, 1) if self.options_checked else 0.0

    @property
    def liquidity_score(self) -> float:
        """0-100: futures value (2x the minimum = full), tight ATM spread, option volume."""
        value = min(1.0, self.fut_value_cr / 20.0)
        spread = 0.0 if self.atm_spread_pct is None else max(0.0, 1.0 - self.atm_spread_pct / 2.0)
        return round(100 * (0.6 * value + 0.4 * spread), 1)

    def row(self) -> dict:
        return {"stock": self.stock, "side": self.side or "", "spot": self.spot_ok, "future": self.fut_ok,
                "calls": self.call_matches, "puts": self.put_matches,
                "option_score": self.option_score, "fut_value_cr": round(self.fut_value_cr, 2),
                "atm_spread_pct": None if self.atm_spread_pct is None else round(self.atm_spread_pct, 2),
                "option_volume": int(self.option_volume), "liquidity": self.liquidity_score,
                "liquidity_ok": self.liquidity_ok, "passes": self.passes, "why_not": "; ".join(self.reasons),
                "price": None if self.spot is None else self.spot.ltp, "atm_strike": self.atm_strike}


def evaluate(stock: str, spot: Optional[Quote], fut: Optional[Quote], options: Sequence[tuple[float, Optional[Quote],
             Optional[Quote]]], s: OpenHighLowSettings, *, atm_strike: float | None = None,
             atm_symbols: tuple = (None, None)) -> Candidate:
    """``options`` = [(strike, CE quote, PE quote)] of the 11 strikes (missing quote = no match)."""
    spot_side, fut_side = side_of(spot, s.tolerance_pct), side_of(fut, s.tolerance_pct)
    side = spot_side or fut_side
    reasons = []
    if side is None:
        return Candidate(stock, None, False, False, 0, 0, s.options_checked, 0.0, None, 0.0, False, False,
                         ["no open = high / low"], spot, fut, atm_strike, *atm_symbols)
    spot_ok, fut_ok = condition(spot, side, s.tolerance_pct), condition(fut, side, s.tolerance_pct)
    if s.confirm == "BOTH" and not (spot_ok and fut_ok):
        reasons.append("spot and futures disagree")
    if not s.side(side).enabled:
        reasons.append(f"{side} side off")
    put_side = "SHORT" if side == "LONG" else "LONG"         # puts move the other way
    calls = sum(condition(ce, side, s.option_tolerance_pct) for _, ce, _ in options)
    puts = sum(condition(pe, put_side, s.option_tolerance_pct) for _, _, pe in options)
    if calls + puts < s.min_option_matches:
        reasons.append(f"options {calls + puts}/{s.options_checked} < {s.min_option_matches}")
    fut_value = (fut.volume * fut.ltp / 1e7) if fut and fut.traded else 0.0
    spreads, atm_ltp = [], (None, None)
    for strike, ce, pe in options:
        if atm_strike is not None and strike == atm_strike:
            atm_ltp = (ce.ltp if ce else None, pe.ltp if pe else None)
            spreads = [(q.ask - q.bid) / q.ltp * 100 for q in (ce, pe) if q and q.ltp > 0 and q.ask > 0 and q.bid > 0]
    atm_spread = max(spreads) if spreads else None
    volume = sum((q.volume if q else 0) for _, ce, pe in options for q in (ce, pe))
    liquid = True
    if fut_value < s.min_fut_value_cr:
        liquid = False
        reasons.append(f"futures value {fut_value:.1f} cr < {s.min_fut_value_cr:g}")
    if atm_spread is None or atm_spread > s.max_atm_spread_pct:
        liquid = False
        reasons.append("ATM spread " + ("unknown" if atm_spread is None else f"{atm_spread:.2f}%") +
                       f" > {s.max_atm_spread_pct:g}%")
    if s.min_option_volume and volume < s.min_option_volume:
        liquid = False
        reasons.append(f"option volume {volume:.0f} < {s.min_option_volume}")
    return Candidate(stock, side, spot_ok, fut_ok, calls, puts, s.options_checked, fut_value, atm_spread, volume,
                     liquid, not reasons, reasons, spot, fut, atm_strike, *atm_symbols, *atm_ltp)


def select_top(candidates: Sequence[Candidate], s: OpenHighLowSettings) -> list[Candidate]:
    """The best ``top_n`` passing candidates: most matching options first, then liquidity, then name."""
    ok = [c for c in candidates if c.passes]
    return sorted(ok, key=lambda c: (-c.option_matches, -c.liquidity_score, c.stock))[:s.top_n]


def breakout(minutes: Sequence, side: str, s: OpenHighLowSettings) -> dict:
    """The owner's entry on one chart's 1-minute candles of the day (5-minute candles work too).

    First candle = 09:15 to the scan time. Trigger = its high (LONG) / low (SHORT). Entry = the first minute of the
    next ``entry_valid_candles`` candles that trades beyond the trigger, at the trigger (or that minute's open if it
    opened beyond it). Cancelled when, before that, price goes below the open (LONG) / above it (SHORT).
    Returns {"state": WAITING / ENTERED / CANCELLED / NO ENTRY, "trigger", "open", "entry", "entry_ts", "stop"}."""
    if not minutes:
        return {"state": "WAITING", "trigger": None, "open": None}
    day = datetime.fromtimestamp(minutes[0].timestamp, IST).date()
    start = int(datetime.combine(day, time(9, 15), tzinfo=IST).timestamp())
    first_end = start + s.first_candle_minutes * 60
    window_end = first_end + s.entry_valid_candles * s.first_candle_minutes * 60
    first = [m for m in minutes if start <= m.timestamp < first_end]
    if not first:
        return {"state": "WAITING", "trigger": None, "open": None}
    day_open = first[0].open
    long = side == "LONG"
    trigger = max(m.high for m in first) if long else min(m.low for m in first)
    out = {"state": "WAITING", "trigger": trigger, "open": day_open, "first_end": first_end, "window_end": window_end}
    limit = day_open * (1 - s.tolerance_pct / 100) if long else day_open * (1 + s.tolerance_pct / 100)
    step = 60
    if len(minutes) > 1:
        step = min((b.timestamp - a.timestamp for a, b in zip(minutes, minutes[1:]) if b.timestamp > a.timestamp),
                   default=60)
    seen_low, seen_high = min(m.low for m in first), max(m.high for m in first)
    for m in (x for x in minutes if first_end <= x.timestamp < window_end):
        crossed = m.high > trigger if long else m.low < trigger
        if crossed:
            entry = max(trigger, m.open) if long else min(trigger, m.open)
            seen_low, seen_high = min(seen_low, m.low), max(seen_high, m.high)
            buf = s.side(side).sl_buffer_pct / 100
            stop = seen_low * (1 - buf) if long else seen_high * (1 + buf)
            return {**out, "state": "ENTERED", "entry": entry, "entry_ts": m.timestamp, "stop": stop}
        if (m.low < limit) if long else (m.high > limit):
            return {**out, "state": "CANCELLED", "cancelled_at": m.timestamp}
        seen_low, seen_high = min(seen_low, m.low), max(seen_high, m.high)
    if minutes[-1].timestamp + step >= window_end:
        return {**out, "state": "NO ENTRY"}
    return out


def levels(c: Candidate, s: OpenHighLowSettings) -> tuple[float, float]:
    """(entry, stop) on the chart the trade is managed on (futures for FUTURE, spot otherwise)."""
    q = c.fut if s.instrument == "FUTURE" else c.spot
    buf = s.side(c.side).sl_buffer_pct / 100
    stop = q.low * (1 - buf) if c.side == "LONG" else q.high * (1 + buf)
    return q.ltp, stop


__all__ = [
    "CONFIRM", "Candidate", "INSTRUMENTS", "breakout", "OHOLSide", "OpenHighLowSettings", "OpenHighLowStore", "Quote", "condition",
    "evaluate", "levels", "open_is_high", "open_is_low", "option_lot", "option_strikes", "select_top", "side_of",
]
