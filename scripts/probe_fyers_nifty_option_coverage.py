"""Probe FYERS availability for representative empty NIFTY option contracts.

Read-only: no database writes. Each FYERS request runs in a killable child
process because the current SDK wrapper does not expose a reliable timeout.
"""

from __future__ import annotations

import argparse
import csv
import multiprocessing as mp
import sqlite3
import sys
import time
from datetime import date, timedelta
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
    if isinstance(data, list):
        return data
    return []


def _probe_worker(symbol: str, range_from: str, range_to: str, queue) -> None:
    try:
        from api.fyers_client import FyersClient

        client = FyersClient()
        response = client.expired_history(
            symbol=symbol,
            resolution="1",
            range_from=range_from,
            range_to=range_to,
            include_oi="1",
            include_greeks="0",
        )
        candles = _extract_candles(response)
        if candles:
            queue.put(
                ("AVAILABLE", len(candles), str(candles[0][0]), str(candles[-1][0]), "")
            )
        else:
            queue.put(("NO_DATA", 0, "", "", ""))
    except Exception as exc:
        queue.put(("ERROR", 0, "", "", str(exc)))


def _probe(
    symbol: str,
    expiry: str,
    days_before: int,
    retries: int,
    timeout: float,
) -> tuple[str, int, str, str, str]:
    expiry_date = date.fromisoformat(expiry)
    range_from = (expiry_date - timedelta(days=days_before)).isoformat()
    range_to = expiry
    last_error = ""

    for attempt in range(retries + 1):
        queue = mp.Queue()
        process = mp.Process(
            target=_probe_worker,
            args=(symbol, range_from, range_to, queue),
            daemon=True,
        )
        process.start()
        process.join(timeout)

        if process.is_alive():
            process.terminate()
            process.join(5)
            last_error = f"FYERS request timed out after {timeout:.0f}s"
        elif not queue.empty():
            return queue.get()
        else:
            last_error = (
                "FYERS worker exited without a response "
                f"(exitcode={process.exitcode})"
            )

        if attempt < retries:
            time.sleep(1.5 * (attempt + 1))

    status = "TIMEOUT" if "timed out" in last_error else "ERROR"
    return status, 0, "", "", last_error


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, default=None)
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT
        / "data"
        / "research"
        / "fyers_nifty_option_coverage_probe.csv",
    )
    parser.add_argument("--days-before", type=int, default=30)
    parser.add_argument("--pause", type=float, default=0.7)
    parser.add_argument("--retries", type=int, default=0)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument(
        "--max-probes",
        type=int,
        default=4,
        help="0 = all expiry/type probes; default 4",
    )
    args = parser.parse_args()

    if args.database is None:
        from config.settings import DATABASE_PATH

        database_path = Path(DATABASE_PATH)
    else:
        database_path = args.database

    print("Loading representative empty contracts from SQLite...", flush=True)
    with sqlite3.connect(database_path, timeout=5) as db:
        db.row_factory = sqlite3.Row
        rows = db.execute(
            """
            WITH empty AS (
                SELECT i.id, i.symbol, i.expiry_date, i.strike, i.option_type
                FROM instruments i
                LEFT JOIN (
                    SELECT instrument_id, COUNT(*) AS cnt
                    FROM candles
                    WHERE resolution='1' AND source='FYERS_FNO_HISTORY'
                    GROUP BY instrument_id
                ) c ON c.instrument_id=i.id
                WHERE i.broker='FYERS'
                  AND i.underlying='NIFTY'
                  AND i.option_type IN ('CE','PE')
                  AND i.expiry_date <= date('now')
                  AND i.strike > 0
                  AND COALESCE(c.cnt,0)=0
            ),
            expiry_avg AS (
                SELECT expiry_date, option_type, AVG(strike) AS avg_strike
                FROM empty
                GROUP BY expiry_date, option_type
            ),
            ranked AS (
                SELECT e.id, e.symbol, e.expiry_date, e.strike, e.option_type,
                       ROW_NUMBER() OVER (
                           PARTITION BY e.expiry_date, e.option_type
                           ORDER BY ABS(e.strike-a.avg_strike), e.strike
                       ) AS rn
                FROM empty e
                JOIN expiry_avg a
                  ON a.expiry_date=e.expiry_date
                 AND a.option_type=e.option_type
            )
            SELECT id, symbol, expiry_date, strike, option_type
            FROM ranked
            WHERE rn=1
            ORDER BY expiry_date, option_type
            """
        ).fetchall()
    print(f"SQLite selection complete: {len(rows)} representative rows.", flush=True)

    if args.max_probes:
        rows = rows[: args.max_probes]

    args.output.parent.mkdir(parents=True, exist_ok=True)

    fields = [
        "instrument_id",
        "symbol",
        "expiry_date",
        "strike",
        "option_type",
        "range_from",
        "range_to",
        "status",
        "candle_count",
        "first_timestamp",
        "last_timestamp",
        "error",
    ]

    with args.output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()

        for index, row in enumerate(rows, 1):
            print(
                f"[{index:03d}/{len(rows):03d}] "
                f"PROBING {row['expiry_date']} {row['option_type']} "
                f"{row['symbol']} ...",
                flush=True,
            )

            status, count, first_ts, last_ts, error = _probe(
                row["symbol"],
                row["expiry_date"],
                args.days_before,
                args.retries,
                args.timeout,
            )

            expiry_date = date.fromisoformat(row["expiry_date"])
            range_from = (
                expiry_date - timedelta(days=args.days_before)
            ).isoformat()

            writer.writerow(
                {
                    "instrument_id": row["id"],
                    "symbol": row["symbol"],
                    "expiry_date": row["expiry_date"],
                    "strike": row["strike"],
                    "option_type": row["option_type"],
                    "range_from": range_from,
                    "range_to": row["expiry_date"],
                    "status": status,
                    "candle_count": count,
                    "first_timestamp": first_ts,
                    "last_timestamp": last_ts,
                    "error": error,
                }
            )
            handle.flush()

            print(
                f"[{index:03d}/{len(rows):03d}] "
                f"RESULT {status} candles={count}"
                + (f" error={error}" if error else ""),
                flush=True,
            )

            if index < len(rows):
                time.sleep(max(0.0, args.pause))

    print("=" * 90)
    print("FYERS OPTION COVERAGE PROBE COMPLETE")
    print("=" * 90)
    print(f"Probe rows : {len(rows)}")
    print(f"Output     : {args.output}")


if __name__ == "__main__":
    mp.freeze_support()
    main()
