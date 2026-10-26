"""Strict per-day quality check for 1-minute (or N-minute) session candles.

A day is CLEAN only if, inside 09:15-15:29 IST, it has:
  * every expected candle (no missing minute), no duplicates,
  * valid prices (positive, low <= open/close <= high),
  * no frozen feed (10+ identical candles in a row),
  * no impossible jump (one candle moving > SPIKE_PCT of price).
Bars after the cut-off (Yahoo stamps the official closing price on the last
minutes) are dropped by ``session_cut`` before checking, and reported.

STOCK rules (owner 26 Oct 2026, "3 months of clean data, not 1 year of broken data"): a stock may skip a minute
when nobody trades it, so a stock day may miss up to 3 minutes, but NONE of the first 15 (09:15-09:29: the open,
the gap and the first candles are what the stock strategies read); spikes count above 8% in one minute (a real
gap stock can move 2-5%); only minutes up to 15:14 count (all strategies are out by 15:10; Yahoo stops stocks
at 15:15); no frozen-feed check (a quiet stock can repeat a price). A split / bonus day (overnight
price change near 1/2, 1/3, 1/5, 1/10, 2/3 ...) and the 3 days after it are not clean (unadjusted prices).

Same checks as downloader/quality.py (duplicates, order, OHLC, completeness),
but on plain candle lists so any source (Yahoo, FYERS, local DB) can use it.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, time
from typing import Iterable, Sequence
from zoneinfo import ZoneInfo

from market_data.resampling import Candle

IST = ZoneInfo("Asia/Kolkata")
SESSION_OPEN = time(9, 15)
SESSION_LAST = time(15, 29)
TRADING_UNTIL = time(15, 10)   # a cut earlier than this makes the day unusable
SPIKE_PCT = 2.0          # one 1-minute candle moving more than 2% of price = bad data
FROZEN_RUN = 10          # 10 identical candles in a row = frozen feed


@dataclass(frozen=True)
class Rules:
    max_missing: int = 0              # missing minutes a day may have and still be clean
    open_minutes: int = 0             # the first N minutes must ALL be there
    spike_pct: float = SPIKE_PCT
    check_frozen: bool = True
    check_until: time | None = None   # STOCK: only up to 15:14 (every strategy is out by 15:10)


INDEX_RULES = Rules()
STOCK_RULES = Rules(max_missing=3, open_minutes=15, spike_pct=8.0, check_frozen=False, check_until=time(15, 14))
SPLIT_RATIOS = (1 / 2, 1 / 3, 1 / 4, 1 / 5, 1 / 10, 2 / 3, 3 / 4, 2 / 5)
AFTER_ACTION_DAYS = 3


@dataclass(frozen=True)
class DayQuality:
    day: date
    expected: int
    actual: int
    missing: int
    duplicates: int
    bad_ohlc: int
    spikes: int
    frozen_runs: int
    cut_after: str | None = None          # e.g. "15:14" when a dead tail was removed
    cut_too_early: bool = False          # e.g. "15:27" when closing artifacts were removed
    missing_times: tuple[str, ...] = field(default=(), compare=False)
    allowed_missing: int = 0              # STOCK rules: a few quiet minutes are fine
    open_missing: int = 0                 # missing minutes in the opening window (never fine)
    corporate_action: str = ""            # e.g. "split/bonus x0.50 on 2026-09-12"

    @property
    def clean(self) -> bool:
        return not (self.missing > self.allowed_missing or self.open_missing or self.duplicates or self.bad_ohlc
                    or self.spikes or self.frozen_runs or self.cut_too_early or self.corporate_action)

    @property
    def reason(self) -> str:
        if self.clean:
            return "CLEAN" + (f" (cut after {self.cut_after})" if self.cut_after else "")
        parts = []
        if self.corporate_action:
            parts.append(self.corporate_action)
        if self.open_missing:
            parts.append(f"{self.open_missing} missing in the first minutes")
        if self.missing > self.allowed_missing:
            sample = ", ".join(self.missing_times[:3]) + ("..." if len(self.missing_times) > 3 else "")
            parts.append(f"{self.missing} missing ({sample})")
        if self.cut_too_early:
            parts.append(f"feed stopped at {self.cut_after}")
        for name in ("duplicates", "bad_ohlc", "spikes", "frozen_runs"):
            if getattr(self, name):
                parts.append(f"{getattr(self, name)} {name.replace('_', ' ')}")
        return "; ".join(parts)


def _local(ts: int) -> datetime:
    return datetime.fromtimestamp(int(ts), IST)


def group_by_day(candles: Iterable[Candle]) -> dict[date, list[Candle]]:
    days: dict[date, list[Candle]] = defaultdict(list)
    for candle in candles:
        local = _local(candle.timestamp)
        if SESSION_OPEN <= local.time() <= SESSION_LAST:
            days[local.date()].append(candle)
    return dict(days)


def closing_artifact_cut(day_candles: Sequence[Candle], *, min_flat: int = 3, max_active: int = 2) -> time | None:
    """Find a dead tail at the end of the day and return the last live minute.

    Some feeds (Yahoo NIFTY/BANKNIFTY) stop updating near the close: the last
    10-15 candles repeat one price, then the official closing price is stamped
    on the final minutes. Walking back from the end, the tail is the stretch
    that is almost all flat candles (open = high = low = close); at most
    ``max_active`` non-flat candles (the stamped-close jump) are tolerated.
    """
    bars = sorted(day_candles, key=lambda c: c.timestamp)
    if len(bars) < 30:
        return None
    flat = [b.open == b.high == b.low == b.close for b in bars]
    best_start, flats, active = None, 0, 0
    for i in range(len(bars) - 1, 0, -1):
        if flat[i]:
            flats += 1
        else:
            active += 1
            if active > max_active:
                break
        if flat[i] and flats >= min_flat:
            best_start = i
    if best_start is None:
        return None
    return _local(bars[best_start - 1].timestamp).time()


def assess_day(day: date, day_candles: Sequence[Candle], *, minutes: float = 1,
               cut_after: time | None = None, rules: Rules = INDEX_RULES) -> DayQuality:
    open_ts = int(datetime.combine(day, SESSION_OPEN, tzinfo=IST).timestamp())
    last = cut_after or rules.check_until or SESSION_LAST
    last_ts = int(datetime.combine(day, last, tzinfo=IST).timestamp())
    expected = list(range(open_ts, last_ts + 1, int(round(60 * minutes))))
    if minutes < 1:   # seconds candles: the last minute holds several bars
        expected = list(range(open_ts, last_ts + 60, int(round(60 * minutes))))
        last_ts += 59
    bars = [c for c in day_candles if open_ts <= c.timestamp <= last_ts]
    seen: dict[int, int] = defaultdict(int)
    for c in bars:
        seen[c.timestamp] += 1
    missing = [ts for ts in expected if ts not in seen]
    duplicates = sum(n - 1 for n in seen.values() if n > 1)
    ordered = sorted({c.timestamp: c for c in bars}.values(), key=lambda c: c.timestamp)
    bad = sum(1 for c in ordered if min(c.open, c.high, c.low, c.close) <= 0
              or c.low > min(c.open, c.close) or c.high < max(c.open, c.close))
    spikes = sum(1 for a, b in zip(ordered, ordered[1:])
                 if a.close > 0 and abs(b.close - a.close) / a.close * 100 > rules.spike_pct * minutes ** 0.5)
    frozen, run, frozen_limit = 0, 1, max(FROZEN_RUN, int(FROZEN_RUN / minutes))
    for a, b in zip(ordered, ordered[1:]) if rules.check_frozen else ():
        run = run + 1 if (a.open, a.high, a.low, a.close) == (b.open, b.high, b.low, b.close) else 1
        if run == frozen_limit:
            frozen += 1
    open_end = open_ts + 60 * rules.open_minutes
    open_missing = sum(1 for ts in missing if ts < open_end)
    return DayQuality(
        day=day, expected=len(expected), actual=len(seen), missing=len(missing), duplicates=duplicates,
        bad_ohlc=bad, spikes=spikes, frozen_runs=frozen,
        cut_after=cut_after.strftime("%H:%M") if cut_after else None,
        cut_too_early=bool(cut_after and cut_after < TRADING_UNTIL),
        missing_times=tuple(_local(ts).strftime("%H:%M") for ts in missing),
        allowed_missing=int(rules.max_missing * (1 if minutes >= 1 else 0) / max(1.0, minutes)),
        open_missing=open_missing,
    )


def corporate_action_days(days: dict[date, list[Candle]]) -> dict[date, str]:
    """Days whose open is the previous close times a split / bonus ratio (FYERS prices are not adjusted)."""
    out: dict[date, str] = {}
    order = sorted(days)
    for prev, day in zip(order, order[1:]):
        p_close = max(days[prev], key=lambda c: c.timestamp).close
        d_open = min(days[day], key=lambda c: c.timestamp).open
        if p_close <= 0 or d_open <= 0:
            continue
        ratio = d_open / p_close
        if abs(ratio - 1) < 0.15:
            continue
        for r in SPLIT_RATIOS:
            for x in (r, 1 / r):
                if abs(ratio / x - 1) < 0.03:
                    out[day] = f"split/bonus x{ratio:.2f} on {day.isoformat()}"
    return out


def assess_series(candles: Iterable[Candle], *, minutes: float = 1, fix_closing_artifact: bool = True,
                  rules: Rules = INDEX_RULES) -> tuple[list[DayQuality], list[Candle]]:
    """Quality of every day, and the CLEAN candles only (artifact minutes removed)."""
    from dataclasses import replace
    reports, clean = [], []
    grouped = group_by_day(candles)
    actions: dict[date, str] = {}
    if rules is STOCK_RULES:
        order = sorted(grouped)
        for day, why in corporate_action_days(grouped).items():
            k = order.index(day)
            for d in order[k:k + 1 + AFTER_ACTION_DAYS]:
                actions.setdefault(d, why)
    for day, bars in sorted(grouped.items()):
        cut = closing_artifact_cut(bars) if fix_closing_artifact and minutes == 1 else None
        report = assess_day(day, bars, minutes=minutes, cut_after=cut, rules=rules)
        if day in actions:
            report = replace(report, corporate_action=actions[day])
        reports.append(report)
        if report.clean:
            limit = cut or SESSION_LAST
            clean.extend(sorted((b for b in bars if _local(b.timestamp).time() <= limit),
                                key=lambda b: b.timestamp))
    return reports, clean


def longest_clean_stretch(reports: Sequence[DayQuality]) -> tuple[date | None, date | None, int]:
    """Longest run of consecutive trading days (in the data) that are all clean."""
    best = (None, None, 0)
    start, count = None, 0
    for report in reports:
        if report.clean:
            start, count = (start or report.day), count + 1
            if count > best[2]:
                best = (start, report.day, count)
        else:
            start, count = None, 0
    return best


__all__ = ["DayQuality", "INDEX_RULES", "Rules", "STOCK_RULES", "assess_day", "assess_series", "closing_artifact_cut",
           "corporate_action_days", "group_by_day", "longest_clean_stretch"]
