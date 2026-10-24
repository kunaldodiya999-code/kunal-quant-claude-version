"""Read-only validation of whether Dhan rolling options can be stitched by timestamp + actual strike.

Makes one request for each ATM-relative strike from ATM-10 through ATM+10.
No database writes and no order placement. Raw responses and a merged diagnostic
CSV/JSON are saved under ignored data/raw/dhan_reconstruction/.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from api.dhan_client import DhanAPIError, DhanClient  # noqa: E402


FIELDS = ("timestamp", "strike", "spot", "open", "high", "low", "close", "iv", "volume", "oi")


def default_dates() -> tuple[str, str]:
    end = date.today()
    start = end - timedelta(days=1)
    return start.isoformat(), end.isoformat()


def strike_labels() -> list[str]:
    return [f"ATM{offset:+d}" if offset else "ATM" for offset in range(-10, 11)]


def rows_from_response(result: dict[str, Any], option_type: str, request_strike: str) -> list[dict[str, Any]]:
    data = result.get("data") or {}
    # Dhan's sample schema puts CALL data under ce and PUT data under pe.
    block_key = "ce" if option_type == "CALL" else "pe"
    block = data.get(block_key)
    if not isinstance(block, dict):
        return []
    timestamps = block.get("timestamp") or []
    rows: list[dict[str, Any]] = []
    for i, timestamp in enumerate(timestamps):
        row: dict[str, Any] = {
            "timestamp": timestamp,
            "request_strike": request_strike,
            "option_type": option_type,
        }
        for field in FIELDS:
            if field == "timestamp":
                continue
            values = block.get(field)
            row[field] = values[i] if isinstance(values, list) and i < len(values) else None
        rows.append(row)
    return rows


def main() -> int:
    default_from, default_to = default_dates()
    parser = argparse.ArgumentParser(description="Validate Dhan rolling-strike reconstruction (read-only).")
    parser.add_argument("--from-date", default=default_from, help="YYYY-MM-DD inclusive")
    parser.add_argument("--to-date", default=default_to, help="YYYY-MM-DD exclusive")
    parser.add_argument("--expiry-flag", choices=["WEEK", "MONTH"], default="WEEK")
    parser.add_argument("--expiry-code", type=int, choices=[1, 2, 3], default=1,
                        help="1=near, 2=next, 3=far; endpoint-specific mapping; default 1")
    parser.add_argument("--option-type", choices=["CALL", "PUT"], default="CALL")
    parser.add_argument("--delay", type=float, default=0.25, help="Seconds between requests (default 0.25)")
    args = parser.parse_args()

    output_dir = PROJECT_ROOT / "data" / "raw" / "dhan_reconstruction"
    output_dir.mkdir(parents=True, exist_ok=True)
    client = DhanClient()
    all_rows: list[dict[str, Any]] = []
    request_summary: list[dict[str, Any]] = []
    print("=" * 72)
    print("KUNAL QUANT — DHAN ROLLING-STRIKE RECONSTRUCTION VALIDATION")
    print("=" * 72)
    print(f"Date range: {args.from_date} to {args.to_date} (end exclusive)")
    print(f"Expiry: {args.expiry_flag}, code={args.expiry_code}; option: {args.option_type}")
    print("Requests: 21 relative strikes (ATM-10 through ATM+10)")
    print("Safety: read-only; no database writes; no orders")
    labels = strike_labels()

    for index, label in enumerate(labels):
        try:
            result = client.rolling_options(
                from_date=args.from_date,
                to_date=args.to_date,
                expiry_flag=args.expiry_flag,
                expiry_code=args.expiry_code,
                strike=label,
                option_type=args.option_type,
                interval="1",
            )
        except (DhanAPIError, RuntimeError, ValueError) as exc:
            print(f"FAILED at {label}: {exc}")
            print(f"Completed {len(request_summary)} of {len(labels)} requests. No database was changed.")
            return 1

        rows = rows_from_response(result, args.option_type, label)
        all_rows.extend(rows)
        request_summary.append({"request_strike": label, "rows": len(rows)})
        print(f"[{index + 1:02d}/21] {label:6s} -> {len(rows)} rows")
        if index < len(labels) - 1 and args.delay > 0:
            time.sleep(args.delay)

    # Keep one row per timestamp + actual strike. Record conflicts rather than
    # silently overwriting potentially different values from overlapping streams.
    grouped: dict[tuple[int, float], list[dict[str, Any]]] = defaultdict(list)
    for row in all_rows:
        if row.get("timestamp") is not None and row.get("strike") is not None:
            grouped[(int(row["timestamp"]), float(row["strike"]))].append(row)

    merged: list[dict[str, Any]] = []
    conflict_count = 0
    for (timestamp, strike), candidates in sorted(grouped.items()):
        chosen = candidates[0]
        for other in candidates[1:]:
            differs = any(
                chosen.get(field) != other.get(field)
                for field in ("open", "high", "low", "close", "spot", "iv", "volume", "oi")
                if chosen.get(field) is not None and other.get(field) is not None
            )
            if differs:
                conflict_count += 1
        out = {field: chosen.get(field) for field in FIELDS}
        out["source_requests"] = ";".join(sorted({r["request_strike"] for r in candidates}))
        out["source_count"] = len(candidates)
        merged.append(out)

    strike_counts = Counter(float(row["strike"]) for row in merged if row.get("strike") is not None)
    timestamp_counts = Counter(int(row["timestamp"]) for row in merged if row.get("timestamp") is not None)
    summary = {
        "from_date": args.from_date,
        "to_date_exclusive": args.to_date,
        "expiry_flag": args.expiry_flag,
        "expiry_code": args.expiry_code,
        "option_type": args.option_type,
        "requests": request_summary,
        "raw_rows_total": len(all_rows),
        "unique_timestamp_strike_rows": len(merged),
        "unique_timestamps": len(timestamp_counts),
        "unique_actual_strikes": len(strike_counts),
        "duplicate_timestamp_strike_groups": sum(1 for v in grouped.values() if len(v) > 1),
        "conflicting_duplicate_groups": conflict_count,
        "strike_row_counts": {str(k): v for k, v in sorted(strike_counts.items())},
        "interpretation": (
            "Stitching is only a candidate method. This diagnostic does not prove that "
            "expiryCode maps to a constant expiry date through time, nor that OHLC values "
            "are identical across overlapping requests. Validate contract expiry and prices "
            "before using the output for backtesting."
        ),
    }

    stem = f"{args.from_date}_{args.to_date}_{args.expiry_flag}_code{args.expiry_code}_{args.option_type}"
    json_path = output_dir / f"reconstruction_{stem}.json"
    csv_path = output_dir / f"reconstruction_{stem}.csv"
    json_path.write_text(json.dumps({"summary": summary, "rows": merged}, indent=2), encoding="utf-8")
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=[*FIELDS, "source_requests", "source_count"])
        writer.writeheader()
        writer.writerows(merged)

    print("\nSUMMARY")
    print(f"Raw rows across requests : {len(all_rows)}")
    print(f"Unique timestamp+strike  : {len(merged)}")
    print(f"Unique timestamps        : {len(timestamp_counts)}")
    print(f"Unique actual strikes    : {len(strike_counts)}")
    print(f"Duplicate key groups     : {summary['duplicate_timestamp_strike_groups']}")
    print(f"Conflicting duplicates   : {conflict_count}")
    print(f"JSON output              : {json_path.relative_to(PROJECT_ROOT)}")
    print(f"CSV output               : {csv_path.relative_to(PROJECT_ROOT)}")
    print("\nNOT A BACKTEST DATASET YET: confirm exact expiry and overlap consistency first.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
