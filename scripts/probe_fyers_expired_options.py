"""Read-only FYERS expired-option API probe.

No database writes. Used to confirm the broker's historical contract-discovery
response shape before implementing targeted option acquisition.
"""
from __future__ import annotations

import json
from api.fyers_client import FyersClient

UNDERLYING_SYMBOL = "NSE:NIFTY50-INDEX"
PROBE_EXPIRY = "2026-09-22"


def main() -> None:
    client = FyersClient()

    print("=" * 90)
    print("KUNAL QUANT — FYERS EXPIRED OPTION API PROBE")
    print("=" * 90)
    print("READ-ONLY — no database changes")
    print()

    print(f"EXPIRY DATES: {UNDERLYING_SYMBOL}")
    response = client.expired_expiry_dates(
        symbol=UNDERLYING_SYMBOL,
        range_from="2026-08-01",
        range_to="2026-09-23",
    )
    print(json.dumps(response, indent=2, default=str))

    print()
    print(f"CONTRACTS FOR {PROBE_EXPIRY}: {UNDERLYING_SYMBOL}")
    response = client.expired_contracts(
        symbol=UNDERLYING_SYMBOL,
        expiry_date=PROBE_EXPIRY,
    )
    print(json.dumps(response, indent=2, default=str))


if __name__ == "__main__":
    main()
