"""THE REPORT CARD: every strategy x every exit plan on the shared FYERS data, as one multi-page HTML page.

Run from C:\\Users\\USER\\Desktop\\Kunal\\kunal-quant-claude-version (after scripts\\fetch_data.py; no login needed):

    python scripts\\report_card.py
    python scripts\\report_card.py --days 90 --long-days 365      (the defaults)
    python scripts\\report_card.py --stocks RELIANCE,SBIN,TCS       (a quick try on a few stocks)

Money (owner 26 Oct 2026): capital Rs 10,00,000, Rs 30,000 per trade, at most 33 trades open at once.
Tested: KTMI Uni Lite (NIFTY, BANK NIFTY, SENSEX; 3, 5, 10, 15-min signals), Gap Reversal (gap >= 3% and >= 1%;
5 and 3-min candles; BREAK and CLOSE entry), Open High Low (plain, VWAP filter, Bollinger filter, 15-min first
candle), Opening Scalp (research). Exits: fixed 1:1.5, 1:2, 1:2.5, 1:3 and each TSL method alone. Clean days only.
Tags: hour of entry, India VIX at the open (LOW / NORMAL / HIGH), VIX up / down, NIFTY TREND / RANGE day.
Extra page: KTMI on 1 year of NIFTY (--long-days, 0 = skip).

Writes data\\research\\report_card\\:
  report_card.html   open it with a double click (works offline, several pages, every number explained)
  summary.txt        the key results in plain text (paste it to Claude)
  trades.csv, ranking.csv
"""

from __future__ import annotations

import argparse
import csv
import html
import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from research import report_card as rc  # noqa: E402

IST = ZoneInfo("Asia/Kolkata")
INDEXES = ("NIFTY", "BANKNIFTY", "SENSEX")
COLORS = ("#2563eb", "#dc2626", "#16a34a", "#d97706", "#7c3aed", "#0891b2", "#db2777", "#65a30d")


def say(text: str) -> None:
    print(f"[{datetime.now(IST):%H:%M:%S}] {text}", flush=True)


# ====================================================================== collect
def collect(args) -> dict:
    from market_data.clean_days import stock_candles, tradable_days
    from market_data.kq_store import KQStore, default_path
    from research.data_loader import load
    store = KQStore(args.kq_db or default_path())
    if not store.exists():
        raise SystemExit(f"Shared database not found: {store.path}. Run  python scripts\\fetch_data.py  first.")
    exits = rc.exit_plans()
    newest = store.saved_range("NIFTY")[1] or date.today()
    since = newest - timedelta(days=args.days)
    rows: list[dict] = []
    quality = {}
    frames = [int(x) for x in args.timeframes.split(",") if x.strip()]
    for index in INDEXES:
        everything, clean = load("fyers", index, kq_db=store.path, days=args.days)
        clean_days = sorted(d for d in {datetime.fromtimestamp(c.timestamp, IST).date() for c in clean} if d >= since)
        all_days = sorted({datetime.fromtimestamp(c.timestamp, IST).date() for c in everything} - {None})
        quality[index] = {"clean": len(clean_days), "days": len([d for d in all_days if d > since])}
        if not clean:
            say(f"{index}: no clean data, skipped")
            continue
        for tf in frames:
            got = rc.ktmi_trades(index, everything, clean, timeframe=tf, exits=exits)
            rows += got
            say(f"KTMI Uni Lite {index} {tf}-min: {len({(r['entry_ts'], r['side']) for r in got})} signals")
        if not args.no_scalp:
            rows += rc.opening_scalp_trades(index, clean)
    stocks = [x.strip().upper() for x in args.stocks.split(",") if x.strip()] or store.stocks()
    calendar = store.trading_days(since - timedelta(days=5))
    series, allowed, s_days, s_clean = {}, {}, 0, 0
    for n, stock in enumerate(stocks, 1):
        candles = stock_candles(store, stock, "1m", since=since - timedelta(days=5))
        if not candles:
            continue
        series[stock] = candles
        allowed[stock], counts = tradable_days(candles, calendar)
        s_days += counts["days"]
        s_clean += counts["tradable"]
        if n % 50 == 0:
            say(f"  stocks loaded: {n} of {len(stocks)}")
    quality["stocks"] = {"stocks": len(series), "stock_days": s_days, "tradable": s_clean}
    if series:
        for gap in (3.0, 1.0):
            for tf in (5, 3):
                got = rc.gap_reversal_trades(series, allowed, gap_pct=gap, timeframe=tf, exits=exits)
                rows += got
                say(f"Gap Reversal gap >= {gap:g}%, {tf}-min: {len(got) // len(exits)} trades (BREAK + CLOSE)")
        for variant, kwargs in (("plain (first 5-min candle)", {}), ("VWAP filter ON", {"vwap": True}),
                                ("Bollinger filter ON", {"bb": True}),
                                ("first candle 15 min", {"first_candle": 15})):
            got = rc.open_high_low_trades(series, allowed, variant=variant, **kwargs)
            rows += got
            say(f"Open High Low {variant}: {len(got) // len(exits)} trades")
    nifty, vix = store.load("NIFTY", since=since - timedelta(days=5)), store.load("INDIAVIX", since=since - timedelta(days=5))
    days_regime, thresholds = rc.regimes(nifty, vix)
    rc.tag(rows, days_regime)
    long_rows: list[dict] = []
    if args.long_days:
        everything, clean = load("fyers", "NIFTY", kq_db=store.path, days=args.long_days)
        for tf in (3, 5):
            long_rows += rc.ktmi_trades("NIFTY", everything, clean, timeframe=tf, exits=exits)
        rc.tag(long_rows, rc.regimes(everything, store.load("INDIAVIX"))[0])
        say(f"1-year NIFTY check: {len(long_rows) // len(exits)} trades")
    return {"rows": rows, "long_rows": long_rows, "quality": quality, "thresholds": thresholds,
            "regime": days_regime, "since": since, "newest": newest, "store": str(store.path)}


# ====================================================================== html helpers
def esc(x) -> str:
    return html.escape(str(x))


def rs(x) -> str:
    if x is None or x == "":
        return "-"
    v = float(x)
    sign = "-" if v < 0 else ""
    v = abs(round(v))
    s = f"{v:,}"
    if v >= 100000:                                      # Indian grouping: 1,23,45,678
        head, tail = str(v)[:-3], str(v)[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        s = ",".join([head] + parts) + "," + tail if head else ",".join(parts) + "," + tail
    return f"{sign}Rs {s}"


def cls(v) -> str:
    try:
        return "pos" if float(v) > 0 else "neg" if float(v) < 0 else ""
    except (TypeError, ValueError):
        return ""


def table(rows: list[dict], cols: list[tuple[str, str]], money=(), signed=(), limit: int | None = None) -> str:
    head = "".join(f"<th>{esc(t)}</th>" for _k, t in cols)
    body = []
    for r in rows[:limit] if limit else rows:
        cells = []
        for k, _t in cols:
            v = r.get(k, "")
            if k == "stars":
                cells.append(f"<td class='stars'>{'&#9733;' * int(v)}{'&#9734;' * (5 - int(v))}</td>")
            elif k in money:                                     # a drawdown is a size, not a gain: no colour
                cells.append(f"<td class='num {'' if 'dd' in k else cls(v)}'>{esc(rs(v))}</td>")
            elif k in signed:
                cells.append(f"<td class='num {cls(v)}'>{esc(v)}</td>")
            elif isinstance(v, bool):
                cells.append(f"<td>{'yes' if v else 'no'}</td>")
            elif isinstance(v, (int, float)):
                cells.append(f"<td class='num'>{esc(v)}</td>")
            else:
                cells.append(f"<td>{esc(v)}</td>")
        body.append("<tr>" + "".join(cells) + "</tr>")
    return f"<div class='tw'><table><thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody></table></div>"


def line_chart(curves: list[tuple[str, list]], title: str, width=900, height=300) -> str:
    curves = [(n, c) for n, c in curves if c]
    if not curves:
        return "<p class='muted'>No trades to draw.</p>"
    days = sorted({d for _n, c in curves for d, _v in c})
    xi = {d: i for i, d in enumerate(days)}
    vals = [v for _n, c in curves for _d, v in c] + [rc.CAPITAL]
    lo, hi = min(vals), max(vals)
    pad = (hi - lo) * 0.08 or 1000
    lo, hi = lo - pad, hi + pad
    L, R, T, B = 80, 20, 30, 40

    def x(i):
        return L + (width - L - R) * (i / max(1, len(days) - 1))

    def y(v):
        return T + (height - T - B) * (1 - (v - lo) / (hi - lo))
    parts = [f"<svg viewBox='0 0 {width} {height}' class='chart' role='img' aria-label='{esc(title)}'>",
             f"<text x='{L}' y='18' class='ct'>{esc(title)}</text>"]
    for k in range(5):
        v = lo + (hi - lo) * k / 4
        parts.append(f"<line x1='{L}' x2='{width - R}' y1='{y(v):.1f}' y2='{y(v):.1f}' class='grid'/>"
                     f"<text x='{L - 6}' y='{y(v) + 4:.1f}' class='ax' text-anchor='end'>{esc(rs(v))}</text>")
    parts.append(f"<line x1='{L}' x2='{width - R}' y1='{y(rc.CAPITAL):.1f}' y2='{y(rc.CAPITAL):.1f}' class='base'/>")
    for i, anchor in ((0, "start"), (len(days) // 2, "middle"), (len(days) - 1, "end")):
        parts.append(f"<text x='{x(i):.1f}' y='{height - 12}' class='ax' text-anchor='{anchor}'>{esc(days[i])}</text>")
    legend = []
    for n, (name, curve) in enumerate(curves):
        col = COLORS[n % len(COLORS)]
        pts = [(x(xi[curve[0][0]]) - 1, y(rc.CAPITAL))] + [(x(xi[d]), y(v)) for d, v in curve]
        parts.append(f"<polyline fill='none' stroke='{col}' stroke-width='2' "
                     f"points='{' '.join(f'{a:.1f},{b:.1f}' for a, b in pts)}'/>")
        legend.append(f"<span><i style='background:{col}'></i>{esc(name)}</span>")
    parts.append("</svg>")
    return "".join(parts) + f"<div class='legend'>{''.join(legend)}</div>"


def bar_chart(items: list[tuple[str, float]], title: str, width=900) -> str:
    if not items:
        return ""
    row_h, L = 26, 330
    height = 40 + row_h * len(items)
    m = max(abs(v) for _n, v in items) or 1
    mid = L + (width - L - 20) / 2
    half = (width - L - 20) / 2
    parts = [f"<svg viewBox='0 0 {width} {height}' class='chart' role='img' aria-label='{esc(title)}'>",
             f"<text x='10' y='18' class='ct'>{esc(title)}</text>",
             f"<line x1='{mid}' x2='{mid}' y1='28' y2='{height - 6}' class='base'/>"]
    for i, (name, v) in enumerate(items):
        yy = 32 + i * row_h
        w = half * abs(v) / m
        x0 = mid if v >= 0 else mid - w
        parts.append(f"<text x='{L - 8}' y='{yy + 15}' class='ax' text-anchor='end'>{esc(name[:48])}</text>"
                     f"<rect x='{x0:.1f}' y='{yy + 3}' width='{max(w, 1):.1f}' height='{row_h - 8}' "
                     f"class='{'bp' if v >= 0 else 'bn'}'/>"
                     f"<text x='{(mid + w + 6) if v >= 0 else (mid - w - 6):.1f}' y='{yy + 15}' class='ax' "
                     f"text-anchor='{'start' if v >= 0 else 'end'}'>{esc(rs(v))}</text>")
    parts.append("</svg>")
    return "".join(parts)


# ====================================================================== analysis for the pages
def best_per_family(ranking: list[dict]) -> dict[str, dict]:
    out = {}
    for r in ranking:                                    # ranking is best first
        out.setdefault(r["strategy"], r)
    return out


def pivot(rows: list[dict], combos: list[dict], key: str, values: list[str]) -> list[dict]:
    """For each chosen combo (strategy + variant + exit): net / trades / win % per value of ``key``."""
    out = []
    for c in combos:
        rs_ = [r for r in rows if r["strategy"] == c["strategy"] and r["variant"] == c["variant"]
               and r["exit"] == c["exit"]]
        line = {"combo": f"{c['strategy']} - {c['variant']} - {c['exit']}"}
        for v in values:
            sel = [r for r in rs_ if r[key] == v]
            s = rc.stats(sel)
            line[v] = f"{rs(s['net'])} ({s['trades']}, {s['win_pct']}%)" if s["trades"] else "-"
            line[v + "_net"] = s.get("net", 0)
        out.append(line)
    return out


def method_scores(ranking: list[dict], kind: str) -> list[dict]:
    """Each exit method of one kind: in how many strategy versions it was the best of its kind, its average place,
    and its total net over all of them."""
    fam: dict[tuple, list[dict]] = {}
    for r in ranking:
        if r["exit_kind"] == kind:
            fam.setdefault((r["strategy"], r["variant"]), []).append(r)
    score: dict[str, dict] = {}
    for rows in fam.values():
        ordered = sorted(rows, key=lambda r: -r["net"])
        for place, r in enumerate(ordered, 1):
            s = score.setdefault(r["exit"], {"exit": r["exit"], "name": r["exit_name"], "wins": 0, "places": [],
                                             "net": 0.0, "profitable": 0, "versions": 0})
            s["places"].append(place)
            s["net"] += r["net"]
            s["versions"] += 1
            s["profitable"] += r["net"] > 0
            if place == 1:
                s["wins"] += 1
    out = []
    for s in score.values():
        out.append({"exit": s["exit"], "name": s["name"], "best_in": s["wins"], "versions": s["versions"],
                    "avg_place": round(sum(s["places"]) / len(s["places"]), 2), "profitable_in": s["profitable"],
                    "total_net": round(s["net"], 0)})
    out.sort(key=lambda s: (s["avg_place"], -s["total_net"]))
    return out


def regime_table(regime: dict) -> list[dict]:
    out = []
    for name in ("LOW", "NORMAL", "HIGH"):
        days = [g for g in regime.values() if g.vix_regime == name and g.day_type != "?"]
        if not days:
            continue
        out.append({"vix": name, "days": len(days),
                    "trend_pct": round(100 * sum(g.day_type == "TREND" for g in days) / len(days), 1),
                    "avg_range": round(sum(g.nifty_range_pct for g in days) / len(days), 2),
                    "avg_abs_move": round(sum(abs(g.nifty_change_pct) for g in days) / len(days), 2)})
    return out


def suggestions(ranking, rows, fams, tsl_scores, rr_scores, tf_rows, hour_rows, vix_rows, trend_rows, wf) -> list[str]:
    tips = []
    good = [r for r in ranking if r["stars"] >= 4]
    if ranking:
        b = ranking[0]
        tips.append(f"Best overall: <b>{esc(b['strategy'])} - {esc(b['variant'])}</b> with exit <b>{esc(b['exit_name'])}"
                    f"</b>: {b['trades']} trades, win {b['win_pct']}%, profit factor {b['pf']}, net {esc(rs(b['net']))} "
                    f"({b['return_pct']}% of Rs 10 lakh), worst drawdown {esc(rs(b['max_dd']))}.")
    if not good:
        tips.append("No combination earned 4 stars. Treat every result as 'not proven yet': keep paper trading.")
    for name, best in fams.items():
        verdict = ("worth paper trading next" if best["stars"] >= 4 else "promising, needs more days" if best["stars"] == 3
                   else "not good enough on this data")
        tips.append(f"{esc(name)}: best version <b>{esc(best['variant'])}, {esc(best['exit_name'])}</b> "
                    f"({best['stars']} stars, net {esc(rs(best['net']))}) - {verdict}.")
    if tsl_scores:
        t = tsl_scores[0]
        tips.append(f"Trailing stop: <b>{esc(t['name'])}</b> had the best average place among the TSL methods "
                    f"(best in {t['best_in']} of {t['versions']} strategy versions, profitable in {t['profitable_in']}).")
    if rr_scores:
        t = rr_scores[0]
        tips.append(f"Fixed target: <b>{esc(t['exit'])}</b> had the best average place among the fixed targets "
                    f"(best in {t['best_in']} of {t['versions']}).")
    for line in tf_rows[:3]:
        tips.append(f"Timeframe, {esc(line['strategy'])}: best was <b>{esc(line['best'])}</b>.")
    for line in hour_rows:
        name = esc(line['combo'].split(' - ')[0])
        if line["best_hour"] == line["worst_hour"]:
            tips.append(f"Time of day, {name}: trades only in <b>{esc(line['best_hour'])}</b> (by design).")
        else:
            tips.append(f"Time of day, {name}: best hour <b>{esc(line['best_hour'])}</b>, worst hour "
                        f"<b>{esc(line['worst_hour'])}</b>.")
    for line in vix_rows:
        name = esc(line['combo'].split(' - ')[0])
        if line["best"] != line["worst"]:
            tips.append(f"India VIX, {name}: best when VIX was <b>{esc(line['best'])}</b>, worst when "
                        f"<b>{esc(line['worst'])}</b> (see the VIX page for the size of the difference).")
    for line in trend_rows:
        tips.append(f"Market type, {esc(line['combo'].split(' - ')[0])}: TREND days {esc(line['TREND'])}, "
                    f"RANGE days {esc(line['RANGE'])}.")
    held = [w for w in wf if w["second_half_net"] > 0]
    if wf:
        tips.append(f"Honesty check: choosing the exit on the first half of the days and trading it on the unseen second "
                    f"half stayed profitable in {len(held)} of {len(wf)} strategy versions (page 'Honesty check').")
    return tips


# ====================================================================== the page
CSS = """
:root{--bg:#f7f8fb;--card:#fff;--ink:#111827;--mut:#6b7280;--line:#e5e7eb;--acc:#2563eb;--pos:#15803d;--neg:#b91c1c}
@media (prefers-color-scheme:dark){:root{--bg:#0f172a;--card:#111827;--ink:#e5e7eb;--mut:#9ca3af;--line:#1f2937;
--acc:#60a5fa;--pos:#4ade80;--neg:#f87171}}
*{box-sizing:border-box}body{margin:0;font:15px/1.5 system-ui,Segoe UI,Arial,sans-serif;background:var(--bg);color:var(--ink)}
header{padding:18px 20px;background:var(--card);border-bottom:1px solid var(--line)}
h1{margin:0;font-size:22px}h2{font-size:19px;margin:6px 0 10px}h3{font-size:16px;margin:18px 0 6px}
nav{display:flex;flex-wrap:wrap;gap:6px;padding:10px 20px;background:var(--card);border-bottom:1px solid var(--line);
position:sticky;top:0;z-index:2}
nav button{border:1px solid var(--line);background:var(--bg);color:var(--ink);padding:6px 10px;border-radius:8px;cursor:pointer;font-size:14px}
nav button.on{background:var(--acc);color:#fff;border-color:var(--acc)}
main{max-width:1200px;margin:0 auto;padding:16px}section{display:none}section.on{display:block}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px 16px;margin:12px 0}
.muted{color:var(--mut)}.explain{background:var(--bg);border-left:4px solid var(--acc);padding:8px 12px;border-radius:6px}
.tw{overflow-x:auto}table{border-collapse:collapse;width:100%;font-size:13px}
th,td{padding:6px 8px;border-bottom:1px solid var(--line);text-align:left;white-space:nowrap}
th{position:sticky;top:0;background:var(--card)}td.num{text-align:right;font-variant-numeric:tabular-nums}
.pos{color:var(--pos)}.neg{color:var(--neg)}.stars{color:#d97706;letter-spacing:1px}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:10px}
.kpi{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:10px}
.kpi b{display:block;font-size:20px}.chart{width:100%;height:auto;background:var(--card)}
.chart .ct{font-size:14px;font-weight:600;fill:var(--ink)}.chart .ax{font-size:11px;fill:var(--mut)}
.chart .grid{stroke:var(--line)}.chart .base{stroke:var(--mut);stroke-dasharray:4 3}
.chart .bp{fill:var(--pos)}.chart .bn{fill:var(--neg)}
.legend{display:flex;flex-wrap:wrap;gap:12px;font-size:12px;margin:4px 0 8px}
.legend i{display:inline-block;width:12px;height:12px;border-radius:3px;margin-right:5px;vertical-align:-1px}
ul.tips li{margin:6px 0}
"""

JS = """
function show(id){document.querySelectorAll('section').forEach(s=>s.classList.toggle('on',s.id===id));
document.querySelectorAll('nav button').forEach(b=>b.classList.toggle('on',b.dataset.p===id));
try{localStorage.setItem('kq_rc_page',id)}catch(e){};window.scrollTo(0,0)}
document.querySelectorAll('nav button').forEach(b=>b.onclick=()=>show(b.dataset.p));
var start='summary';try{start=localStorage.getItem('kq_rc_page')||start}catch(e){};
if(!document.getElementById(start))start='summary';show(start);
"""

RANK_COLS = [("rank", "#"), ("stars", "Rating"), ("strategy", "Strategy"), ("variant", "Version"),
             ("exit_name", "Exit plan"), ("trades", "Trades"), ("win_pct", "Win %"), ("pf", "Profit factor"),
             ("avg", "Avg / trade"), ("net", "Net profit"), ("return_pct", "Return %"), ("max_dd", "Worst drawdown"),
             ("return_to_dd", "Return / drawdown"), ("green_days_pct", "Green days %"), ("stable", "Both halves +")]


def build_html(data: dict, ranking: list[dict], long_ranking: list[dict], wf: list[dict]) -> tuple[str, list[str]]:
    rows = data["rows"]
    fams = best_per_family(ranking)
    top_combos = list(fams.values())
    tsl_scores = method_scores(ranking, "TSL")
    rr_scores = method_scores(ranking, "Fixed RR")
    # timeframes
    tf_rows = []
    for strategy in fams:
        per_tf: dict[str, float] = {}
        for r in ranking:
            if r["strategy"] != strategy:
                continue
            key = r["variant"].split(", entry")[0] if strategy == "Gap Reversal" else r["variant"]
            if strategy == "KTMI Uni Lite":
                key = r["variant"].split(" ", 1)[1]
            per_tf[key] = max(per_tf.get(key, -1e18), r["net"])
        if per_tf:
            ordered = sorted(per_tf.items(), key=lambda kv: -kv[1])
            tf_rows.append({"strategy": strategy, "best": f"{ordered[0][0]} (best index / exit: {rs(ordered[0][1])})",
                            "all": "; ".join(f"{k}: {rs(v)}" for k, v in ordered)})
    hour_p = pivot(rows, top_combos, "hour", list(rc.HOURS))
    for line in hour_p:
        vals = {h: line[h + "_net"] for h in rc.HOURS if line[h] != "-"}
        line["best_hour"] = max(vals, key=vals.get) if vals else "-"
        line["worst_hour"] = min(vals, key=vals.get) if vals else "-"
    vix_p = pivot(rows, top_combos, "vix_regime", ["LOW", "NORMAL", "HIGH"])
    for line in vix_p:
        vals = {h: line[h + "_net"] for h in ("LOW", "NORMAL", "HIGH") if line[h] != "-"}
        line["best"] = max(vals, key=vals.get) if vals else "-"
        line["worst"] = min(vals, key=vals.get) if vals else "-"
    move_p = pivot(rows, top_combos, "vix_move", ["VIX up", "VIX down"])
    trend_p = pivot(rows, top_combos, "day_type", ["TREND", "RANGE"])
    tips = suggestions(ranking, rows, fams, tsl_scores, rr_scores, tf_rows, hour_p, vix_p, trend_p, wf)

    # combined portfolio of the strategies whose best version has >= 3 stars and held in both halves
    chosen = [c for c in top_combos if c["stars"] >= 3 and c["stable"]]
    combined_rows = [r for c in chosen for r in rows if r["strategy"] == c["strategy"] and r["variant"] == c["variant"]
                     and r["exit"] == c["exit"]]
    combined = rc.portfolio(combined_rows) if combined_rows else None
    q = data["quality"]
    th = data["thresholds"]
    sec = {}
    kpis = [("Data window", f"{data['since']} to {data['newest']}"),
            ("Clean index days", ", ".join(f"{k} {v['clean']}" for k, v in q.items() if k != "stocks")),
            ("Stocks / tradable stock-days", f"{q.get('stocks', {}).get('stocks', 0)} / "
                                             f"{q.get('stocks', {}).get('tradable', 0)}"),
            ("Capital / per trade", "Rs 10,00,000 / Rs 30,000"), ("Combinations tested", str(len(ranking)))]
    sec["summary"] = ("Summary", f"""
<div class='kpis'>{''.join(f"<div class='kpi'><span class='muted'>{esc(a)}</span><b>{esc(b)}</b></div>" for a, b in kpis)}</div>
<div class='card'><h2>The answers in short</h2><ul class='tips'>{''.join(f'<li>{t}</li>' for t in tips)}</ul></div>
<div class='card'><h2>Top 10 (best first)</h2>{table(ranking, RANK_COLS, money=('avg', 'net', 'max_dd'), signed=('return_pct',), limit=10)}
<p class='explain'>Each line is ONE way of trading: a strategy, its version, and one exit plan, run on every clean day with
Rs 30,000 per trade out of Rs 10 lakh. "Net profit" is after charges. "Worst drawdown" is the deepest fall of the account
from a high point. Read the page "How to read" for every word.</p></div>
{line_chart([(f"{c['strategy']} ({c['exit']})", c['curve']) for c in top_combos], "Account value, best version of each strategy (Rs 10 lakh start)")}
""")
    sec["ranking"] = ("Ranking", f"""
<div class='card'><h2>Every combination, best to worst</h2><p class='explain'>Rating: profit factor 1.6+ = 5 stars, 1.3+ = 4,
1.1+ = 3, 0.9+ = 2, below = 1; one star less when it did not make money in BOTH halves of the period or had fewer than 30
trades. Same stars: more net profit first (same Rs 10 lakh for all). Only combinations with 10+ trades are listed.</p>
{table(ranking, RANK_COLS, money=('avg', 'net', 'max_dd'), signed=('return_pct',))}</div>""")
    strat_html = []
    for name in fams:
        sub = [r for r in ranking if r["strategy"] == name]
        best_variants: dict[str, dict] = {}
        for r in sub:
            best_variants.setdefault(r["variant"], r)
        strat_html.append(f"<div class='card'><h2>{esc(name)}</h2>"
                          f"{bar_chart([(f'{v} | {r['exit']}', r['net']) for v, r in best_variants.items()], 'Best exit of each version: net profit')}"
                          f"{table(sub, RANK_COLS, money=('avg', 'net', 'max_dd'), signed=('return_pct',), limit=25)}"
                          f"<p class='muted'>Top 25 of {len(sub)} lines. Full list: ranking.csv.</p></div>")
    sec["strategies"] = ("Strategies", f"""
<div class='card explain'>KTMI Uni Lite buys an ATM CALL (long) or PUT (short) on the index when the locked indicator gives an
arrow (rule UNI_LITE_CORE). Its money is an ESTIMATE: there are no option candles for these days, so the option is
modelled as half the index move (delta 0.5), premium 0.6% of the index, a 1-point spread and real option charges, and NO
time decay (slow trades look better than they would be). Gap Reversal and Open High Low trade the STOCK itself
(intraday), so their numbers use real prices and real charges. Opening Scalp is a research strategy (OFF live).</div>
{''.join(strat_html)}""")
    tsl_cols = [("exit", "TSL method"), ("name", "In plain words"), ("best_in", "Best TSL in (versions)"),
                ("versions", "Versions tested"), ("avg_place", "Average place (1 = best)"),
                ("profitable_in", "Profitable in"), ("total_net", "Total net (all versions)")]
    tsl_pivot = []
    for name in fams:
        line = {"strategy": name}
        for key in rc.PRESETS:
            sel = [r for r in ranking if r["strategy"] == name and r["exit"] == f"TSL {key}"]
            line[key] = max((r["net"] for r in sel), default=None)
        tsl_pivot.append(line)
    sec["tsl"] = ("TSL methods", f"""
<div class='card'><h2>Trailing stops, each one alone (no fixed target)</h2>
<p class='explain'>Every TSL method ran on every trade of every strategy version, on the strategy's candles, exiting when a
candle CLOSES beyond it (your rule). "Average place" ranks the methods inside each strategy version (1 = made the most);
a low average place in many versions means it works across strategies, not by luck in one.</p>
{table(tsl_scores, tsl_cols, money=('total_net',))}
<h3>Best version of each strategy with each TSL (net profit)</h3>
{table(tsl_pivot, [("strategy", "Strategy")] + [(k, k) for k in rc.PRESETS], money=tuple(rc.PRESETS))}</div>""")
    sec["rr"] = ("Fixed targets", f"""
<div class='card'><h2>Fixed targets 1:1.5 to 1:3 (the whole trade out at the target, hard stop, no TSL)</h2>
{table(rr_scores, [("exit", "Target"), ("best_in", "Best target in"), ("versions", "Versions"),
                   ("avg_place", "Average place"), ("profitable_in", "Profitable in"), ("total_net", "Total net")],
       money=('total_net',))}
<h3>Fixed target or trailing stop?</h3>
{table([{"kind": k, **rc.stats([r for r in rows if r["exit_kind"] == k])} for k in ("Fixed RR", "TSL", "Own rule")
        if any(r["exit_kind"] == k for r in rows)],
       [("kind", "Exit type"), ("trades", "Trades"), ("win_pct", "Win %"), ("pf", "Profit factor"), ("avg", "Avg"),
        ("net", "Net (all versions together)")], money=('avg', 'net'))}
<p class='explain'>Fixed targets usually win MORE OFTEN (higher win %), trailing stops usually make more on the big days.
The table above adds up every version, so compare the profit factor and the average, not only the totals.</p></div>""")
    sec["timeframe"] = ("Timeframes", f"""
<div class='card'><h2>Which timeframe?</h2><p class='explain'>KTMI: the candle size of the signal (and of its TSL).
Gap Reversal: 5-min (first 10 candles) or 3-min (first 16 candles). Open High Low: first candle 5 or 15 minutes.
Each version is shown with its best exit plan.</p>
{table(tf_rows, [("strategy", "Strategy"), ("best", "Best"), ("all", "All versions (best exit each)")])}</div>""")
    sec["hours"] = ("Time of day", f"""
<div class='card'><h2>When does each strategy work? (hour of ENTRY)</h2><p class='explain'>Best version of each strategy.
Cell = net profit (number of trades, win %).</p>
{table(hour_p, [("combo", "Strategy - version - exit")] + [(h, h) for h in rc.HOURS] +
       [("best_hour", "Best hour"), ("worst_hour", "Worst hour")])}</div>""")
    reg = regime_table(data["regime"])
    sec["vix"] = ("India VIX & market", f"""
<div class='card'><h2>India VIX: calm or nervous market</h2><p class='explain'>VIX at 09:15 each day, split into three equal
groups for this period: LOW below {esc(th.get('vix_low_below'))}, HIGH from {esc(th.get('vix_high_from'))}, NORMAL between.
The VIX at the open is known BEFORE you trade, so it can become a filter. TREND day = NIFTY closed at least half its day's
range away from its open; RANGE day = it did not (sideways). That is known only after the close: it explains, it cannot
filter.</p>
<h3>How the market behaved in each VIX group (NIFTY)</h3>
{table(reg, [("vix", "VIX group"), ("days", "Days"), ("trend_pct", "Trend days %"), ("avg_range", "Avg day range %"),
             ("avg_abs_move", "Avg open-to-close move %")])}
<h3>Each strategy (best version) by VIX group</h3>
{table(vix_p, [("combo", "Strategy - version - exit"), ("LOW", "VIX LOW"), ("NORMAL", "VIX NORMAL"), ("HIGH", "VIX HIGH"),
               ("best", "Best"), ("worst", "Worst")])}
<h3>VIX rising or falling at the open (vs yesterday's close)</h3>
{table(move_p, [("combo", "Strategy - version - exit"), ("VIX up", "VIX up"), ("VIX down", "VIX down")])}
<h3>Trend days vs sideways days</h3>
{table(trend_p, [("combo", "Strategy - version - exit"), ("TREND", "TREND days"), ("RANGE", "RANGE (sideways) days")])}
</div>""")
    port_rows = []
    for c in top_combos:
        p = rc.portfolio([r for r in rows if r["strategy"] == c["strategy"] and r["variant"] == c["variant"]
                          and r["exit"] == c["exit"]])
        port_rows.append({"plan": f"{c['strategy']} - {c['variant']} - {c['exit']}", **p})
    if combined:
        port_rows.append({"plan": "COMBINED: " + " + ".join(c["strategy"] for c in chosen), **combined})
    port_cols = [("plan", "Plan"), ("taken", "Trades taken"), ("skipped", "Skipped (no free money)"), ("net", "Net"),
                 ("return_pct", "Return %"), ("max_dd", "Worst drawdown"), ("max_dd_pct", "Drawdown %"),
                 ("return_to_dd", "Return / drawdown"), ("green_days_pct", "Green days %"), ("best_day", "Best day"),
                 ("worst_day", "Worst day")]
    sec["money"] = ("Rs 10 lakh plan", f"""
<div class='card'><h2>Rs 10,00,000 account, Rs 30,000 per trade</h2><p class='explain'>At most 33 trades can be open at the
same time (33 x Rs 30,000 = Rs 9.9 lakh); a signal that finds no free money is skipped. Profits are not re-invested
(every trade stays Rs 30,000). COMBINED = the best version of every strategy rated 3+ stars that made money in both halves,
sharing the same Rs 10 lakh.</p>
{table(port_rows, port_cols, money=('net', 'max_dd', 'best_day', 'worst_day'), signed=('return_pct',))}
{line_chart([(p['plan'][:60], p['curve']) for p in port_rows], 'Account value')}</div>""")
    wf_cols = [("strategy", "Strategy"), ("variant", "Version"), ("picked_exit", "Exit chosen on 1st half"),
               ("first_half_net", "1st half net"), ("second_half_net", "Same exit, 2nd half (unseen)"),
               ("second_half_best_exit", "Best exit of 2nd half"), ("second_half_best_net", "Its net")]
    sec["honesty"] = ("Honesty check", f"""
<div class='card'><h2>Would we have picked a winner in advance?</h2><p class='explain'>Testing many combinations always finds
some that look great by luck. Here the exit plan is chosen using ONLY the first half of the days, then traded on the second
half it has never seen. If the second-half number stays positive, the result is more likely real.</p>
{table(wf, wf_cols, money=('first_half_net', 'second_half_net', 'second_half_best_net'))}</div>""")
    if long_ranking:
        sec["long"] = ("1-year NIFTY", f"""
<div class='card'><h2>KTMI Uni Lite on 1 year of NIFTY (clean days)</h2><p class='explain'>The same tests on a longer stretch
of NIFTY from your 5-year database: if the best exits here match the 3-month ones, trust them more.</p>
{table(long_ranking, RANK_COLS, money=('avg', 'net', 'max_dd'), signed=('return_pct',), limit=25)}
{line_chart([(f"{r['variant']} {r['exit']}", r['curve']) for r in long_ranking[:4]], 'Account value, top 4 (1 year)')}</div>""")
    sec["ideas"] = ("Suggestions", f"""
<div class='card'><h2>What the numbers say</h2><ul class='tips'>{''.join(f'<li>{t}</li>' for t in tips)}</ul></div>
<div class='card'><h2>Advice before real money</h2><ul class='tips'>
<li><b>Paper trade the 4-5 star versions for 4-6 weeks</b> with these exact settings, and compare live results with this
report every week. Real money only for versions that keep their profit factor above 1.2 live.</li>
<li><b>KTMI money is an estimate</b> (no time decay, fixed delta). The live paper engine trades real option prices: trust
its numbers over this page. A trade held 2-3 hours loses premium to time decay, especially on expiry days.</li>
<li><b>62 days is short.</b> Many combinations were tested, so a few look good by chance: prefer versions that are good in
both halves, in the honesty check and (KTMI) on the 1-year page.</li>
<li><b>Use VIX at the open as an on/off switch only if the VIX page shows a clear, large difference</b> (for example a
strategy that loses money on HIGH VIX days in both halves). Small differences are noise.</li>
<li><b>Risk per day:</b> with Rs 30,000 per trade and stops of 0.5-2%, one losing trade costs about Rs 150-600 on stocks and
up to Rs 9,000 (30% of premium) on options. Set a daily loss limit (for example Rs 20,000 = 2% of capital) in the
dashboard and stop for the day when it is hit.</li>
<li><b>Why the stock strategies show small rupees:</b> Rs 30,000 of a stock that moves 0.5% is about Rs 150, while Rs 30,000
of options moves much more (leverage). Compare strategies by profit factor, win % and "Both halves +", not only by rupees.
If a stock strategy is good, size it by RISK instead (for example risk Rs 1,500 per trade = entry-to-stop distance x
quantity, using intraday MIS margin) - ask Claude to add that as a setting.</li>
<li><b>Ideas to test next:</b> (1) a VIX filter for the weakest regime of each strategy; (2) KTMI only in its best hours;
(3) Gap Reversal with a smaller gap (1%) but only the strongest setups (strength 80%+); (4) half out at 1:2, rest on the
best TSL (the live KTMI default); (5) record real option candles every day so the KTMI estimate can be replaced by real
premiums within a few weeks.</li></ul></div>""")
    sec["help"] = ("How to read", """
<div class='card'><h2>Words used in this report</h2><ul class='tips'>
<li><b>Trade</b>: one entry and its exit. <b>Win %</b>: share of trades that made money after charges.</li>
<li><b>Profit factor (PF)</b>: total money won / total money lost. 1.0 = break-even, 1.3+ good, 1.6+ very good.</li>
<li><b>Net profit</b>: after brokerage, STT, exchange fees, GST and stamp duty.</li>
<li><b>Worst drawdown</b>: the biggest fall of the account from a previous high (Rs and % of Rs 10 lakh).</li>
<li><b>Return / drawdown</b>: profit earned per rupee of worst fall. Above 2 is comfortable.</li>
<li><b>Both halves +</b>: made money in the first half of the days AND in the second half.</li>
<li><b>R</b>: profit in units of the risk taken (distance from entry to stop). 1R = made what was risked.</li>
<li><b>Fixed target 1:2</b>: the whole trade exits when profit = 2 x the risk; else at the stop or 15:10.</li>
<li><b>TSL only</b>: no target; the trailing stop (your preset numbers) closes the trade when a candle closes beyond it.</li>
<li><b>Clean day</b>: every minute of FYERS data present and sane (stocks: up to 15:14, max 3 quiet minutes).</li>
<li><b>VIX LOW / NORMAL / HIGH</b>: India VIX at 09:15, in three equal groups for the period.</li>
<li><b>TREND / RANGE day</b>: NIFTY closed at least half its day's range away from the open (trend) or not (sideways).</li>
</ul></div>""")
    nav = "".join(f"<button data-p='{k}'>{esc(t)}</button>" for k, (t, _b) in sec.items())
    body = "".join(f"<section id='{k}'>{b}</section>" for k, (_t, b) in sec.items())
    page = (f"<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' "
            f"content='width=device-width,initial-scale=1'><title>Kunal Quant Report Card</title><style>{CSS}</style>"
            f"</head><body><header><h1>Kunal Quant - Strategy Report Card</h1><div class='muted'>Made "
            f"{datetime.now(IST):%d %b %Y %H:%M} from the shared FYERS database ({esc(data['store'])}). Clean days only. "
            f"Rs 10 lakh capital, Rs 30,000 per trade. Research, not advice: past results do not promise future ones."
            f"</div></header><nav>{nav}</nav><main>{body}</main><script>{JS}</script></body></html>")
    return page, [html_text(t) for t in tips]


def html_text(s: str) -> str:
    import re
    return html.unescape(re.sub(r"<[^>]+>", "", s))


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Strategy report card (HTML) from the shared FYERS database.")
    p.add_argument("--days", type=int, default=90)
    p.add_argument("--long-days", type=int, default=365, help="KTMI on NIFTY over this many days (0 = skip)")
    p.add_argument("--timeframes", default="3,5,10,15", help="KTMI signal timeframes")
    p.add_argument("--stocks", default="", help="comma list (default: every stock in the database)")
    p.add_argument("--no-scalp", action="store_true")
    p.add_argument("--kq-db", type=Path, default=None)
    p.add_argument("--data-folder", type=Path, default=PROJECT_ROOT / "data")
    args = p.parse_args(argv)
    say("Report card: running every strategy x every exit plan (10-30 minutes; progress below).")
    data = collect(args)
    rows = data["rows"]
    if not rows:
        print("No trades at all: run  python scripts\\data_audit.py  and  python scripts\\fetch_data.py  first.")
        return 1
    all_days = sorted({r["day"] for r in rows})
    ranking = rc.rank_combos(rows, all_days)
    long_ranking = rc.rank_combos(data["long_rows"], sorted({r["day"] for r in data["long_rows"]})) \
        if data["long_rows"] else []
    wf = rc.walk_forward(rows, all_days)
    page, tips = build_html(data, ranking, long_ranking, wf)
    out = args.data_folder / "research" / "report_card"
    out.mkdir(parents=True, exist_ok=True)
    (out / "report_card.html").write_text(page, encoding="utf-8")
    keys = [k for k in rows[0]]
    with (out / "trades.csv").open("w", newline="", encoding="utf-8") as h:
        w = csv.DictWriter(h, fieldnames=keys)
        w.writeheader()
        w.writerows(rows)
    rank_keys = [k for k in ranking[0] if k != "curve"] if ranking else []
    with (out / "ranking.csv").open("w", newline="", encoding="utf-8") as h:
        w = csv.DictWriter(h, fieldnames=rank_keys, extrasaction="ignore")
        w.writeheader()
        w.writerows(ranking)
    lines = [f"KUNAL QUANT REPORT CARD {datetime.now(IST):%Y-%m-%d %H:%M}  window {data['since']} to {data['newest']}",
             f"Data: {json.dumps(data['quality'])}  VIX groups: {json.dumps(data['thresholds'])}", "", "TOP 20:"]
    for r in ranking[:20]:
        lines.append(f"{r['rank']:>3} {'*' * r['stars']:<5} {r['strategy']} | {r['variant']} | {r['exit']} | trades "
                     f"{r['trades']} win {r['win_pct']}% PF {r['pf']} net {r['net']:,.0f} ret {r['return_pct']}% "
                     f"DD {r['max_dd']:,.0f} stable {r['stable']}")
    lines += ["", "ANSWERS:"] + [f"- {t}" for t in tips] + ["", "HONESTY CHECK:"]
    lines += [f"- {w['strategy']} | {w['variant']}: picked {w['picked_exit']} -> 2nd half {w['second_half_net']:,.0f}"
              for w in wf]
    if long_ranking:
        lines += ["", "1-YEAR NIFTY TOP 5:"] + [
            f"- {r['variant']} | {r['exit']} | trades {r['trades']} PF {r['pf']} net {r['net']:,.0f}" for r in long_ranking[:5]]
    (out / "summary.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    say(f"Done. Open: {out / 'report_card.html'}   Send Claude: {out / 'summary.txt'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
