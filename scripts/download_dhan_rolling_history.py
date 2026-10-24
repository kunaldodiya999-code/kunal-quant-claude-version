"""Resumable Dhan rolling-options history downloader (read-only).

Default is PLAN ONLY. Add --execute to make API calls.
Downloads NIFTY rolling option data in <=30-calendar-day chunks, saves every raw
response and a manifest, and resumes by skipping successfully completed requests.

The series are ATM-relative rolling observations, not fixed-expiry contract history.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import date, timedelta
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

FIELDS = ("timestamp", "open", "high", "low", "close", "iv", "volume", "strike", "oi", "spot")
STRIKES = [f"ATM{n:+d}" if n else "ATM" for n in range(-10, 11)]
OPTION_TYPES = ("CALL", "PUT")


def default_dates() -> tuple[str, str]:
    end = date.today()  # exclusive: captures complete days through yesterday
    start = end - timedelta(days=365)
    return start.isoformat(), end.isoformat()


def build_chunks(from_date: str, to_date: str, max_days: int = 30) -> list[tuple[str, str]]:
    start = date.fromisoformat(from_date)
    end = date.fromisoformat(to_date)
    if end <= start:
        raise ValueError("to-date must be later than from-date; to-date is exclusive.")
    if max_days < 1 or max_days > 30:
        raise ValueError("max_days must be between 1 and 30.")
    chunks = []
    current = start
    while current < end:
        next_date = min(current + timedelta(days=max_days), end)
        chunks.append((current.isoformat(), next_date.isoformat()))
        current = next_date
    return chunks


def rows_from_response(response: dict[str, Any], option_type: str, request_strike: str) -> list[dict[str, Any]]:
    data = response.get("data")
    if not isinstance(data, dict):
        return []
    block = data.get("ce" if option_type == "CALL" else "pe")
    if not isinstance(block, dict):
        return []
    timestamps = block.get("timestamp")
    if not isinstance(timestamps, list):
        return []
    rows = []
    for index, timestamp in enumerate(timestamps):
        row = {"timestamp": timestamp, "request_strike": request_strike, "option_type": option_type}
        for field in FIELDS:
            if field == "timestamp":
                continue
            values = block.get(field)
            row[field] = values[index] if isinstance(values, list) and index < len(values) else None
        rows.append(row)
    return rows


def response_is_success(response: dict[str, Any]) -> bool:
    """Recognize common successful Dhan response envelopes."""
    if response.get("errorCode") or response.get("errorType"):
        return False
    status = response.get("status")
    if isinstance(status, str) and status.lower() in {"error", "failed", "failure"}:
        return False
    return isinstance(response.get("data"), dict)


def inspect_response(response: dict[str, Any], option_type: str) -> dict[str, Any]:
    data = response.get("data")
    block = data.get("ce" if option_type == "CALL" else "pe") if isinstance(data, dict) else None
    if not isinstance(block, dict):
        return {
            "rows": 0,
            "block_present": False,
            "field_lengths": {},
            "field_length_mismatches": [],
            "non_null_counts": {},
            "zero_counts": {},
        }
    lengths = {
        key: len(value) for key, value in block.items()
        if isinstance(value, list)
    }
    row_count = len(block.get("timestamp", [])) if isinstance(block.get("timestamp"), list) else 0
    mismatches = {key: length for key, length in lengths.items() if length != row_count}
    non_null_counts = {}
    zero_counts = {}
    for field in ("open", "high", "low", "close", "iv", "volume", "strike", "oi", "spot"):
        values = block.get(field)
        if isinstance(values, list):
            non_null_counts[field] = sum(value is not None for value in values)
            zero_counts[field] = sum(value == 0 for value in values if value is not None)
    return {
        "rows": row_count,
        "block_present": True,
        "field_lengths": lengths,
        "field_length_mismatches": mismatches,
        "non_null_counts": non_null_counts,
        "zero_counts": zero_counts,
    }


def main() -> int:
    default_from, default_to = default_dates()
    parser = argparse.ArgumentParser(description="Plan or resumably download Dhan NIFTY rolling options history.")
    parser.add_argument("--from-date", default=default_from, help="YYYY-MM-DD inclusive")
    parser.add_argument("--to-date", default=default_to, help="YYYY-MM-DD exclusive; defaults to today")
    parser.add_argument("--interval", choices=("1", "5", "15", "25", "60"), default="5")
    parser.add_argument("--expiry-flag", choices=("WEEK", "MONTH"), default="WEEK")
    parser.add_argument("--expiry-code", choices=(1, 2, 3), type=int, default=1)
    parser.add_argument("--max-days", type=int, default=30)
    parser.add_argument("--delay", type=float, default=0.30, help="Seconds between API calls")
    parser.add_argument("--output-dir", type=Path, default=PROJECT_ROOT / "data" / "raw" / "dhan_rolling_history")
    parser.add_argument("--execute", action="store_true", help="Actually call Dhan API; without this, only prints the plan")
    args = parser.parse_args()

    chunks = build_chunks(args.from_date, args.to_date, args.max_days)
    tasks = [
        {
            "from_date": chunk_start,
            "to_date": chunk_end,
            "expiry_flag": args.expiry_flag,
            "expiry_code": args.expiry_code,
            "strike": strike,
            "option_type": option_type,
            "interval": args.interval,
        }
        for chunk_start, chunk_end in chunks
        for strike in STRIKES
        for option_type in OPTION_TYPES
    ]
    run_name = f"nifty_{args.from_date}_{args.to_date}_{args.interval}m_{args.expiry_flag}_code{args.expiry_code}"
    run_dir = args.output_dir / run_name
    response_dir = run_dir / "responses"
    manifest_path = run_dir / "manifest.json"

    print("=" * 76)
    print("KUNAL QUANT — DHAN ROLLING OPTIONS HISTORY")
    print("=" * 76)
    print(f"Period (end exclusive): {args.from_date} to {args.to_date}")
    print(f"Chunks: {len(chunks)}; chunk limit: {args.max_days} calendar days")
    print(f"Resolution: {args.interval} minute; expiry: {args.expiry_flag} code {args.expiry_code}")
    print(f"Strike labels: {len(STRIKES)} (ATM-10 through ATM+10); sides: CALL + PUT")
    print(f"Planned requests: {len(tasks)}")
    print(f"Output: {run_dir}")
    print("Data meaning: rolling ATM-relative series; not fixed-expiry contract identity.")
    if not args.execute:
        print("PLAN ONLY: no API calls and no files written.")
        print("To execute/resume, add --execute to this command.")
        for index, chunk in enumerate(chunks, 1):
            print(f"  chunk {index:02d}: {chunk[0]} -> {chunk[1]} (exclusive)")
        return 0

    from api.dhan_client import DhanAPIError, DhanClient  # noqa: E402

    response_dir.mkdir(parents=True, exist_ok=True)
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("plan_signature") != tasks:
            raise RuntimeError(f"Existing manifest plan differs: {manifest_path}. Use a new date/configuration or output directory.")
    else:
        manifest = {
            "plan_signature": tasks,
            "configuration": {
                "from_date": args.from_date, "to_date_exclusive": args.to_date,
                "interval": args.interval, "expiry_flag": args.expiry_flag,
                "expiry_code": args.expiry_code, "strike_labels": STRIKES,
                "option_types": OPTION_TYPES, "max_chunk_days": args.max_days,
            },
            "read_only": True,
            "database_writes": False,
            "orders_placed": False,
            "requests": {},
        }
    client = DhanClient()
    completed = 0
    total_rows = 0
    for index, task in enumerate(tasks, 1):
        request_id = f"{index:04d}_{task['from_date']}_{task['to_date']}_{task['strike']}_{task['option_type']}"
        existing = manifest["requests"].get(request_id, {})
        response_path = response_dir / f"{request_id}.json"
        if response_path.exists():
            try:
                saved_response = json.loads(response_path.read_text(encoding="utf-8"))
                saved_quality = inspect_response(saved_response, task["option_type"])
                if (response_is_success(saved_response)
                        and saved_quality["rows"] > 0
                        and not saved_quality["field_length_mismatches"]):
                    if existing.get("status") != "ok":
                        manifest["requests"][request_id] = {
                            **task, "status": "ok", "rows": saved_quality["rows"],
                            "quality": saved_quality, "response_file": response_path.name,
                        }
                        manifest["completed_requests"] = sum(
                            1 for item in manifest["requests"].values() if item.get("status") == "ok"
                        )
                        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
                    completed += 1
                    total_rows += int(saved_quality["rows"])
                    continue
            except (OSError, json.JSONDecodeError):
                pass
        try:
            response = client.rolling_options(
                from_date=task["from_date"], to_date=task["to_date"],
                expiry_flag=task["expiry_flag"], expiry_code=task["expiry_code"],
                strike=task["strike"], option_type=task["option_type"],
                interval=task["interval"],
            )
        except (DhanAPIError, RuntimeError, ValueError) as exc:
            manifest["last_error"] = {"request_id": request_id, "error": str(exc)}
            manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
            print(f"STOPPED at {request_id}: {exc}")
            print(f"Completed requests: {completed}/{len(tasks)}. Rerun same command to resume.")
            return 1

        quality = inspect_response(response, task["option_type"])
        if not response_is_success(response):
            manifest["last_error"] = {
                "request_id": request_id,
                "error": response.get("errorMessage") or response.get("errorDescription") or response.get("message") or response.get("errorCode") or "unexpected response envelope",
            }
            response_path.write_text(json.dumps(response, separators=(",", ":")), encoding="utf-8")
            manifest["requests"][request_id] = {**task, "status": "api_error", "rows": quality["rows"], "quality": quality, "response_file": response_path.name}
            manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
            print(f"STOPPED at {request_id}: API response was not a successful data payload.")
            print(f"Completed requests: {completed}/{len(tasks)}. Fix the issue and rerun same command to resume.")
            return 1
        response_path.write_text(json.dumps(response, separators=(",", ":")), encoding="utf-8")
        manifest["requests"][request_id] = {
            **task,
            "status": "ok",
            "rows": quality["rows"],
            "quality": quality,
            "response_file": response_path.name,
        }
        completed += 1
        total_rows += quality["rows"]
        manifest["completed_requests"] = completed
        manifest["rows_total_across_requests_including_overlaps"] = total_rows
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        if quality["rows"] == 0:
            print(f"[{index}/{len(tasks)}] {request_id}: 0 rows (saved response; inspect payload)")
        elif quality["field_length_mismatches"]:
            print(f"[{index}/{len(tasks)}] {request_id}: {quality['rows']} rows; FIELD LENGTH MISMATCH")
        else:
            print(f"[{index}/{len(tasks)}] {request_id}: {quality['rows']} rows")
        if index < len(tasks) and args.delay > 0:
            time.sleep(args.delay)

    manifest["finished"] = True
    manifest["completed_requests"] = completed
    manifest["rows_total_across_requests_including_overlaps"] = total_rows
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"FINISHED: {completed}/{len(tasks)} requests; {total_rows} rows including overlaps.")
    print(f"Manifest: {manifest_path}")
    print("No database writes or orders were performed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
