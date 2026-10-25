"""After the entry: one intraday trade managed by the shared exit plan (every strategy uses this).

Hard stop (touch, on the 1-minute candles; the stop is checked first), target 1:rr (if the reward box
is filled), trailing stop (TSL) on the strategy's candles (exit when a candle CLOSES beyond it, or
touches it), and a time exit. Prices are the traded instrument's real prices; SHORT and LONG work the
same way (the maths runs in a "short view": LONG prices are negated).

TSL rules (no look-ahead): a TSL value is known at its candle's close and protects the next candles;
it only tightens; it starts once it is on the protective side of price (above it for a SHORT).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time
from typing import Optional, Sequence
from zoneinfo import ZoneInfo

from paper_trading.tsl_methods import method_stops
from strategies.exit_plan import ExitPlan

IST = ZoneInfo("Asia/Kolkata")


@dataclass(frozen=True)
class _C:                    # one candle in the short view
    timestamp: int
    open: float
    high: float
    low: float
    close: float


def _view(candles: Sequence, sign: int) -> list[_C]:
    if sign == 1:
        return [_C(int(c.timestamp), c.open, c.high, c.low, c.close) for c in candles]
    return [_C(int(c.timestamp), -c.open, -c.low, -c.high, -c.close) for c in candles]


def step_of(minutes: Sequence) -> int:
    """Seconds per 'minute' candle (60 for 1-minute data, 300 when only 5-minute data exists)."""
    gaps = [b.timestamp - a.timestamp for a, b in zip(minutes, minutes[1:]) if b.timestamp > a.timestamp]
    return min(gaps) if gaps else 60


@dataclass
class Outcome:
    side: str
    entry_time: int
    entry: float
    stop: float
    risk: float
    rr: Optional[float]
    target: Optional[float]
    exit_time: int
    exit: float
    result: str               # TARGET, STOP, TSL, TIME or OPEN (live, still running)
    detail: str
    points: float             # in the trade's favour (+ = profit)
    r_multiple: float
    max_favourable_r: float


def manage_trade(*, side: str, entry: float, entry_ts: int, stop: float, plan: ExitPlan, bars: Sequence,
                 minutes: Sequence, exit_time: str = "15:10", history: Sequence = (), live: bool = False,
                 entry_at_bar_close: bool = False, stop_label: str = "stop",
                 tsl_chart: Optional[dict] = None) -> Optional[Outcome]:
    """``bars`` = the day's finished strategy candles (TSL), ``minutes`` = the day's 1-minute candles (or
    5-minute when nothing finer exists), ``history`` = earlier days' strategy candles (TSL warm-up).
    ``entry_at_bar_close``: the entry is the close of a strategy candle (CLOSE entry). None if risk <= 0.
    ``tsl_chart``: run the TSL on ANOTHER chart (owner 25 Oct: spot / futures / option chart to choose), as
    {"label", "side", "entry", "bars", "minutes", "history"}: e.g. a stock trade whose stop and target stay on the
    stock while the TSL follows the bought option (side LONG on the premium). The TSL exit happens at that chart's
    candle close; the trade is closed at this chart's price of that moment."""
    forced_ts = forced_detail = None
    if tsl_chart is not None and plan.uses_tsl:
        t_side = tsl_chart["side"].upper()
        t_entry = float(tsl_chart["entry"])
        probe = manage_trade(side=t_side, entry=t_entry, entry_ts=entry_ts,
                             stop=t_entry * (1e-6 if t_side == "LONG" else 1e6),
                             plan=ExitPlan(target_rr=None, tsl_method=plan.tsl_method, tsl_trigger=plan.tsl_trigger,
                                           method_params=plan.method_params),
                             bars=tsl_chart["bars"], minutes=tsl_chart["minutes"], exit_time=exit_time,
                             history=tsl_chart.get("history", ()), live=live, entry_at_bar_close=entry_at_bar_close)
        if probe is not None and probe.result == "TSL":
            forced_ts, forced_detail = probe.exit_time, f"{probe.detail} ({tsl_chart.get('label', 'other')} chart)"
    use_tsl = plan.uses_tsl and tsl_chart is None
    short = side.upper() == "SHORT"
    sign = 1 if short else -1
    o_bars, o_min = _view(bars, sign), _view(minutes, sign)
    o_entry, o_stop = sign * entry, sign * stop
    risk = o_stop - o_entry
    if risk <= 0:
        return None
    tf = (bars[1].timestamp - bars[0].timestamp) if len(bars) > 1 else 300
    step = step_of(minutes)
    target = None if plan.target_rr is None else o_entry - plan.target_rr * risk
    day = datetime.fromtimestamp(entry_ts, IST).date()
    cutoff = int(datetime.combine(day, time.fromisoformat(exit_time), tzinfo=IST).timestamp())

    tsl_at: dict[int, tuple] = {}                           # candle end -> (index, value or None, flip)
    if use_tsl and bars:
        kind, params = plan.method()
        warm = len(history)
        points = method_stops(kind, params, list(history) + list(bars), side.upper(), entry_price=entry)[warm:]
        for k, (bar, point) in enumerate(zip(bars, points)):
            value = None if point.stop is None else sign * point.stop
            tsl_at[int(bar.timestamp) + tf] = (k, value, point.against)
    tsl = None
    for end in sorted(e for e in tsl_at if e <= entry_ts):   # the method's value when the trade starts
        k, value, _ = tsl_at[end]
        tsl = value if value is not None and value > o_bars[k].close else None

    exit_price, exit_ts, result, detail = None, None, "TIME", ""
    best = o_entry
    after = [m for m in o_min if m.timestamp > entry_ts and m.timestamp < cutoff]
    entry_end = entry_ts if entry_at_bar_close else entry_ts + step
    if entry_end in tsl_at:                                 # the entry candle closes in the entry minute
        k, value, _ = tsl_at[entry_end]
        if value is not None and value > o_bars[k].close:
            tsl = value if tsl is None else min(tsl, value)
    last_close = o_entry
    for m in after:
        if forced_ts is not None and m.timestamp >= forced_ts:            # the TSL on the other chart said out
            exit_price, exit_ts, result, detail = last_close, forced_ts, "TSL", forced_detail
            break
        last_close = m.close
        if m.high >= o_stop:
            exit_price, exit_ts, result, detail = max(o_stop, m.open), m.timestamp, "STOP", stop_label
            break
        if target is not None and m.low <= target:
            exit_price, exit_ts, result, detail = target, m.timestamp, "TARGET", f"1:{plan.target_rr:g}"
            break
        best = min(best, m.low)
        if use_tsl and plan.tsl_trigger == "TOUCH" and tsl is not None and m.high >= tsl:
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
    if exit_price is None and forced_ts is not None and forced_ts < cutoff:   # no later candle here yet
        exit_price, exit_ts, result, detail = last_close, forced_ts, "TSL", forced_detail
    if exit_price is None:
        before = [m for m in o_min if m.timestamp <= entry_ts]
        last = after[-1] if after else (before[-1] if before else _C(entry_ts, o_entry, o_entry, o_entry, o_entry))
        exit_price, exit_ts = last.close, last.timestamp
        if live and (not after or after[-1].timestamp + step < cutoff):
            result = "OPEN"
    won = o_entry - exit_price
    return Outcome(side.upper(), entry_ts, sign * o_entry, sign * o_stop, round(risk, 4), plan.target_rr,
                   None if target is None else sign * target, exit_ts, sign * exit_price, result, detail,
                   round(won, 4), round(won / risk, 3), round((o_entry - best) / risk, 3))


__all__ = ["Outcome", "manage_trade", "step_of"]
