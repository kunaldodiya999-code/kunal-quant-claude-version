"""Offline audit/normalizer for a completed Dhan rolling-history download.

Reads only the downloader's manifest and saved raw responses. No API calls,
database writes, or credentials are needed.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).resolve().parents[1]
IST = ZoneInfo("Asia/Kolkata")
FIELDS = ("timestamp", "open", "high", "low", "close", "iv", "volume", "strike", "oi", "spot")


def flatten_response(response: dict[str, Any], task: dict[str, Any], request_id: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    data = response.get("data")
    block = data.get("ce" if task["option_type"] == "CALL" else "pe") if isinstance(data, dict) else None
    if not isinstance(block, dict):
        return [], {"block_present": False, "rows": 0, "field_length_mismatches": {"option_block": "missing"}}
    timestamps = block.get("timestamp")
    if not isinstance(timestamps, list):
        return [], {"block_present": True, "rows": 0, "field_length_mismatches": {"timestamp": "missing"}}
    count = len(timestamps)
    mismatches = {}
    for field in FIELDS:
        if field == "timestamp":
            continue
        values = block.get(field)
        if isinstance(values, list) and len(values) != count:
            mismatches[field] = len(values)
        elif values is not None and not isinstance(values, list):
            mismatches[field] = "not-list"
    rows = []
    for i, timestamp in enumerate(timestamps):
        try:
            epoch = int(float(timestamp))
            local = datetime.fromtimestamp(epoch, timezone.utc).astimezone(IST)
        except (ValueError, TypeError, OverflowError, OSError):
            continue
        row = {
            "timestamp": epoch,
            "date_ist": local.date().isoformat(),
            "time_ist": local.strftime("%H:%M:%S"),
            "request_strike": task["strike"],
            "option_type": task["option_type"],
            "expiry_flag": task["expiry_flag"],
            "expiry_code": task["expiry_code"],
            "request_from": task["from_date"],
            "request_to_exclusive": task["to_date"],
            "source_request": request_id,
        }
        for field in FIELDS:
            if field == "timestamp":
                continue
            values = block.get(field)
            row[field] = values[i] if isinstance(values, list) and i < len(values) else None
        rows.append(row)
    return rows, {"block_present": True, "rows": count, "field_length_mismatches": mismatches}


def main() -> int:
    parser = argparse.ArgumentParser(description="Offline audit of Dhan rolling-history response files.")
    parser.add_argument("--run-dir", type=Path, required=True, help="Downloader run directory containing manifest.json and responses/")
    args = parser.parse_args()
    run_dir = args.run_dir if args.run_dir.is_absolute() else PROJECT_ROOT / args.run_dir
    manifest_path = run_dir / "manifest.json"
    if not manifest_path.exists():
        parser.error(f"manifest not found: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    requests = manifest.get("requests", {})
    planned_tasks = manifest.get("plan_signature", [])
    planned_ids = set()
    for index, task in enumerate(planned_tasks, 1):
        planned_ids.add(f"{index:04d}_{task['from_date']}_{task['to_date']}_{task['strike']}_{task['option_type']}")
    all_rows: list[dict[str, Any]] = []
    response_checks = []
    for request_id, task in requests.items():
        if task.get("status") != "ok":
            response_checks.append({"request_id": request_id, "status": "not-complete"})
            continue
        path = run_dir / "responses" / task.get("response_file", f"{request_id}.json")
        if not path.exists():
            response_checks.append({"request_id": request_id, "status": "missing-file"})
            continue
        response = json.loads(path.read_text(encoding="utf-8"))
        rows, quality = flatten_response(response, task, request_id)
        all_rows.extend(rows)
        response_checks.append({"request_id": request_id, "status": "read", **quality})

    # Check per requested rolling label and side, by IST session date.
    per_session: dict[tuple[str, str, str], list[int]] = defaultdict(list)
    for row in all_rows:
        per_session[(row["request_strike"], row["option_type"], row["date_ist"])].append(row["timestamp"])
    session_reports = []
    expected = 75 if str(manifest.get("configuration", {}).get("interval", "5")) == "5" else None
    interval_seconds = int(manifest.get("configuration", {}).get("interval", "5")) * 60
    for (label, side, day), timestamps in sorted(per_session.items()):
        unique = sorted(set(timestamps))
        local = [datetime.fromtimestamp(ts, timezone.utc).astimezone(IST) for ts in unique]
        in_session = [dt for dt in local if (dt.hour * 60 + dt.minute) >= 555 and (dt.hour * 60 + dt.minute) <= 925 and dt.second == 0]
        expected_starts = set()
        if expected is not None:
            midnight = datetime.fromisoformat(day).replace(tzinfo=IST)
            base = int(midnight.timestamp()) + 9 * 3600 + 15 * 60
            expected_starts = {base + i * interval_seconds for i in range(75)}
        missing = len(expected_starts - {int(dt.timestamp()) for dt in in_session}) if expected is not None else None
        session_reports.append({
            "request_strike": label, "option_type": side, "date_ist": day,
            "rows": len(timestamps), "unique_timestamps": len(unique),
            "in_session_rows": len(in_session),
            "expected_5m_full_session_rows": expected,
            "missing_expected_rows": missing,
            "first_ist": local[0].isoformat() if local else None,
            "last_ist": local[-1].isoformat() if local else None,
        })

    # Collapse only exact timestamp + actual strike + side duplicates; retain provenance
    # and explicitly count disagreements rather than silently overwriting them.
    grouped: dict[tuple[int, float, str], list[dict[str, Any]]] = defaultdict(list)
    unkeyed_rows = 0
    for row in all_rows:
        try:
            key = (int(row["timestamp"]), float(row["strike"]), row["option_type"])
        except (ValueError, TypeError):
            unkeyed_rows += 1
            continue
        grouped[key].append(row)
    merged = []
    conflict_groups = []
    for key, candidates in sorted(grouped.items()):
        chosen = candidates[0]
        conflicts = []
        for other in candidates[1:]:
            differences = [
                field for field in ("open", "high", "low", "close", "iv", "volume", "oi", "spot")
                if chosen.get(field) is not None and other.get(field) is not None and chosen.get(field) != other.get(field)
            ]
            if differences:
                conflicts.append({"source_request": other["source_request"], "different_fields": differences})
        output = {field: chosen.get(field) for field in FIELDS}
        output.update({
            "date_ist": chosen["date_ist"], "time_ist": chosen["time_ist"],
            "option_type": chosen["option_type"],
            "source_count": len(candidates),
            "source_requests": ";".join(sorted({x["source_request"] for x in candidates})),
        })
        merged.append(output)
        if conflicts:
            conflict_groups.append({
                "timestamp": key[0], "strike": key[1], "option_type": key[2],
                "source_count": len(candidates), "conflicts": conflicts,
            })

    csv_path = run_dir / "normalized_rolling_history.csv"
    fieldnames = [*FIELDS, "date_ist", "time_ist", "option_type", "source_count", "source_requests"]
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(merged)

    report = {
        "run_configuration": manifest.get("configuration"),
        "planned_requests": len(planned_ids) if planned_ids else len(requests),
        "manifest_requests": len(requests),
        "request_ids_missing_from_manifest": sorted(planned_ids - set(requests)) if planned_ids else [],
        "requests_with_saved_response": sum(1 for x in response_checks if x["status"] == "read"),
        "missing_or_incomplete_requests": [x for x in response_checks if x["status"] != "read"],
        "requests_with_field_length_mismatches": [x for x in response_checks if x.get("field_length_mismatches")],
        "empty_or_missing_option_blocks": [x for x in response_checks if x.get("rows", 0) == 0 or not x.get("block_present", True)],
        "raw_normalized_rows": len(all_rows),
        "unique_timestamp_actual_strike_side_rows": len(merged),
        "duplicate_groups_collapsed": sum(1 for v in grouped.values() if len(v) > 1),
        "conflicting_duplicate_groups": len(conflict_groups),
        "unkeyed_rows_missing_timestamp_or_strike": unkeyed_rows,
        "session_rows_expected_per_full_5m_session": expected,
        "sessions_evaluated": len(session_reports),
        "sessions_with_missing_5m_starts": sum(1 for x in session_reports if x["missing_expected_rows"] not in (None, 0)),
        "field_population": {
            field: {
                "non_null": sum(row.get(field) is not None for row in merged),
                "zero": sum(row.get(field) == 0 for row in merged if row.get(field) is not None),
            }
            for field in ("open", "high", "low", "close", "iv", "volume", "strike", "oi", "spot")
        },
        "conflict_samples": conflict_groups[:200],
        "session_samples": session_reports,
        "normalized_csv": csv_path.name,
        "interpretation": [
            "This is rolling ATM-relative data, not fixed-expiry contract history.",
            "A session with fewer than 75 rows is flagged for review, not automatically declared invalid; instrument/market holidays and API behavior must be accounted for.",
            "Historical Greeks are not provided by the documented rolling endpoint.",
            "Do not use for backtests until missing sessions, field population, and duplicate conflicts are reviewed.",
        ],
    }
    report_path = run_dir / "quality_report.json"
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print("DHAN ROLLING HISTORY OFFLINE AUDIT")
    print(f"Requests with saved responses: {report['requests_with_saved_response']}/{report['planned_requests']}")
    print(f"Empty/missing option blocks: {len(report['empty_or_missing_option_blocks'])}")
    print(f"Raw rows: {len(all_rows)}; unique timestamp+actual strike+side: {len(merged)}")
    print(f"Duplicate groups: {report['duplicate_groups_collapsed']}; conflicting groups: {len(conflict_groups)}")
    print(f"Sessions with missing expected 5m starts: {report['sessions_with_missing_5m_starts']}")
    print(f"Normalized CSV: {csv_path}")
    print(f"Quality report: {report_path}")
    incomplete = bool(report["missing_or_incomplete_requests"] or report["request_ids_missing_from_manifest"] or report["empty_or_missing_option_blocks"])
    return 0 if not incomplete else 2


if __name__ == "__main__":
    raise SystemExit(main())
