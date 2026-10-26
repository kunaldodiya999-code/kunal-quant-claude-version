"""Report card engine (owner 26 Oct 2026): every strategy x every exit plan on the shared FYERS data, in rupees.

Money rules (owner): capital Rs 10,00,000, Rs 30,000 per trade. Clean days only.
  * Index options (KTMI Uni Lite, Opening Scalp): the backtest moves on the INDEX (no historical option candles for
    these days); the option is ESTIMATED: ATM premium ~ PREMIUM_PCT of spot, premium moves DELTA x index points,
    SLIPPAGE premium points per round trip, real option charges (paper_trading/costs.py). No time decay: a slow
    trade looks better than it would be. Initial stop = 30% of the premium (the live rule) = 0.36% of the index.
  * Stocks (Gap Reversal, Open High Low): the stock itself, intraday, real equity charges (backtest/equity_costs.py).
Every trade row is tagged with: entry hour, India VIX at the open (regime LOW / NORMAL / HIGH by terciles), VIX
up/down vs the previous close, and the NIFTY day type (TREND / RANGE) - the day type is only known after the close
(explains results, cannot be used as a filter); the VIX at the open IS known before trading.
"""

from __future__ import annotations

import bisect
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from statistics import median
from typing import Callable, Iterable, Optional, Sequence
from zoneinfo import ZoneInfo

from market_data.day_quality import group_by_day
from paper_trading.costs import OptionCostModel
from paper_trading.trade_management import session_bars
from paper_trading.tsl_methods import PRESET_LABELS, PRESETS
from strategies.exit_plan import NO_TSL, ExitPlan

IST = ZoneInfo("Asia/Kolkata")
CAPITAL = 1_000_000
PER_TRADE = 30_000
MAX_OPEN = CAPITAL // PER_TRADE              # 33 trades open at the same time at most
PREMIUM_PCT = 0.6
DELTA = 0.5
STOP_PREMIUM_PCT = 30.0
SLIPPAGE_POINTS = 1.0                        # premium points lost per round trip (spread)
LOTS = {"NIFTY": 65, "BANKNIFTY": 30, "SENSEX": 20}
RR_CHOICES = (1.5, 2.0, 2.5, 3.0)
HOURS = ("09:15-10:00", "10:00-11:00", "11:00-12:00", "12:00-13:00", "13:00-14:00", "14:00-15:30")


def exit_plans() -> list[tuple[str, ExitPlan]]:
    """The same list for every strategy: fixed targets 1:1.5 .. 1:3 (hard stop only) and each TSL method alone."""
    plans = [(f"1:{rr:g}", ExitPlan(target_rr=rr, tsl_method=NO_TSL)) for rr in RR_CHOICES]
    return plans + [(f"TSL {key}", ExitPlan(target_rr=None, tsl_method=key)) for key in PRESETS]


def describe_exit(label: str) -> tuple[str, str, str]:
    """(kind, plain name, short name) of an exit label."""
    if label.startswith("TSL "):
        key = label[4:]
        return "TSL", PRESET_LABELS.get(key, key), key
    if label.startswith("1:"):
        return "Fixed RR", f"Fixed target {label} (stop = the strategy's stop)", label
    return "Own rule", label, label


def hour_bucket(clock: str) -> str:
    h, m = (int(x) for x in clock.split(":"))
    if h < 10:
        return HOURS[0]
    return HOURS[min(h - 9, len(HOURS) - 1)]


def _ts(day: str, clock: str) -> int:
    return int(datetime.combine(date.fromisoformat(day), datetime.strptime(clock, "%H:%M").time(),
                                tzinfo=IST).timestamp())


# ------------------------------------------------------------------ market regime (VIX, NIFTY day type)
@dataclass(frozen=True)
class DayRegime:
    vix_open: Optional[float]
    vix_regime: str           # LOW / NORMAL / HIGH (terciles of the period), "?" when unknown
    vix_move: str             # "VIX up" / "VIX down" at the open vs the previous close
    day_type: str             # TREND / RANGE (NIFTY: |close - open| >= half the day's range)
    nifty_range_pct: float
    nifty_change_pct: float


def regimes(nifty: Sequence, vix: Sequence) -> tuple[dict[date, DayRegime], dict]:
    n_days = group_by_day(nifty)
    v_days = group_by_day(vix)
    opens = {d: c[0].open for d, c in v_days.items() if c}
    closes = {d: c[-1].close for d, c in v_days.items() if c}
    levels = sorted(opens.values())
    lo = levels[len(levels) // 3] if levels else None
    hi = levels[2 * len(levels) // 3] if levels else None
    out = {}
    order = sorted(set(n_days) | set(opens))
    prev_close = None
    for d in order:
        v = opens.get(d)
        regime = "?" if v is None or lo is None else ("LOW" if v < lo else "HIGH" if v >= hi else "NORMAL")
        move = "?" if v is None or prev_close is None else ("VIX up" if v > prev_close else "VIX down")
        prev_close = closes.get(d, prev_close)
        bars = n_days.get(d)
        if bars:
            o, c = bars[0].open, bars[-1].close
            h, l_ = max(b.high for b in bars), min(b.low for b in bars)
            eff = abs(c - o) / (h - l_) if h > l_ else 0
            out[d] = DayRegime(v, regime, move, "TREND" if eff >= 0.5 else "RANGE",
                               round((h - l_) / o * 100, 2), round((c - o) / o * 100, 2))
        else:
            out[d] = DayRegime(v, regime, move, "?", 0.0, 0.0)
    return out, {"vix_low_below": lo, "vix_high_from": hi}


# ------------------------------------------------------------------ index options (estimated from the index)
def option_money(index: str, spot: float, index_points: float) -> tuple[float, float, int]:
    """(gross Rs, charges Rs, quantity) of a bought ATM option for an index move of ``index_points``."""
    premium = spot * PREMIUM_PCT / 100
    lot = LOTS.get(index, 50)
    lots = max(1, int(PER_TRADE // (premium * lot)))
    qty = lots * lot
    move = max(-premium, DELTA * index_points) - SLIPPAGE_POINTS
    exit_premium = max(0.05, premium + move)
    costs = OptionCostModel()
    charges = costs.order_cost(side="BUY", price=premium, quantity=qty) + \
        costs.order_cost(side="SELL", price=exit_premium, quantity=qty)
    return (exit_premium - premium) * qty, charges, qty


def ktmi_trades(index: str, everything: Sequence, clean: Sequence, *, timeframe: int,
                exits: list[tuple[str, ExitPlan]], warmup_days: int = 3, exit_time: str = "15:10") -> list[dict]:
    """KTMI Uni Lite (locked rule UNI_LITE_CORE) on one index and signal timeframe, every exit plan."""
    from research.ktmi_accuracy import find_signals
    from strategies.trade_sim import manage_trade
    clean_days = sorted(group_by_day(clean))
    by_day = group_by_day(everything)
    days = sorted(by_day)
    bars_by_day = {d: session_bars(by_day[d], timeframe) for d in days}
    rows = []
    for sig in find_signals(everything, index=index, timeframe=timeframe, clean_days=clean_days):
        day = datetime.fromtimestamp(sig.decision_ts, IST).date()
        mins = by_day.get(day, [])
        times = [m.timestamp for m in mins]
        i = bisect.bisect_left(times, sig.decision_ts)
        if i >= len(mins):
            continue
        entry = mins[i].open
        side = sig.direction
        risk = entry * PREMIUM_PCT / 100 * STOP_PREMIUM_PCT / 100 / DELTA
        stop = entry - risk if side == "LONG" else entry + risk
        k = days.index(day)
        history = [b for d in days[max(0, k - warmup_days):k] for b in bars_by_day[d]]
        for label, plan in exits:
            out = manage_trade(side=side, entry=entry, entry_ts=sig.decision_ts, stop=stop, plan=plan,
                               bars=bars_by_day[day], minutes=mins, exit_time=exit_time, history=history,
                               entry_at_bar_close=True, stop_label="30% premium stop")
            if out is None:
                continue
            gross, charges, qty = option_money(index, entry, out.points)
            rows.append(_row("KTMI Uni Lite", f"{index} {timeframe}-min", "Index option (estimate)", index,
                             day.isoformat(), side, sig.decision_ts, out.exit_time, label, f"{timeframe}m",
                             out.r_multiple, gross, charges, out.result, qty))
    return rows


def opening_scalp_trades(index: str, clean: Sequence) -> list[dict]:
    """Opening Scalp (research only, OFF live) with its default setting, as an index option estimate."""
    from research.opening_scalp_backtest import run_days
    from strategies.opening_scalp import OpeningScalpConfig
    rows = []
    for t in run_days(group_by_day(clean), OpeningScalpConfig(), index=index):
        entry_ts, exit_ts = _ts(t["day"], t["entry_time"]), _ts(t["day"], t["exit_time"])
        gross, charges, qty = option_money(index, t["entry"], t["points"])
        r = t["points"] / t["stop"] if t["stop"] else 0.0
        rows.append(_row("Opening Scalp (research)", f"{index}", "Index option (estimate)", index, t["day"],
                         t["direction"], entry_ts, exit_ts, "Own target / stop", "1m", round(r, 3), gross, charges,
                         t["result"], qty))
    return rows


# ------------------------------------------------------------------ stocks
def stock_rows(strategy: str, variant: str, trades: Iterable[dict], timeframe: str) -> list[dict]:
    out = []
    for t in trades:
        out.append(_row(strategy, variant, "Stock (intraday)", t["symbol"], t["day"], t["side"],
                        _ts(t["day"], t["entry_time"]), _ts(t["day"], t["exit_time"]), t["exit"], timeframe,
                        float(t["r"]), float(t["gross_pnl"]), float(t["charges"]), t["result"], int(t["quantity"])))
    return out


def gap_reversal_trades(series: dict, allowed: dict, *, gap_pct: float, timeframe: int,
                        exits: list[tuple[str, ExitPlan]]) -> list[dict]:
    from research.gap_reversal_backtest import apply_daily_cap, run_symbol
    from strategies.gap_reversal import GapReversalSettings
    s = replace(GapReversalSettings(), gap_pct=gap_pct, timeframe=timeframe)
    trades = []
    for stock, minutes in series.items():
        trades += run_symbol(stock, minutes, s, exits=exits, capital_per_trade=PER_TRADE,
                             trade_days=allowed.get(stock, set()))[1]
    trades = apply_daily_cap(trades, s)
    rows = []
    for mode in ("BREAK", "CLOSE"):
        rows += stock_rows("Gap Reversal", f"gap >= {gap_pct:g}%, {timeframe}-min, entry {mode}",
                           [t for t in trades if t["entry_mode"] == mode], f"{timeframe}m")
    return rows


def open_high_low_trades(series: dict, allowed: dict, *, variant: str, first_candle: int = 5,
                         vwap: bool = False, bb: bool = False) -> list[dict]:
    from research.open_high_low_backtest import run
    from strategies.open_high_low import OpenHighLowSettings
    s = replace(OpenHighLowSettings(), first_candle_minutes=first_candle, vwap_filter=vwap, bb_filter=bb)
    _cands, trades = run(series, replace(s, top_n=s.top_n), capital_per_trade=PER_TRADE, trade_days=allowed)
    trades = [t for t in trades if t["rank"] <= s.top_n]
    return stock_rows("Open High Low", variant, trades, f"{s.timeframe}m")


# ------------------------------------------------------------------ rows, tags, statistics
def _row(strategy, variant, market, symbol, day, side, entry_ts, exit_ts, exit_label, timeframe, r, gross, charges,
         result, qty) -> dict:
    kind, name, short = describe_exit(exit_label)
    return {"strategy": strategy, "variant": variant, "market": market, "symbol": symbol, "day": day, "side": side,
            "entry_ts": int(entry_ts), "exit_ts": int(exit_ts),
            "entry_time": datetime.fromtimestamp(entry_ts, IST).strftime("%H:%M"),
            "exit_time": datetime.fromtimestamp(exit_ts, IST).strftime("%H:%M"),
            "exit": exit_label, "exit_kind": kind, "exit_name": name, "exit_short": short, "timeframe": timeframe,
            "r": round(float(r), 3), "gross": round(gross, 2), "charges": round(charges, 2),
            "net": round(gross - charges, 2), "result": result, "quantity": qty}


def tag(rows: list[dict], days: dict[date, DayRegime]) -> list[dict]:
    for r in rows:
        g = days.get(date.fromisoformat(r["day"]))
        r["hour"] = hour_bucket(r["entry_time"])
        r["vix_regime"] = g.vix_regime if g else "?"
        r["vix_move"] = g.vix_move if g else "?"
        r["day_type"] = g.day_type if g else "?"
    return rows


def stats(rows: Sequence[dict], all_days: Sequence[str] = ()) -> dict:
    nets = [r["net"] for r in rows]
    if not nets:
        return {"trades": 0}
    wins = [x for x in nets if x > 0]
    losses = [-x for x in nets if x <= 0]
    pf = round(sum(wins) / sum(losses), 2) if losses and sum(losses) > 0 else (99.0 if wins else 0.0)
    by_day: dict[str, float] = {}
    for r in rows:
        by_day[r["day"]] = by_day.get(r["day"], 0) + r["net"]
    days = sorted(set(all_days) | set(by_day)) if all_days else sorted(by_day)
    half = len(days) // 2
    first = sum(by_day.get(d, 0) for d in days[:half])
    second = sum(by_day.get(d, 0) for d in days[half:])
    streak = worst = 0
    for x in nets:
        streak = streak + 1 if x <= 0 else 0
        worst = max(worst, streak)
    return {"trades": len(nets), "win_pct": round(100 * len(wins) / len(nets), 1), "pf": pf,
            "net": round(sum(nets), 0), "avg": round(sum(nets) / len(nets), 0),
            "avg_r": round(sum(r["r"] for r in rows) / len(rows), 3),
            "charges": round(sum(r["charges"] for r in rows), 0),
            "best": round(max(nets), 0), "worst": round(min(nets), 0), "max_losing_run": worst,
            "first_half": round(first, 0), "second_half": round(second, 0),
            "stable": first > 0 and second > 0, "trade_days": len(by_day)}


def portfolio(rows: Sequence[dict], *, capital: float = CAPITAL, max_open: int = MAX_OPEN) -> dict:
    """Rs 10 lakh, Rs 30,000 per trade, at most 33 open at once; a trade that finds no free money is skipped."""
    order = sorted(rows, key=lambda r: (r["entry_ts"], r["symbol"]))
    open_exits: list[int] = []
    taken, skipped = [], 0
    for r in order:
        open_exits = [e for e in open_exits if e > r["entry_ts"]]
        if len(open_exits) >= max_open:
            skipped += 1
            continue
        open_exits.append(r["exit_ts"])
        taken.append(r)
    by_day: dict[str, float] = {}
    for r in taken:
        by_day[r["day"]] = by_day.get(r["day"], 0) + r["net"]
    equity, peak, dd, curve = capital, capital, 0.0, []
    for d in sorted(by_day):
        equity += by_day[d]
        peak = max(peak, equity)
        dd = max(dd, peak - equity)
        curve.append((d, round(equity, 0)))
    net = equity - capital
    green = sum(1 for v in by_day.values() if v > 0)
    return {"taken": len(taken), "skipped": skipped, "net": round(net, 0), "return_pct": round(100 * net / capital, 2),
            "max_dd": round(dd, 0), "max_dd_pct": round(100 * dd / capital, 2),
            "return_to_dd": round(net / dd, 2) if dd > 0 else (99.0 if net > 0 else 0.0),
            "green_days_pct": round(100 * green / len(by_day), 1) if by_day else 0.0,
            "best_day": round(max(by_day.values()), 0) if by_day else 0,
            "worst_day": round(min(by_day.values()), 0) if by_day else 0, "curve": curve}


def stars(s: dict, p: dict) -> int:
    """1-5 stars: profit factor first; one star off when it is not stable in both halves or has few trades."""
    if not s.get("trades"):
        return 0
    pf = s["pf"]
    n = 1 if pf < 0.9 else 2 if pf < 1.1 else 3 if pf < 1.3 else 4 if pf < 1.6 else 5
    if pf >= 1.1 and (not s["stable"] or s["trades"] < 30):
        n -= 1
    return max(1, n)


def group(rows: Sequence[dict], keys: Sequence[str]) -> dict[tuple, list[dict]]:
    out: dict[tuple, list[dict]] = {}
    for r in rows:
        out.setdefault(tuple(r[k] for k in keys), []).append(r)
    return out


def rank_combos(rows: Sequence[dict], all_days: Sequence[str], *, min_trades: int = 10) -> list[dict]:
    """Every strategy x variant x exit plan: stats, Rs 10 lakh portfolio, stars; best first."""
    table = []
    for (strategy, variant, exit_label), rs in group(rows, ("strategy", "variant", "exit")).items():
        s = stats(rs, all_days)
        if s["trades"] < min_trades:
            continue
        p = portfolio(rs)
        kind, name, short = describe_exit(exit_label)
        table.append({"strategy": strategy, "variant": variant, "exit": exit_label, "exit_kind": kind,
                      "exit_name": name, "market": rs[0]["market"], "timeframe": rs[0]["timeframe"], **s,
                      "return_pct": p["return_pct"], "max_dd": p["max_dd"], "max_dd_pct": p["max_dd_pct"],
                      "return_to_dd": p["return_to_dd"], "green_days_pct": p["green_days_pct"],
                      "skipped": p["skipped"], "stars": stars(s, p), "curve": p["curve"]})
    table.sort(key=lambda x: (-x["stars"], -x["net"], -x["return_to_dd"]))   # same capital: rupees decide
    for n, row in enumerate(table, 1):
        row["rank"] = n
    return table


def walk_forward(rows: Sequence[dict], all_days: Sequence[str]) -> list[dict]:
    """Per strategy family: the exit plan that was best in the FIRST half, and how it did in the unseen SECOND half."""
    days = sorted(all_days)
    half = set(days[: len(days) // 2])
    out = []
    for (strategy, variant), rs in group(rows, ("strategy", "variant")).items():
        first = group([r for r in rs if r["day"] in half], ("exit",))
        second = group([r for r in rs if r["day"] not in half], ("exit",))
        if not first or not second:
            continue
        pick = max(first, key=lambda k: sum(r["net"] for r in first[k]))
        best2 = max(second, key=lambda k: sum(r["net"] for r in second[k]))
        out.append({"strategy": strategy, "variant": variant, "picked_exit": pick[0],
                    "first_half_net": round(sum(r["net"] for r in first[pick]), 0),
                    "second_half_net": round(sum(r["net"] for r in second.get(pick, [])), 0),
                    "second_half_best_exit": best2[0],
                    "second_half_best_net": round(sum(r["net"] for r in second[best2]), 0)})
    return out


__all__ = ["CAPITAL", "HOURS", "MAX_OPEN", "PER_TRADE", "describe_exit", "exit_plans", "gap_reversal_trades",
           "group", "ktmi_trades", "open_high_low_trades", "opening_scalp_trades", "option_money", "portfolio",
           "rank_combos", "regimes", "stars", "stats", "tag", "walk_forward"]
