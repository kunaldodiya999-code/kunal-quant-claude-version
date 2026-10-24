"""Read-only smoke test for DhanHQ rolling/expired NIFTY options data.

Example:
  python scripts/test_dhan_expired_options.py --from-date 2026-10-06 --to-date 2026-10-07

Requires DHAN_ACCESS_TOKEN in the local .env and an active Dhan Data API
subscription. It performs one request only and never places orders.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from api.dhan_client import DhanAPIError, DhanClient  # noqa: E402


def _default_dates() -> tuple[str, str]:
    # A recent completed trading day; user can override explicitly.
    end = date.today()
    start = end - timedelta(days=1)
    return start.isoformat(), end.isoformat()


def main() -> int:
    default_from, default_to = _default_dates()
    parser = argparse.ArgumentParser(description="Test one Dhan expired-options API request.")
    parser.add_argument("--from-date", default=default_from, help="YYYY-MM-DD, inclusive")
    parser.add_argument("--to-date", default=default_to, help="YYYY-MM-DD, exclusive")
    parser.add_argument("--expiry-flag", choices=["WEEK", "MONTH"], default="WEEK")
    parser.add_argument("--expiry-code", type=int, choices=[1, 2, 3], default=1)
    parser.add_argument("--strike", default="ATM", help="ATM or ATM+/-1..10")
    parser.add_argument("--option-type", choices=["CALL", "PUT"], default="CALL")
    parser.add_argument("--interval", choices=["1", "5", "15", "25", "60"], default="1")
    args = parser.parse_args()

    print("=" * 68)
    print("KUNAL QUANT — DHAN EXPIRED OPTIONS SMOKE TEST")
    print("=" * 68)
    print("Mode          : read-only; one API request; no database writes")
    print(f"Date range    : {args.from_date} to {args.to_date} (to-date exclusive)")
    print(f"Expiry        : {args.expiry_flag}, code={args.expiry_code} (1=near, 2=next, 3=far)")
    print(f"Strike/type   : {args.strike} / {args.option_type}")
    print(f"Interval      : {args.interval} minute(s)")

    try:
        client = DhanClient()
        result = client.rolling_options(
            from_date=args.from_date,
            to_date=args.to_date,
            expiry_flag=args.expiry_flag,
            expiry_code=args.expiry_code,
            strike=args.strike,
            option_type=args.option_type,
            interval=args.interval,
        )
    except (DhanAPIError, RuntimeError, ValueError) as exc:
        print(f"RESULT: FAILED — {exc}")
        print("No credentials were printed. Check Data API subscription, token validity, and request parameters.")
        return 1

    data = result.get("data")
    if not isinstance(data, dict):
        print("RESULT: RESPONSE RECEIVED, BUT NO 'data' OBJECT WAS FOUND")
        print("Top-level keys:", sorted(result.keys()))
        return 2

    # Dhan's response arrays can be large; save the raw sample locally for
    # inspection without dumping the entire payload to the terminal.
    output = PROJECT_ROOT / "data" / "raw" / "dhan_smoke" / (
        f"rollingoption_{args.from_date}_{args.to_date}_{args.expiry_flag}_{args.strike}_{args.option_type}.json"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2), encoding="utf-8")

    print("RESULT: API RESPONSE RECEIVED")
    print("Top-level keys:", sorted(result.keys()))
    for side in ("ce", "pe"):
        block = data.get(side)
        if isinstance(block, dict):
            timestamps = block.get("timestamp") or []
            print(
                f"{side.upper()}: rows={len(timestamps)}, "
                f"fields={','.join(sorted(block.keys()))}, "
                f"first_timestamp={timestamps[0] if timestamps else 'n/a'}, "
                f"last_timestamp={timestamps[-1] if timestamps else 'n/a'}"
            )
        else:
            print(f"{side.upper()}: no data")
    print(f"Raw response saved locally: {output.relative_to(PROJECT_ROOT)}")
    print("IMPORTANT: This validates access and response shape only; no candles were imported.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
