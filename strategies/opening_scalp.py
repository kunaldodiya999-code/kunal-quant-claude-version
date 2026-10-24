"""Opening Scalp: one quick trade in the first minutes after 09:15. DEFAULT OFF.

Research strategy, separate from KTMI Uni Lite. Points are NIFTY-sized and are
scaled for other indexes (BANK NIFTY / SENSEX move ~2.4x / ~3.2x more points).

Modes (choose one):
  ORB_CLOSE  - Opening-range breakout. Range = first ``range_minutes``. Enter when a
               1-minute candle CLOSES beyond the range high/low (+ buffer).
  DRIVE      - Follow a strong opening candle: if the first ``range_minutes`` close
               near their high (low) with a big body, buy CALL (PUT) at the next open.
  FADE       - Bet against an over-stretched open: if the first ``range_minutes`` ran
               more than ``fade_min_move`` one way, trade back the other way.

Risk: stop = min(range-based stop, ``max_stop``) and at least ``min_stop``;
target ``target_points``; optional stop-to-cost after ``breakeven_after`` points;
time stop ``exit_by``; one trade per index per day; entries only until ``last_entry``.
Decisions use completed candles only.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time
from typing import Sequence
from zoneinfo import ZoneInfo

from market_data.resampling import Candle

IST = ZoneInfo("Asia/Kolkata")
MODES = ("ORB_CLOSE", "DRIVE", "FADE")


@dataclass(frozen=True)
class OpeningScalpConfig:
    enabled: bool = False                 # OFF by default: the owner turns it on
    mode: str = "ORB_CLOSE"
    range_minutes: int = 10               # opening range 09:15 .. 09:25
    target_points: float = 50.0           # NIFTY points (scaled for other indexes)
    max_stop: float = 20.0
    min_stop: float = 10.0
    breakout_buffer: float = 2.0
    breakeven_after: float | None = 20.0  # stop to cost after +20 (None = off)
    last_entry: time = time(9, 45)
    exit_by: time = time(10, 15)
    drive_body_pct: float = 60.0          # DRIVE: body >= 60% of the range
    fade_min_move: float = 60.0           # FADE: first-range move of 60+ points
    max_range: float | None = None        # skip days whose opening range is wider (None = no filter)

    def __post_init__(self) -> None:
        if self.mode not in MODES:
            raise ValueError(f"mode must be one of {MODES}")
        if not 1 <= self.range_minutes <= 30:
            raise ValueError("range_minutes must be 1..30")
        if self.target_points <= 0 or self.max_stop <= 0 or self.min_stop <= 0 or self.min_stop > self.max_stop:
            raise ValueError("target/stop points must be positive and min_stop <= max_stop")

    def scaled(self, scale: float) -> "OpeningScalpConfig":
        """Same rules in another index's points (scale = its price / NIFTY's price)."""
        from dataclasses import replace
        return replace(
            self, target_points=self.target_points * scale, max_stop=self.max_stop * scale,
            min_stop=self.min_stop * scale, breakout_buffer=self.breakout_buffer * scale,
            breakeven_after=None if self.breakeven_after is None else self.breakeven_after * scale,
            fade_min_move=self.fade_min_move * scale,
            max_range=None if self.max_range is None else self.max_range * scale,
        )


@dataclass(frozen=True)
class ScalpSignal:
    direction: str          # LONG = BUY CALL, SHORT = BUY PUT
    decision_ts: int        # moment the deciding candle closed
    stop_points: float
    target_points: float
    reason: str


def _t(ts: int) -> time:
    return datetime.fromtimestamp(ts, IST).time()


def opening_scalp_signal(day: Sequence[Candle], config: OpeningScalpConfig, *, bar_seconds: int = 60
                         ) -> ScalpSignal | None:
    """The day's single signal from its candles (sorted, one day), or None."""
    bars = sorted(day, key=lambda c: c.timestamp)
    if not bars or _t(bars[0].timestamp) != time(9, 15):
        return None                                      # no proper open: no trade
    range_end = bars[0].timestamp + config.range_minutes * 60
    opening = [b for b in bars if b.timestamp < range_end]
    if len(opening) * bar_seconds < config.range_minutes * 60:
        return None
    hi, lo = max(b.high for b in opening), min(b.low for b in opening)
    o, c = opening[0].open, opening[-1].close
    width = hi - lo
    if config.max_range is not None and width > config.max_range:
        return None
    decided_at = range_end                               # opening range completes here

    def stop_for(range_stop: float) -> float:
        return min(max(range_stop, config.min_stop), config.max_stop)

    if config.mode == "DRIVE":
        if width <= 0 or abs(c - o) / width * 100 < config.drive_body_pct:
            return None
        direction = "LONG" if c > o else "SHORT"
        return ScalpSignal(direction, decided_at, stop_for(width / 2), config.target_points,
                           f"DRIVE body {abs(c - o):.0f}/{width:.0f}")
    if config.mode == "FADE":
        move = c - o
        if abs(move) < config.fade_min_move:
            return None
        direction = "SHORT" if move > 0 else "LONG"
        return ScalpSignal(direction, decided_at, stop_for(width / 2), config.target_points,
                           f"FADE first move {move:+.0f}")
    # ORB_CLOSE: first candle after the range that CLOSES beyond it
    for bar in bars:
        if bar.timestamp < range_end:
            continue
        close_ts = bar.timestamp + bar_seconds
        if _t(close_ts) > config.last_entry:
            return None
        if bar.close > hi + config.breakout_buffer:
            return ScalpSignal("LONG", close_ts, stop_for(bar.close - lo), config.target_points,
                               f"ORB up {hi:.1f}")
        if bar.close < lo - config.breakout_buffer:
            return ScalpSignal("SHORT", close_ts, stop_for(hi - bar.close), config.target_points,
                               f"ORB down {lo:.1f}")
    return None


__all__ = ["MODES", "OpeningScalpConfig", "ScalpSignal", "opening_scalp_signal"]
