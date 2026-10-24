"""Gap Reversal strategy (stocks and indexes). OFF by default; research + paper only.

Idea (owner, 25 Oct 2026): a stock or index opens with a big gap (>= 3% by default, a setting).
In the first candles of the day (first 10 x 5-minute or first 16 x 3-minute candles, settings)
look for a reversal setup at the day's extreme, where buyers (gap up) or sellers (gap down) got
absorbed. Mark each candidate with a REVERSAL STRENGTH %, then trade the reversal:
  gap UP   -> SHORT setups (top reversals), stop at the day's HIGH
  gap DOWN -> LONG setups (bottom reversals), stop at the day's LOW
  exit (strategies/exit_plan.py, same for every strategy): reward 1:[box] (1.5, 2, 2.5, 3 or any
  number) or an EMPTY box = the trailing stop (TSL) takes the trade out when a candle closes beyond
  it; flat by 15:10. LONG and SHORT have separate settings.

The 10 setups (docs/reversal_setups.png): shooting star / hammer, doji, engulfing, evening /
morning star, dark cloud / piercing, tweezer, harami, failed breakout / breakdown, volume climax
(absorption), double top / bottom. LONG setups are the exact mirror of SHORT ones: the candles
are flipped upside down and the same short rules are applied.

Reversal strength % (weights are settings):
  rejection 25     how far the setup closes back from its extreme (long wick / strong reversal body)
  absorption 30    volume of the setup vs the day's average, with little progress in the trend's
                   direction: much buying, price not going up = buyers absorbed by sellers
  location 20      at the day's extreme, and stretched away from VWAP
  confirmation 25  the next candle breaks (or closes beyond) the setup candle
x a pattern weight (harami 0.8, tweezer and double top 0.9, others 1.0).
Without volume (spot index) the absorption part counts as half.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, time
from pathlib import Path
from typing import Optional, Sequence
from zoneinfo import ZoneInfo

from paper_trading.tsl_methods import method_stops
from strategies.exit_plan import NO_TSL, ExitPlan, parse_rr

IST = ZoneInfo("Asia/Kolkata")
PATTERNS = ("SHOOTING_STAR", "DOJI", "ENGULFING", "EVENING_STAR", "DARK_CLOUD", "TWEEZER", "HARAMI",
            "FAILED_BREAKOUT", "VOLUME_CLIMAX", "DOUBLE_TOP")
SHORT_NAMES = {"SHOOTING_STAR": "Shooting star / pin bar", "DOJI": "Doji at the top", "ENGULFING": "Bearish engulfing",
               "EVENING_STAR": "Evening star", "DARK_CLOUD": "Dark cloud cover", "TWEEZER": "Tweezer top",
               "HARAMI": "Bearish harami", "FAILED_BREAKOUT": "Failed breakout (bull trap)",
               "VOLUME_CLIMAX": "Volume climax / absorption", "DOUBLE_TOP": "Double top / lower high"}
LONG_NAMES = {"SHOOTING_STAR": "Hammer / pin bar", "DOJI": "Doji at the bottom", "ENGULFING": "Bullish engulfing",
              "EVENING_STAR": "Morning star", "DARK_CLOUD": "Piercing line", "TWEEZER": "Tweezer bottom",
              "HARAMI": "Bullish harami", "FAILED_BREAKOUT": "Failed breakdown (bear trap)",
              "VOLUME_CLIMAX": "Selling climax / absorption", "DOUBLE_TOP": "Double bottom / higher low"}
ENTRY_MODES = ("BREAK", "CLOSE")
RR_CHOICES = (1.5, 2.0, 2.5, 3.0)
SETTINGS_FILE = "settings.json"


def _all_on() -> dict:
    return {p: True for p in PATTERNS}


def _pattern_weights() -> dict:
    return {**{p: 1.0 for p in PATTERNS}, "HARAMI": 0.8, "TWEEZER": 0.9, "DOUBLE_TOP": 0.9}


@dataclass(frozen=True)
class SideSettings:
    """Settings of one side (SHORT after a gap up, LONG after a gap down)."""
    enabled: bool = True
    patterns: dict = field(default_factory=_all_on)
    min_strength: float = 60.0          # % needed to call it a trade candidate
    entry_mode: str = "BREAK"           # BREAK: price trades beyond the setup candle; CLOSE: a candle closes beyond it
    entry_valid_bars: int = 3           # candles after the setup during which the entry may happen
    sl_buffer_pct: float = 0.0          # extra room beyond the day's extreme, % of price
    max_risk_pct: float = 0.0           # skip when the stop is farther than this % of price (0 = no limit)
    # exit plan (same fields as strategies/exit_plan.ExitPlan): reward 1:[target_rr], None = TSL exit
    target_rr: Optional[float] = 2.0
    tsl_method: str = NO_TSL            # NONE or a TSL preset (on this strategy's candles, the stock chart)
    tsl_trigger: str = "CLOSE"
    method_params: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.entry_mode not in ENTRY_MODES:
            raise ValueError(f"entry_mode must be one of {ENTRY_MODES}")
        if not 0 <= self.min_strength <= 100 or self.entry_valid_bars < 1:
            raise ValueError("min_strength 0-100, entry_valid_bars >= 1")
        plan = self.exit_plan()                   # validates the exit fields
        object.__setattr__(self, "target_rr", plan.target_rr)
        object.__setattr__(self, "method_params", plan.method_params)
        merged = _all_on()
        merged.update({k: bool(v) for k, v in (self.patterns or {}).items() if k in merged})
        object.__setattr__(self, "patterns", merged)

    def exit_plan(self) -> ExitPlan:
        return ExitPlan(target_rr=parse_rr(self.target_rr), tsl_method=self.tsl_method, tsl_trigger=self.tsl_trigger,
                        method_params=self.method_params)


@dataclass(frozen=True)
class GapReversalSettings:
    enabled: bool = False                # OFF by default: the owner turns it on
    gap_pct: float = 3.0                 # open vs previous close, %
    timeframe: int = 5                   # 3 or 5 minute candles
    window_5m: int = 10                  # setups only in the first 10 candles of 5 minutes ...
    window_3m: int = 16                  # ... or the first 16 candles of 3 minutes
    exit_time: str = "15:10"
    include_indexes: bool = True         # scan NIFTY, BANK NIFTY, SENSEX too (spot has no volume)
    rr_choices: tuple = RR_CHOICES
    # pattern rules
    doji_body_pct: float = 10.0          # body <= 10% of the candle's range
    wick_ratio: float = 2.0              # pin bar wick >= 2 x body
    top_zone_pct: float = 0.5            # setup high within 0.5% of the day's high (low for longs)
    climax_volume_mult: float = 2.0      # volume climax: >= 2 x the day's average volume
    tweezer_tol_pct: float = 0.1         # tweezer highs equal within 0.1%
    double_top_tol_pct: float = 0.3      # double top: second high at most 0.3% above the first (lower is fine)
    stretch_full_pct: float = 1.0        # 1% away from VWAP = full location score
    # strength weights and pattern weights
    w_rejection: float = 25.0
    w_absorption: float = 30.0
    w_location: float = 20.0
    w_confirmation: float = 25.0
    pattern_weights: dict = field(default_factory=_pattern_weights)
    # paper trading
    capital: float = 100_000.0
    allocation_pct: float = 20.0
    short: SideSettings = field(default_factory=SideSettings)
    long: SideSettings = field(default_factory=SideSettings)

    def __post_init__(self) -> None:
        if self.timeframe not in (1, 3, 5, 10, 15):
            raise ValueError("timeframe must be 1, 3, 5, 10 or 15 minutes")
        if self.gap_pct <= 0:
            raise ValueError("gap_pct must be positive")
        if isinstance(self.short, dict):
            object.__setattr__(self, "short", SideSettings(**self.short))
        if isinstance(self.long, dict):
            object.__setattr__(self, "long", SideSettings(**self.long))
        weights = _pattern_weights()
        weights.update({k: float(v) for k, v in (self.pattern_weights or {}).items() if k in weights})
        object.__setattr__(self, "pattern_weights", weights)
        object.__setattr__(self, "rr_choices", tuple(float(r) for r in self.rr_choices))
        time.fromisoformat(self.exit_time)

    def window_bars(self) -> int:
        if self.timeframe == 5:
            return self.window_5m
        if self.timeframe == 3:
            return self.window_3m
        return max(1, round(self.window_5m * 5 / self.timeframe))

    def side(self, side: str) -> SideSettings:
        return self.short if side == "SHORT" else self.long

    def to_dict(self) -> dict:
        return asdict(self)


class GapReversalStore:
    """``data/gap_reversal/settings.json``; the saved file wins over the defaults."""

    def __init__(self, folder: str | Path) -> None:
        self.path = Path(folder) / SETTINGS_FILE
        self._settings = GapReversalSettings()
        if self.path.exists():
            try:
                self._settings = GapReversalSettings(**json.loads(self.path.read_text(encoding="utf-8")))
            except (ValueError, TypeError) as exc:
                raise ValueError(f"{self.path} is invalid ({exc}); fix or delete it to use the defaults.") from exc

    @property
    def settings(self) -> GapReversalSettings:
        return self._settings

    def update(self, **changes) -> GapReversalSettings:
        data = {**self._settings.to_dict(), **changes}
        self._settings = GapReversalSettings(**data)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self._settings.to_dict(), indent=2), encoding="utf-8")
        return self._settings


# ------------------------------------------------------------------ candles

@dataclass(frozen=True)
class Bar:
    timestamp: int
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0


def bars_from(candles) -> list[Bar]:
    return [Bar(int(c.timestamp), float(c.open), float(c.high), float(c.low), float(c.close),
                float(getattr(c, "volume", 0) or 0)) for c in candles]


def flip(bars: Sequence[Bar]) -> list[Bar]:
    """Upside-down copy: a bottom reversal becomes a top reversal (used for LONG setups)."""
    return [Bar(b.timestamp, -b.open, -b.low, -b.high, -b.close, b.volume) for b in bars]


def _rng(b: Bar) -> float:
    return b.high - b.low


def _body(b: Bar) -> float:
    return abs(b.close - b.open)


def _green(b: Bar) -> bool:
    return b.close > b.open


def _red(b: Bar) -> bool:
    return b.close < b.open


# ------------------------------------------------------------------ the 10 setups (top side)

@dataclass(frozen=True)
class Setup:
    pattern: str
    start: int             # first candle of the setup
    end: int               # last candle (the reversal candle)
    trigger: float         # entry level (in the flipped space for LONG)


def detect(bars: Sequence[Bar], i: int, s: GapReversalSettings) -> list[Setup]:
    """Every top-reversal setup that completes on candle ``i`` (bars in the SHORT orientation)."""
    b = bars[i]
    r = _rng(b)
    if r <= 0:
        return []
    day_high = max(x.high for x in bars[:i + 1])
    high_before = max((x.high for x in bars[:i]), default=None)
    zone = abs(day_high) * s.top_zone_pct / 100

    def near_top(level: float) -> bool:
        return level >= day_high - zone

    out: list[Setup] = []
    uw, body = b.high - max(b.open, b.close), _body(b)
    if (uw >= s.wick_ratio * max(body, 0.05 * r) and uw >= 0.5 * r and (b.close - b.low) / r <= 0.4
            and near_top(b.high)):
        out.append(Setup("SHOOTING_STAR", i, i, b.low))
    if body <= s.doji_body_pct / 100 * r and near_top(b.high):
        out.append(Setup("DOJI", i, i, b.low))
    if i >= 1:
        p = bars[i - 1]
        pb = _body(p)
        top = max(p.high, b.high)
        if (_green(p) and _red(b) and b.open >= p.close - 0.1 * pb and b.close <= p.open and body >= pb
                and near_top(top)):
            out.append(Setup("ENGULFING", i - 1, i, b.low))
        if (_green(p) and pb >= 0.5 * _rng(p) and _red(b) and b.open >= p.close - 0.1 * pb
                and p.open < b.close < (p.open + p.close) / 2 and near_top(top)):
            out.append(Setup("DARK_CLOUD", i - 1, i, b.low))
        if (_green(p) and _red(b) and abs(b.high - p.high) <= abs(p.high) * s.tweezer_tol_pct / 100
                and near_top(top)):
            out.append(Setup("TWEEZER", i - 1, i, min(p.low, b.low)))
        if (_green(p) and pb >= 0.6 * _rng(p) and _red(b) and max(b.open, b.close) <= p.close
                and min(b.open, b.close) >= p.open and body <= 0.5 * pb and near_top(p.high)):
            out.append(Setup("HARAMI", i - 1, i, b.low))
        if (high_before is not None and b.high > high_before and b.close < high_before
                and (b.close - b.low) / r <= 0.5):
            out.append(Setup("FAILED_BREAKOUT", i, i, b.low))
    if i >= 2:
        a, m = bars[i - 2], bars[i - 1]
        ab = _body(a)
        if (_green(a) and ab >= 0.5 * _rng(a) and _body(m) <= 0.3 * ab and min(m.open, m.close) >= a.close - 0.5 * ab
                and _red(b) and b.close <= (a.open + a.close) / 2 and near_top(max(a.high, m.high, b.high))):
            out.append(Setup("EVENING_STAR", i - 2, i, b.low))
        earlier = bars[:i]
        avg_vol = sum(x.volume for x in earlier) / len(earlier)
        progress = (b.close - b.open) / r
        if avg_vol > 0 and b.volume >= s.climax_volume_mult * avg_vol and progress <= 0.3 and near_top(b.high):
            out.append(Setup("VOLUME_CLIMAX", i, i, b.low))
        # double top: an earlier peak at about the same height, a dip between, now turning down
        if _red(b):
            avg_rng = sum(_rng(x) for x in bars[:i + 1]) / (i + 1)
            peak2 = max(b.high, m.high)
            for j in range(0, i - 1):
                pj = bars[j]
                local_max = pj.high >= max((x.high for x in bars[max(0, j - 1):j + 2]))
                tol = abs(pj.high) * s.double_top_tol_pct / 100
                between = bars[j + 1:i]
                if not local_max or not between or peak2 > pj.high + tol:
                    continue
                neck = min(x.low for x in between)
                # second push climbs back at least half way from the dip (equal or LOWER high), then turns down
                if (pj.high - neck >= 0.5 * avg_rng and peak2 >= neck + 0.5 * (pj.high - neck)
                        and b.close < peak2 - 0.25 * (peak2 - neck) and near_top(max(pj.high, peak2))):
                    out.append(Setup("DOUBLE_TOP", j, i, neck))
                    break
    return out


# ------------------------------------------------------------------ strength

def vwap_at(bars: Sequence[Bar], i: int) -> float:
    vol = sum(b.volume for b in bars[:i + 1])
    if vol > 0:
        return sum((b.high + b.low + b.close) / 3 * b.volume for b in bars[:i + 1]) / vol
    return sum((b.high + b.low + b.close) / 3 for b in bars[:i + 1]) / (i + 1)


def strength(bars: Sequence[Bar], setup: Setup, s: GapReversalSettings, entry_mode: str = "BREAK") -> dict:
    """Reversal strength % and its parts (bars in the SHORT orientation)."""
    span = bars[setup.start:setup.end + 1]
    last = bars[setup.end]
    top = max(x.high for x in span)
    bottom = min(x.low for x in span)
    rejection = max(0.0, min(1.0, (top - last.close) / (top - bottom))) if top > bottom else 0.0
    before = bars[:setup.start]
    avg_vol = (sum(x.volume for x in before) / len(before)) if before else 0.0
    biggest = max(span, key=lambda x: x.volume)
    if avg_vol > 0 and biggest.volume > 0:
        vol_ratio = biggest.volume / avg_vol
        progress = (biggest.close - biggest.open) / _rng(biggest) if _rng(biggest) > 0 else 0.0
        absorption = min(1.0, vol_ratio / 3.0) * (1.0 - max(0.0, min(1.0, progress)))
    else:
        vol_ratio, absorption = None, 0.5                 # no volume data: neutral
    day_high = max(x.high for x in bars[:setup.end + 1])
    at_top = top >= day_high - abs(day_high) * s.top_zone_pct / 100
    vw = vwap_at(bars, setup.end)
    stretch_pct = (top - vw) / abs(vw) * 100 if vw else 0.0
    location = (0.5 if at_top else 0.0) + 0.5 * max(0.0, min(1.0, stretch_pct / s.stretch_full_pct))
    confirmation, confirmed = 0.0, None
    if setup.end + 1 < len(bars):
        nxt = bars[setup.end + 1]
        if nxt.close < setup.trigger:
            confirmation, confirmed = 1.0, True
        elif nxt.low < setup.trigger:
            confirmation, confirmed = (0.6, True) if entry_mode == "BREAK" else (0.6, False)
        else:
            confirmed = False
    total = s.w_rejection + s.w_absorption + s.w_location + s.w_confirmation
    raw = (s.w_rejection * rejection + s.w_absorption * absorption + s.w_location * location
           + s.w_confirmation * confirmation)
    score = 100 * raw / total * s.pattern_weights.get(setup.pattern, 1.0) if total > 0 else 0.0
    return {"strength": round(score, 1), "rejection": round(rejection * 100), "absorption": round(absorption * 100),
            "location": round(location * 100), "confirmation": round(confirmation * 100),
            "volume_ratio": None if vol_ratio is None else round(vol_ratio, 2), "confirmed": confirmed}


# ------------------------------------------------------------------ scanning a day

@dataclass
class Candidate:
    symbol: str
    side: str                  # SHORT or LONG
    gap_pct: float
    bar_index: int
    bar_time: int              # start of the reversal candle
    patterns: list
    pattern_names: str
    strength: float
    parts: dict
    trigger: float             # entry level (real prices)
    setup_extreme: float       # highest high (short) / lowest low (long) of the setup
    qualifies: bool            # strength >= the side's minimum


def gap_side(prev_close: float, day_open: float, s: GapReversalSettings) -> tuple[Optional[str], float]:
    gap = (day_open - prev_close) / prev_close * 100 if prev_close else 0.0
    if gap >= s.gap_pct and s.short.enabled:
        return "SHORT", gap
    if gap <= -s.gap_pct and s.long.enabled:
        return "LONG", gap
    return None, gap


def scan_bars(symbol: str, prev_close: float, bars: Sequence[Bar], s: GapReversalSettings) -> list[Candidate]:
    """Candidates in the opening window of one day (``bars`` = finished candles of the timeframe)."""
    if not bars:
        return []
    side, gap = gap_side(prev_close, bars[0].open, s)
    if side is None:
        return []
    side_cfg = s.side(side)
    oriented = list(bars) if side == "SHORT" else flip(bars)
    names = SHORT_NAMES if side == "SHORT" else LONG_NAMES
    sign = 1 if side == "SHORT" else -1
    out = []
    for i in range(min(len(bars), s.window_bars())):
        setups = [x for x in detect(oriented, i, s) if side_cfg.patterns.get(x.pattern, True)]
        if not setups:
            continue
        scored = [(strength(oriented, x, s, side_cfg.entry_mode), x) for x in setups]
        best_parts, best = max(scored, key=lambda t: t[0]["strength"])
        top = max(x.high for x in oriented[best.start:best.end + 1])
        out.append(Candidate(
            symbol=symbol, side=side, gap_pct=round(gap, 2), bar_index=i, bar_time=bars[i].timestamp,
            patterns=[x.pattern for _, x in scored], pattern_names=" + ".join(names[x.pattern] for _, x in scored),
            strength=best_parts["strength"], parts=best_parts, trigger=sign * best.trigger,
            setup_extreme=sign * top, qualifies=best_parts["strength"] >= side_cfg.min_strength))
    return out


# ------------------------------------------------------------------ the trade

@dataclass
class TradeResult:
    symbol: str
    side: str
    candidate_time: int
    entry_time: int
    entry: float
    stop: float                # the hard stop (day's extreme + buffer)
    risk: float
    rr: Optional[float]        # None = no fixed target (TSL exit)
    target: Optional[float]
    exit_time: int
    exit: float
    result: str                # TARGET, STOP, TSL, TIME (15:10) or OPEN (live, still running)
    points: float              # in the trade's favour (+ = profit)
    r_multiple: float
    exit_detail: str = ""
    max_favourable_r: float = 0.0   # best move in the trade's favour before the exit, in R


def _step(minutes: Sequence[Bar]) -> int:
    """Seconds per 'minute' candle (60 for 1-minute data, 300 when only 5-minute data exists)."""
    gaps = [b.timestamp - a.timestamp for a, b in zip(minutes, minutes[1:]) if b.timestamp > a.timestamp]
    return min(gaps) if gaps else 60


def simulate(candidate: Candidate, bars: Sequence[Bar], minutes: Sequence[Bar], s: GapReversalSettings,
             rr: float | None = None, live: bool = False, plan: ExitPlan | None = None,
             history: Sequence[Bar] = ()) -> Optional[TradeResult]:
    """Entry after the candidate (BREAK or CLOSE), hard stop at the day's extreme so far, then the exit plan:
    target ``rr`` x risk (if any) and / or the TSL on the strategy candles (exit when a candle CLOSES beyond it).
    ``minutes`` = the day's 1-minute candles (precise entry, stop and target); stop first if both touch.
    ``rr`` (backtest) = fixed target only, no TSL; ``plan`` overrides the side's exit plan.
    ``live``: the day is still running, so a trade without an exit yet is OPEN (not a 15:10 exit).
    ``history``: earlier days' strategy candles, only to warm the TSL up (as on a TradingView chart).

    TSL rules (no look-ahead): a TSL value is known at its candle's close and protects the next candles;
    it only tightens; it starts once it is on the protective side of price (above it for a SHORT), so
    the up-trend values before the reversal do not throw the trade out at once."""
    side_cfg = s.side(candidate.side)
    if plan is None:
        plan = ExitPlan(target_rr=rr, tsl_method=NO_TSL) if rr is not None else side_cfg.exit_plan()
    short = candidate.side == "SHORT"
    sign = 1 if short else -1
    o_bars = list(bars) if short else flip(bars)
    o_min = list(minutes) if short else flip(minutes)
    trigger = candidate.trigger if short else -candidate.trigger
    tf = (bars[1].timestamp - bars[0].timestamp) if len(bars) > 1 else s.timeframe * 60
    step = _step(minutes)
    entry = entry_ts = None
    last_k = min(len(o_bars) - 1, candidate.bar_index + side_cfg.entry_valid_bars)
    for k in range(candidate.bar_index + 1, last_k + 1):
        bar = o_bars[k]
        if side_cfg.entry_mode == "CLOSE":
            if bar.close < trigger:
                entry, entry_ts = bar.close, bar.timestamp + tf
                break
            continue
        inside = [m for m in o_min if bar.timestamp <= m.timestamp < bar.timestamp + tf]
        for m in inside:
            if m.low < trigger:
                entry, entry_ts = min(trigger, m.open), m.timestamp
                break
        if entry is not None:
            break
    if entry is None:
        return None
    seen = [m for m in o_min if m.timestamp <= entry_ts]
    extreme = max(m.high for m in seen)                     # the day's high (short) / low (long) so far
    stop = extreme + abs(extreme) * side_cfg.sl_buffer_pct / 100
    risk = stop - entry
    if risk <= 0:
        return None
    if side_cfg.max_risk_pct and risk / abs(entry) * 100 > side_cfg.max_risk_pct:
        return None
    target = None if plan.target_rr is None else entry - plan.target_rr * risk
    day = datetime.fromtimestamp(entry_ts, IST).date()
    cutoff = int(datetime.combine(day, time.fromisoformat(s.exit_time), tzinfo=IST).timestamp())

    # TSL values per strategy candle, on real prices and the real side, then turned to the short view
    tsl_at: dict[int, tuple] = {}                           # candle end -> (index, value or None, flip)
    if plan.uses_tsl:
        kind, params = plan.method()
        real_entry = sign * entry
        warm = len(history)
        points = method_stops(kind, params, list(history) + list(bars), candidate.side, entry_price=real_entry)[warm:]
        for k, (bar, point) in enumerate(zip(bars, points)):
            value = None if point.stop is None else sign * point.stop
            tsl_at[bar.timestamp + tf] = (k, value, point.against)
    tsl = None
    for end in sorted(e for e in tsl_at if e <= entry_ts):   # the method's value when the trade starts
        k, value, _ = tsl_at[end]
        tsl = value if value is not None and value > o_bars[k].close else None

    exit_price, exit_ts, result, detail = None, None, "TIME", ""
    best = entry
    after = [m for m in o_min if m.timestamp > entry_ts and m.timestamp < cutoff]
    entry_end = entry_ts if side_cfg.entry_mode == "CLOSE" else entry_ts + step
    if entry_end in tsl_at:                                 # the entry candle closes in the entry minute
        k, value, _ = tsl_at[entry_end]
        if value is not None and value > o_bars[k].close:
            tsl = value if tsl is None else min(tsl, value)
    for m in after:
        if m.high >= stop:
            exit_price, exit_ts, result, detail = max(stop, m.open), m.timestamp, "STOP", "day's extreme"
            break
        if target is not None and m.low <= target:
            exit_price, exit_ts, result, detail = target, m.timestamp, "TARGET", f"1:{plan.target_rr:g}"
            break
        best = min(best, m.low)
        if plan.uses_tsl and plan.tsl_trigger == "TOUCH" and tsl is not None and m.high >= tsl:
            exit_price, exit_ts, result, detail = max(tsl, m.open), m.timestamp, "TSL", f"touched {abs(tsl):g}"
            break
        hit = tsl_at.get(m.timestamp + step)
        if hit is None:
            continue
        k, value, against = hit
        close = o_bars[k].close
        if tsl is not None and plan.tsl_trigger == "CLOSE" and close > tsl:
            exit_price, exit_ts, result = close, m.timestamp + step, "TSL"
            detail = f"candle closed beyond the TSL {abs(tsl):g}"
            break
        if against and tsl is not None:
            exit_price, exit_ts, result, detail = close, m.timestamp + step, "TSL", "SAR switched sides"
            break
        if value is not None and (tsl is not None or value > close):
            tsl = value if tsl is None else min(tsl, value)
    if exit_price is None:
        last = after[-1] if after else [m for m in o_min if m.timestamp <= entry_ts][-1]
        exit_price, exit_ts = last.close, last.timestamp
        if live and (not after or after[-1].timestamp + step < cutoff):
            result = "OPEN"
    points_won = entry - exit_price
    return TradeResult(candidate.symbol, candidate.side, candidate.bar_time, entry_ts, sign * entry, sign * stop,
                       round(risk, 4), plan.target_rr, None if target is None else sign * target, exit_ts,
                       sign * exit_price, result, round(points_won, 4), round(points_won / risk, 3), detail,
                       round((entry - best) / risk, 3))


__all__ = [
    "Bar", "Candidate", "ENTRY_MODES", "GapReversalSettings", "GapReversalStore", "LONG_NAMES", "PATTERNS",
    "RR_CHOICES", "SHORT_NAMES", "Setup", "SideSettings", "TradeResult", "bars_from", "detect", "flip",
    "gap_side", "scan_bars", "simulate", "strength", "vwap_at",
]
