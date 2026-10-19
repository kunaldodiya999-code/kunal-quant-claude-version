"""Compare Dhan rolling-options expiry codes 1/2/3 with a small read-only test.

Dhan support has stated that the expired-options endpoint uses 1=near, 2=next,
3=far (distinct from some other API expiry-code mappings). The rolling-options
response may not include the actual expiry date, so this script compares response
fingerprints but cannot independently prove the contract expiry date.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from api.dhan_client import DhanAPIError, DhanClient  # noqa: E402


def default_dates() -> tuple[str, str]:
    end = date.today()
    return (end - timedelta(days=1)).isoformat(), end.isoformat()


def summarize(result: dict[str, Any], option_type: str) -> dict[str, Any]:
    data = result.get("data") or {}
    key = "ce" if option_type == "CALL" else "pe"
    block = data.get(key)
    if not isinstance(block, dict):
        return {"rows": 0, "error": "Expected option-side data block missing"}

    timestamps = block.get("timestamp") or []
    strikes = block.get("strike") or []
    spots = block.get("spot") or []
    closes = block.get("close") or []
    n = len(timestamps)
    return {
        "rows": n,
        "first_timestamp": timestamps[0] if n else None,
        "last_timestamp": timestamps[-1] if n else None,
        "first_strike": strikes[0] if strikes else None,
        "last_strike": strikes[-1] if strikes else None,
        "unique_strikes": len(set(strikes)),
        "first_spot": spots[0] if spots else None,
        "last_spot": spots[-1] if spots else None,
        "first_close": closes[0] if closes else None,
        "last_close": closes[-1] if closes else None,
        "has_expiry_date_field": any("expir" in str(k).lower() for k in block.keys()),
        "fields": sorted(block.keys()),
    }


def main() -> int:
    default_from, default_to = default_dates()
    parser = argparse.ArgumentParser(description="Compare Dhan expired-options expiry codes 1, 2, and 3.")
    parser.add_argument("--from-date", default=default_from)
    parser.add_argument("--to-date", default=default_to, help="Exclusive end date")
    parser.add_argument("--expiry-flag", choices=["WEEK", "MONTH"], default="WEEK")
    parser.add_argument("--strike", default="ATM")
    parser.add_argument("--option-type", choices=["CALL", "PUT"], default="CALL")
    args = parser.parse_args()

    client = DhanClient()
    report: dict[str, Any] = {
        "date_range": {"from_inclusive": args.from_date, "to_exclusive": args.to_date},
        "expiry_flag": args.expiry_flag,
        "strike": args.strike,
        "option_type": args.option_type,
        "codes": {},
        "conclusion": (
            "This compares data fingerprints only. If the API response omits the actual expiry date, "
            "the output cannot establish the exact contract expiry; obtain that mapping from Dhan "
            "or independently validate against known contract records before backtesting."
        ),
    }

    print("=" * 70)
    print("KUNAL QUANT — DHAN EXPIRED-OPTIONS EXPIRY-CODE CHECK")
    print("=" * 70)
    print(f"Range: {args.from_date} to {args.to_date} (end exclusive)")
    print(f"Expiry flag: {args.expiry_flag} | strike: {args.strike} | type: {args.option_type}")
    print("Requests: 3 | read-only | no database writes | no orders")

    for code in (1, 2, 3):
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
            report["codes"][str(code)] = {"request_error": str(exc)}
            print(f"Code {code}: FAILED — {exc}")
            continue

        summary = summarize(result, args.option_type)
        report["codes"][str(code)] = summary
        print(
            f"Code {code}: rows={summary.get('rows', 0)}, "
            f"strikes={summary.get('unique_strikes', 'n/a')}, "
            f"first/last strike={summary.get('first_strike')}/{summary.get('last_strike')}, "
            f"expiry date exposed={summary.get('has_expiry_date_field', False)}"
        )

    out_dir = PROJECT_ROOT / "data" / "raw" / "dhan_smoke"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"expiry_code_check_{args.from_date}_{args.to_date}_{args.expiry_flag}_{args.strike}_{args.option_type}.json"
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Report saved: {out_path.relative_to(PROJECT_ROOT)}")
    print("LIMITATION: different output fingerprints do not prove the exact expiry date.")
    return 0 if all("request_error" not in report["codes"].get(str(code), {}) for code in (1, 2, 3)) else 1


if __name__ == "__main__":
    raise SystemExit(main())
