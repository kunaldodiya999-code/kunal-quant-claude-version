"""
Standalone test for unresolved_event_classifier.py.

Builds a small synthetic database using the canonical repo's own
`database.schema.initialize_database` (so the schema is guaranteed
correct), inserts a handful of hand-crafted instrument/candle rows
designed to hit each classification path, and asserts the result.

Requires KUNAL_QUANT_REPO to point at a local clone of
kunaldodiya999-code/KunalQuant (not vendored here, since this repo does
not duplicate the canonical repo's code).

Run:
    KUNAL_QUANT_REPO=/path/to/KunalQuant python3 proposals/test_classifier.py
"""

from __future__ import annotations

import datetime
import os
import sqlite3
import sys
import zoneinfo
from pathlib import Path

REPO = os.environ.get("KUNAL_QUANT_REPO")
if not REPO:
    raise SystemExit("Set KUNAL_QUANT_REPO to a local KunalQuant clone first.")
sys.path.insert(0, REPO)

from database.schema import initialize_database  # noqa: E402
from strategies.option_contract_resolver import OptionContractResolver  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from unresolved_event_classifier import (  # noqa: E402
    EventClassification,
    classify_event,
)

TZ = zoneinfo.ZoneInfo("Asia/Kolkata")


def build_synthetic_db(db_path: Path) -> dict:
    if db_path.exists():
        db_path.unlink()
    initialize_database(db_path)

    conn = sqlite3.connect(db_path)

    conn.execute(
        """INSERT INTO instruments
        (broker, exchange, segment, symbol, underlying, instrument_type,
         expiry_date, strike, option_type, lot_size, tick_size)
        VALUES ('FYERS','NSE','FO','NSE:NIFTY25060525000CE','NIFTY',
                'OPTION','2026-06-05',25000,'CE',75,0.05)"""
    )
    iid_ce = conn.execute(
        "SELECT id FROM instruments WHERE symbol='NSE:NIFTY25060525000CE'"
    ).fetchone()[0]

    conn.execute(
        """INSERT INTO instruments
        (broker, exchange, segment, symbol, underlying, instrument_type,
         expiry_date, strike, option_type, lot_size, tick_size)
        VALUES ('FYERS','NSE','FO','NSE:NIFTY25060525000PE','NIFTY',
                'OPTION','2026-06-05',25000,'PE',75,0.05)"""
    )

    signal_ts = int(
        datetime.datetime(2026, 6, 1, 9, 18, 0, tzinfo=TZ).timestamp()
    )
    conn.execute(
        """INSERT INTO candles
        (instrument_id, timestamp, open, high, low, close, volume,
         open_interest, resolution, source)
        VALUES (?, ?, 120.0, 125.0, 118.0, 122.0, 500, 10000, '1',
                'FYERS_FNO_HISTORY')""",
        (iid_ce, signal_ts + 60),
    )

    conn.commit()
    conn.close()
    return {"signal_ts": signal_ts}


def main() -> None:
    db_path = Path("/tmp/kq_classifier_synthetic.db")
    ctx = build_synthetic_db(db_path)
    resolver = OptionContractResolver(db_path)

    cases = [
        (
            "CE resolves, has a candle within 1h",
            dict(
                underlying_price=25000,
                entry_date=datetime.date(2026, 6, 1),
                direction="LONG",
                signal_timestamp=ctx["signal_ts"],
            ),
            EventClassification.RESOLVED_WITH_CANDLE,
        ),
        (
            "PE resolves, no candle within 1h",
            dict(
                underlying_price=25000,
                entry_date=datetime.date(2026, 6, 1),
                direction="SHORT",
                signal_timestamp=ctx["signal_ts"],
            ),
            EventClassification.NO_ENTRY_CANDLE,
        ),
        (
            "entry date past every known expiry",
            dict(
                underlying_price=25000,
                entry_date=datetime.date(2026, 7, 1),
                direction="LONG",
                signal_timestamp=ctx["signal_ts"],
            ),
            EventClassification.EXPIRY_NOT_FOUND,
        ),
        (
            "ATM strike with no matching instrument row",
            dict(
                underlying_price=26000,
                entry_date=datetime.date(2026, 6, 1),
                direction="LONG",
                signal_timestamp=ctx["signal_ts"],
            ),
            EventClassification.CONTRACT_NOT_FOUND,
        ),
    ]

    print("=" * 78)
    print("UNRESOLVED-EVENT CLASSIFIER — SYNTHETIC VERIFICATION")
    print("(synthetic data only; not the real 198/16 events)")
    print("=" * 78)

    failures = 0
    for label, kwargs, expected in cases:
        result = classify_event(
            resolver, database_path=db_path, **kwargs
        )
        ok = result.classification == expected
        failures += 0 if ok else 1
        status = "PASS" if ok else "FAIL"
        print(f"[{status}] {label}")
        print(f"        expected={expected.value} got={result.classification.value}")
        print(f"        detail={result.detail}")

    print()
    if failures:
        print(f"{failures} of {len(cases)} case(s) FAILED.")
        raise SystemExit(1)
    print(f"All {len(cases)} synthetic cases classified correctly.")


if __name__ == "__main__":
    main()
