"""Controlled FYERS NIFTY option availability matrix.

Read-only diagnostic. Samples populated and empty contracts across selected
historical expiries and CE/PE sides, then probes FYERS directly without
writing to SQLite.
"""

from __future__ import annotations

import argparse
import csv
import multiprocessing as mp
import sqlite3
import sys
import time
from datetime import date, timedelta, datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _extract_candles(response: dict) -> list:
    if not isinstance(response, dict):
        return []
    data = response.get("candles")
    if isinstance(data, list):
        return data
    data = response.get("data")
    if isinstance(data, dict) and isinstance(data.get("candles"), list):
        return data["candles"]
    return []


def _worker(symbol: str, range_from: str, range_to: str, queue) -> None:
    try:
        from api.fyers_client import FyersClient
        response = FyersClient().expired_history(
            symbol=symbol,
            resolution="1",
            range_from=range_from,
            range_to=range_to,
            include_oi="1",
            include_greeks="0",
        )
        candles = _extract_candles(response)
        if candles:
            queue.put(("AVAILABLE", len(candles), candles[0][0], candles[-1][0], ""))
        else:
            queue.put(("NO_DATA", 0, "", "", ""))
    except Exception as exc:
        queue.put(("ERROR", 0, "", "", repr(exc)))


def probe(symbol: str, expiry: str, days_before: int, timeout: float):
    end = date.fromisoformat(expiry)
    start = end - timedelta(days=days_before)
    queue = mp.Queue()
    process = mp.Process(
        target=_worker,
        args=(symbol, start.isoformat(), end.isoformat(), queue),
        daemon=True,
    )
    process.start()
    process.join(timeout)
    if process.is_alive():
        process.terminate()
        process.join(5)
        return "TIMEOUT", 0, "", "", f"timeout after {timeout:.0f}s"
    if not queue.empty():
        return queue.get()
    return "ERROR", 0, "", "", f"worker exitcode={process.exitcode}"


def _sample_side(db, expiry: str, option_type: str, state: str):
    condition = (
        "COALESCE(c.cnt,0) > 0" if state == "POPULATED"
        else "COALESCE(c.cnt,0) = 0"
    )
    return db.execute(
        f"""
        SELECT i.id, i.symbol, i.expiry_date, i.strike, i.option_type,
               COALESCE(c.cnt,0) AS existing_candles
        FROM instruments i
        LEFT JOIN (
            SELECT instrument_id, COUNT(*) AS cnt
            FROM candles
            WHERE resolution='1' AND source='FYERS_FNO_HISTORY'
            GROUP BY instrument_id
        ) c ON c.instrument_id=i.id
        WHERE i.broker='FYERS' AND i.underlying='NIFTY'
          AND i.option_type=? AND i.expiry_date=?
          AND i.expiry_date <= date('now') AND i.strike > 0
          AND {condition}
        ORDER BY
          CASE WHEN ?='POPULATED' THEN ABS(COALESCE(c.cnt,0)-3000)
               ELSE ABS(i.strike - (
                   SELECT AVG(i2.strike) FROM instruments i2
                   WHERE i2.broker='FYERS' AND i2.underlying='NIFTY'
                     AND i2.option_type=? AND i2.expiry_date=?
                     AND i2.strike > 0
               )) END,
          i.strike
        LIMIT 1
        """,
        (option_type, expiry, state, option_type, expiry),
    ).fetchone()


def select_matrix(db, expiries):
    rows = []
    for expiry in expiries:
        for option_type in ("CE", "PE"):
            for state in ("POPULATED", "EMPTY"):
                row = _sample_side(db, expiry, option_type, state)
                if row:
                    rows.append(dict(row))
    return rows


def _to_dt(value):
    if value in ("", None):
        return None
    try:
        return datetime.fromtimestamp(float(value)).astimezone()
    except (TypeError, ValueError, OSError):
        return None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, default=None)
    parser.add_argument("--days-before", type=int, default=90)
    parser.add_argument("--pause", type=float, default=1.2)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument(
        "--expiries",
        nargs="+",
        default=["2021-01-07", "2021-06-03", "2024-11-21", "2024-11-28",
                 "2025-10-20", "2026-08-25"],
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "data" / "research"
        / "fyers_nifty_option_availability_matrix.csv",
    )
    args = parser.parse_args()

    if args.database is None:
        from config.settings import DATABASE_PATH
        database_path = Path(DATABASE_PATH)
    else:
        database_path = args.database

    with sqlite3.connect(database_path, timeout=5) as db:
        db.row_factory = sqlite3.Row
        rows = select_matrix(db, args.expiries)

    print("=" * 110)
    print("KUNAL QUANT — FYERS NIFTY OPTION AVAILABILITY MATRIX")
    print("=" * 110)
    print(f"Database : {database_path}")
    print(f"Expiries : {', '.join(args.expiries)}")
    print(f"Samples  : {len(rows)} (up to 4 per expiry: populated/empty × CE/PE)")
    print("-" * 110)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "instrument_id", "symbol", "expiry_date", "strike", "option_type",
        "existing_candles", "range_from", "range_to", "status",
        "fyers_candles", "first_candle", "last_candle", "error",
    ]

    with args.output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()

        for idx, row in enumerate(rows, 1):
            expiry = date.fromisoformat(row["expiry_date"])
            range_from = expiry - timedelta(days=args.days_before)
            print(
                f"[{idx:02d}/{len(rows):02d}] {row['expiry_date']} "
                f"{row['option_type']} strike={row['strike']} "
                f"db={row['existing_candles']} {row['symbol']} ...",
                flush=True,
            )

            status, count, first_ts, last_ts, error = probe(
                row["symbol"], row["expiry_date"], args.days_before, args.timeout
            )

            first_dt = _to_dt(first_ts)
            last_dt = _to_dt(last_ts)
            writer.writerow({
                **{k: row[k] for k in ("symbol", "expiry_date", "strike", "option_type", "existing_candles")},
                "instrument_id": row["id"],
                "range_from": range_from.isoformat(),
                "range_to": expiry.isoformat(),
                "status": status,
                "fyers_candles": count,
                "first_candle": first_dt.isoformat() if first_dt else "",
                "last_candle": last_dt.isoformat() if last_dt else "",
                "error": error,
            })
            handle.flush()

            print(
                f"      -> {status} FYERS={count}"
                + (f" first={first_dt}" if first_dt else "")
                + (f" last={last_dt}" if last_dt else ""),
                flush=True,
            )
            if idx < len(rows):
                time.sleep(max(0.0, args.pause))

    print("-" * 110)
    print("FYERS AVAILABILITY MATRIX COMPLETE")
    print(f"Output : {args.output}")


if __name__ == "__main__":
    mp.freeze_support()
    main()
