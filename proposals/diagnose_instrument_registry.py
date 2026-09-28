"""
Kunal Quant — Instrument Registry Diagnostic (read-only)

Why this exists: Option Contract Resolver V2 picks the nearest expiry that
is *registered in the `instruments` table* (SELECT MIN(expiry_date) ...
WHERE expiry_date >= entry_date). If a real weekly expiry was never
registered, the resolver silently lands on a later one. The first real
run of the v2 coverage diagnostic showed 198 of 300 events resolving to
expiry 2026-09-15 from signal dates of Aug 21-24, which suggests exactly
that. This script shows, per registered expiry, how many contracts and
strikes exist, how many have any candles, and where consecutive
registered expiries are more than 8 days apart (weekly NIFTY expiries are
7 days apart, so a wider gap means weeklies are missing from the registry).

Opens the database read-only. Changes nothing.

Usage (from the KunalQuant repo root, PYTHONPATH set to that root):
    python <path>/diagnose_instrument_registry.py
    python <path>/diagnose_instrument_registry.py --since 2026-01-01
    python <path>/diagnose_instrument_registry.py --db some/other.db
"""

from __future__ import annotations

import argparse
import sqlite3
from datetime import date
from pathlib import Path


def build_report(db_path: Path | str, since: date) -> str:
    uri = f"file:{Path(db_path).as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    try:
        registry = conn.execute(
            """
            SELECT expiry_date,
                   COUNT(*)                    AS instruments,
                   COUNT(DISTINCT strike)      AS strikes,
                   MIN(strike), MAX(strike),
                   SUM(option_type = 'CE')     AS ce,
                   SUM(option_type = 'PE')     AS pe
            FROM instruments
            WHERE broker = 'FYERS' AND underlying = 'NIFTY'
              AND option_type IN ('CE', 'PE')
            GROUP BY expiry_date
            ORDER BY expiry_date
            """
        ).fetchall()

        with_candles = dict(
            conn.execute(
                """
                SELECT i.expiry_date, COUNT(DISTINCT c.instrument_id)
                FROM candles c
                JOIN instruments i ON i.id = c.instrument_id
                WHERE c.resolution = '1'
                  AND c.source = 'FYERS_FNO_HISTORY'
                  AND i.broker = 'FYERS' AND i.underlying = 'NIFTY'
                GROUP BY i.expiry_date
                """
            ).fetchall()
        )
    finally:
        conn.close()

    out: list[str] = []
    w = out.append
    bar = "=" * 100
    w(bar)
    w("KUNAL QUANT — NIFTY OPTION INSTRUMENT REGISTRY (read-only)")
    w(bar)
    w(f"Registered NIFTY option expiries : {len(registry):,}")
    older = [r for r in registry if date.fromisoformat(r[0]) < since]
    recent = [r for r in registry if date.fromisoformat(r[0]) >= since]
    w(f"  before {since}              : {len(older):,} (not listed)")
    w(f"  on/after {since}            : {len(recent):,}")
    w("")
    w(f"{'expiry':<12}{'day':<5}{'contracts':>10}{'strikes':>9}"
      f"{'strike range':>16}{'CE':>6}{'PE':>6}{'with candles':>14}")
    for exp, n, strikes, lo, hi, ce, pe in recent:
        d = date.fromisoformat(exp)
        w(
            f"{exp:<12}{d.strftime('%a'):<5}{n:>10}{strikes:>9}"
            f"{f'{lo:.0f}-{hi:.0f}':>16}{ce:>6}{pe:>6}"
            f"{with_candles.get(exp, 0):>14}"
        )
    w("")

    w(f"GAPS — consecutive registered expiries more than 8 days apart (since {since})")
    gaps = 0
    prev = None
    for exp, *_ in recent:
        d = date.fromisoformat(exp)
        if prev is not None and (d - prev).days > 8:
            gaps += 1
            w(f"  {prev} ({prev.strftime('%a')}) -> {d} ({d.strftime('%a')})"
              f" : {(d - prev).days} days, likely missing weekly expiries")
        prev = d
    if gaps == 0:
        w("  none")
    w("")
    w("Reading this: a gap means the resolver will jump over the missing "
      "expiries. If the strike it wants exists on the later expiry it will "
      "silently pick a far-dated option; if not, it returns "
      "CONTRACT_NOT_FOUND (safe, but the trade is lost).")
    return "\n".join(out)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default=None)
    parser.add_argument("--since", default="2026-01-01")
    args = parser.parse_args()

    if args.db is None:
        from config.settings import DATABASE_PATH

        args.db = DATABASE_PATH

    print(build_report(args.db, date.fromisoformat(args.since)))


if __name__ == "__main__":
    main()
