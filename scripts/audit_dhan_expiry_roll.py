"""Forensic audit of Dhan rolling-option expiry behavior across five sessions.

Read-only: 3 API requests (expiry codes 1/2/3), no database writes or orders.
Compares actual strikes and aligned observations. Results do NOT identify exact
contract expiry because the endpoint response does not expose expiry_date.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from api.dhan_client import DhanAPIError, DhanClient  # noqa: E402

IST = ZoneInfo("Asia/Kolkata")
FIELDS = ("timestamp", "strike", "spot", "open", "high", "low", "close", "iv", "volume", "oi")


def rows_from_response(result: dict[str, Any], option_type: str) -> list[dict[str, Any]]:
    block = (result.get("data") or {}).get("ce" if option_type == "CALL" else "pe")
    if not isinstance(block, dict):
        return []
    timestamps = block.get("timestamp") or []
    rows: list[dict[str, Any]] = []
    for i, ts in enumerate(timestamps):
        row: dict[str, Any] = {"timestamp": int(ts)}
        for field in FIELDS:
            if field == "timestamp":
                continue
            values = block.get(field)
            row[field] = values[i] if isinstance(values, list) and i < len(values) else None
        row["date_ist"] = datetime.fromtimestamp(int(ts), IST).date().isoformat()
        row["time_ist"] = datetime.fromtimestamp(int(ts), IST).strftime("%H:%M:%S")
        rows.append(row)
    return rows


def fmt(value: Any) -> str:
    return "n/a" if value is None else str(value)


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit Dhan rolling-option expiry behavior (read-only).")
    parser.add_argument("--from-date", default="2026-10-05", help="YYYY-MM-DD")
    parser.add_argument("--to-date", default="2026-10-10", help="YYYY-MM-DD; API end behavior is audited, not assumed")
    parser.add_argument("--expiry-flag", choices=("WEEK", "MONTH"), default="WEEK")
    parser.add_argument("--strike", default="ATM")
    parser.add_argument("--option-type", choices=("CALL", "PUT"), default="CALL")
    parser.add_argument("--delay", type=float, default=0.3)
    args = parser.parse_args()

    client = DhanClient()
    all_by_code: dict[int, list[dict[str, Any]]] = {}
    report: dict[str, Any] = {
        "request": vars(args),
        "timezone": "Asia/Kolkata",
        "safety": "read-only; no database writes; no orders",
        "expiry_codes": {},
        "aligned_code_comparison": [],
        "limitations": [
            "No expiry_date or stable contract identifier was returned in the inspected response.",
            "ATM-relative rolling data can change actual strike; a strike change is not itself proof of an expiry roll.",
            "Aligned code differences and price jumps cannot establish exact contract expiry identity.",
        ],
    }

    print("=" * 76)
    print("KUNAL QUANT — DHAN EXPIRY-ROLL FORENSIC AUDIT")
    print("=" * 76)
    print(f"Window: {args.from_date} to {args.to_date}; expiry={args.expiry_flag}; strike={args.strike}; type={args.option_type}")
    print("Three requests total (codes 1, 2, 3); read-only; no DB writes or orders.")

    for index, code in enumerate((1, 2, 3)):
        try:
            result = client.rolling_options(
                from_date=args.from_date,
                to_date=args.to_date,
                expiry_flag=args.expiry_flag,
                expiry_code=code,
                strike=args.strike,
                option_type=args.option_type,
                interval="1",
            )
        except (DhanAPIError, RuntimeError, ValueError) as exc:
            print(f"FAILED code {code}: {exc}")
            return 1

        rows = rows_from_response(result, args.option_type)
        all_by_code[code] = rows
        date_counts = Counter(row["date_ist"] for row in rows)
        daily: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            daily.setdefault(row["date_ist"], []).append(row)

        daily_summary: dict[str, Any] = {}
        transition_samples: list[dict[str, Any]] = []
        strike_transitions = 0
        for day, day_rows in sorted(daily.items()):
            day_rows.sort(key=lambda row: row["timestamp"])
            strikes = [row["strike"] for row in day_rows if row.get("strike") is not None]
            changes = []
            for prev, cur in zip(day_rows, day_rows[1:]):
                if prev.get("strike") is not None and cur.get("strike") is not None and prev["strike"] != cur["strike"]:
                    strike_transitions += 1
                    change = {
                        "time_ist": cur["time_ist"],
                        "previous_strike": prev["strike"],
                        "new_strike": cur["strike"],
                        "previous_close": prev.get("close"),
                        "new_close": cur.get("close"),
                        "spot": cur.get("spot"),
                    }
                    changes.append(change)
                    if len(transition_samples) < 12:
                        transition_samples.append({"date_ist": day, **change})
            daily_summary[day] = {
                "rows": len(day_rows),
                "first_time_ist": day_rows[0]["time_ist"],
                "last_time_ist": day_rows[-1]["time_ist"],
                "first_strike": day_rows[0].get("strike"),
                "last_strike": day_rows[-1].get("strike"),
                "unique_actual_strikes": len(set(strikes)),
                "strike_change_events": len(changes),
                "first_close": day_rows[0].get("close"),
                "last_close": day_rows[-1].get("close"),
                "first_spot": day_rows[0].get("spot"),
                "last_spot": day_rows[-1].get("spot"),
            }

        report["expiry_codes"][str(code)] = {
            "total_rows": len(rows),
            "date_counts_IST": dict(sorted(date_counts.items())),
            "daily": daily_summary,
            "strike_change_event_count": strike_transitions,
            "strike_change_samples": transition_samples,
            "rows": rows,
        }
        print(f"\nCODE {code}: rows={len(rows)}; IST dates={dict(sorted(date_counts.items()))}")
        for day, summary in sorted(daily_summary.items()):
            print(
                f"  {day}: n={summary['rows']} "
                f"strike {fmt(summary['first_strike'])}->{fmt(summary['last_strike'])} "
                f"(unique={summary['unique_actual_strikes']}, changes={summary['strike_change_events']}), "
                f"close {fmt(summary['first_close'])}->{fmt(summary['last_close'])}, "
                f"spot {fmt(summary['first_spot'])}->{fmt(summary['last_spot'])}"
            )
        if index < 2 and args.delay > 0:
            time.sleep(args.delay)

    # Compare codes only at identical epoch timestamps; also flag if the actual
    # strikes differ, so price comparisons are not mistaken for same-contract comparisons.
    maps = {
        code: {int(row["timestamp"]): row for row in rows}
        for code, rows in all_by_code.items()
    }
    common = sorted(set(maps[1]) & set(maps[2]) & set(maps[3]))
    aligned: list[dict[str, Any]] = []
    strike_match_count = 0
    price_match_count = 0
    for ts in common:
        a, b, c = (maps[code][ts] for code in (1, 2, 3))
        strikes = [a.get("strike"), b.get("strike"), c.get("strike")]
        closes = [a.get("close"), b.get("close"), c.get("close")]
        strike_match = len(set(strikes)) == 1
        close_match = len(set(closes)) == 1
        strike_match_count += int(strike_match)
        price_match_count += int(close_match)
        if len(aligned) < 30 or (not strike_match and len(aligned) < 60):
            aligned.append({
                "timestamp": ts,
                "date_ist": a["date_ist"],
                "time_ist": a["time_ist"],
                "code1_strike": strikes[0], "code1_close": closes[0],
                "code2_strike": strikes[1], "code2_close": closes[1],
                "code3_strike": strikes[2], "code3_close": closes[2],
                "all_codes_same_strike": strike_match,
                "all_codes_same_close": close_match,
            })
    report["aligned_code_comparison"] = aligned
    report["aligned_summary"] = {
        "timestamps_common_to_all_three_codes": len(common),
        "same_actual_strike_across_all_codes_count": strike_match_count,
        "same_close_across_all_codes_count": price_match_count,
        "note": "A close-price comparison is contract-equivalent only when actual strikes and expiry identities also match; expiry identity is unavailable here.",
    }

    out_dir = PROJECT_ROOT / "data" / "raw" / "dhan_smoke"
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = f"expiry_roll_audit_{args.from_date}_{args.to_date}_{args.expiry_flag}_{args.strike}_{args.option_type}"
    out_path = out_dir / f"{stem}.json"
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print("\nALIGNED TIMESTAMP COMPARISON")
    print(f"Common timestamps across codes: {len(common)}")
    print(f"Same actual strike across all codes: {strike_match_count}/{len(common)}")
    print(f"Same close across all codes: {price_match_count}/{len(common)}")
    print("\nLIMITATION: this audits rolling behavior; it does not prove exact expiry dates.")
    print(f"Full report (raw observations included): {out_path.relative_to(PROJECT_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
