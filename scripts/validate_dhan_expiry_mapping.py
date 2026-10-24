"""Compare Dhan expiry codes across a known NIFTY weekly-expiry boundary.

Read-only: 9 API requests (codes 1/2/3 across three one-day windows), no DB writes.
NIFTY weekly expiry on 2026-10-06 is used as a boundary test. This is a diagnostic,
not proof of expiry identity: the endpoint response may omit the actual expiry date.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from collections import Counter
from datetime import date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from api.dhan_client import DhanAPIError, DhanClient  # noqa: E402

DEFAULT_WINDOWS = [
    ("before_weekly_expiry", "2026-10-05", "2026-10-06"),
    ("weekly_expiry_day", "2026-10-06", "2026-10-07"),
    ("after_weekly_expiry", "2026-10-07", "2026-10-08"),
]
FIELDS = ("timestamp", "strike", "spot", "open", "high", "low", "close", "iv", "volume", "oi")


def summarize(result: dict[str, Any], option_type: str) -> dict[str, Any]:
    data = result.get("data") or {}
    block = data.get("ce" if option_type == "CALL" else "pe")
    if not isinstance(block, dict):
        return {"rows": 0, "error": "missing option-side data block"}
    timestamps = block.get("timestamp") or []
    rows = []
    for i, ts in enumerate(timestamps):
        row = {"timestamp": ts}
        for field in FIELDS:
            if field == "timestamp":
                continue
            values = block.get(field)
            row[field] = values[i] if isinstance(values, list) and i < len(values) else None
        rows.append(row)
    canonical = json.dumps(rows, sort_keys=True, separators=(",", ":"), default=str).encode()
    strikes = [r["strike"] for r in rows if r.get("strike") is not None]
    session_counts = Counter(
        datetime.fromtimestamp(int(ts), ZoneInfo("Asia/Kolkata")).date().isoformat()
        for ts in timestamps
    )
    return {
        "rows": len(rows),
        "session_date_counts_IST": dict(sorted(session_counts.items())),
        "fingerprint_sha256": hashlib.sha256(canonical).hexdigest(),
        "first_timestamp": timestamps[0] if timestamps else None,
        "last_timestamp": timestamps[-1] if timestamps else None,
        "first_strike": strikes[0] if strikes else None,
        "last_strike": strikes[-1] if strikes else None,
        "unique_strikes": len(set(strikes)),
        "first_close": rows[0].get("close") if rows else None,
        "last_close": rows[-1].get("close") if rows else None,
        "first_oi": rows[0].get("oi") if rows else None,
        "last_oi": rows[-1].get("oi") if rows else None,
        "has_expiry_date_field": any("expir" in str(k).lower() for k in block),
        "fields": sorted(block.keys()),
        "sample_rows": [rows[i] for i in sorted(set([0, len(rows)//2, len(rows)-1]))] if rows else [],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate Dhan expiry-code behavior across NIFTY expiry.")
    parser.add_argument("--expiry-flag", choices=["WEEK", "MONTH"], default="WEEK")
    parser.add_argument("--option-type", choices=["CALL", "PUT"], default="CALL")
    parser.add_argument("--strike", default="ATM")
    parser.add_argument("--delay", type=float, default=0.3, help="Seconds between requests")
    args = parser.parse_args()

    client = DhanClient()
    report = {
        "instrument": "NIFTY index options (securityId 13)",
        "boundary": "NIFTY weekly expiry 2026-10-06",
        "expiry_flag": args.expiry_flag,
        "option_type": args.option_type,
        "strike_request": args.strike,
        "windows": {},
        "interpretation": (
            "Compare code fingerprints and sample observations across the expiry boundary. "
            "Different data does not independently prove the exact contract expiry. "
            "No expiry date was observed in the response fields in the prior smoke test; "
            "confirm mapping with Dhan or a trusted contract master before backtesting."
        ),
    }
    print("=" * 74)
    print("KUNAL QUANT — DHAN EXPIRY MAPPING BOUNDARY VALIDATION")
    print("=" * 74)
    print("Read-only: 9 API requests, no database writes, no orders.")
    print("Windows: 2026-10-05, 2026-10-06, 2026-10-07 (each end date exclusive).")

    request_count = 0
    failures = 0
    for label, start, end in DEFAULT_WINDOWS:
        report["windows"][label] = {"from_date": start, "to_date_exclusive": end, "codes": {}}
        print(f"\n[{label}] {start} to {end} (exclusive)")
        for code in (1, 2, 3):
            request_count += 1
            try:
                result = client.rolling_options(
                    from_date=start, to_date=end, expiry_flag=args.expiry_flag,
                    expiry_code=code, strike=args.strike, option_type=args.option_type, interval="1",
                )
                summary = summarize(result, args.option_type)
                report["windows"][label]["codes"][str(code)] = summary
                print(
                    f"  code {code}: rows={summary.get('rows', 0)}, "
                    f"strikes={summary.get('unique_strikes', 'n/a')}, "
                    f"first/last strike={summary.get('first_strike')}/{summary.get('last_strike')}, "
                    f"first/last close={summary.get('first_close')}/{summary.get('last_close')}, "
                    f"expiry field={summary.get('has_expiry_date_field', False)}, "
                    f"hash={summary.get('fingerprint_sha256', 'n/a')[:12]}"
                )
            except (DhanAPIError, RuntimeError, ValueError) as exc:
                failures += 1
                report["windows"][label]["codes"][str(code)] = {"request_error": str(exc)}
                print(f"  code {code}: FAILED — {exc}")
            if request_count < 9 and args.delay > 0:
                time.sleep(args.delay)

    out_dir = PROJECT_ROOT / "data" / "raw" / "dhan_smoke"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"expiry_mapping_boundary_{args.expiry_flag}_{args.strike}_{args.option_type}.json"
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"\nReport saved: {out_path.relative_to(PROJECT_ROOT)}")
    print("DATE-COVERAGE CHECK: compare returned IST dates with each requested one-day window;")
    print("if the end date appears, endpoint behavior differs from the documented exclusive end.")
    print("LIMITATION: fingerprints show response differences, not the exact expiry date.")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
