"""
Tests for diagnose_option_data_coverage_v2.build_report and
diagnose_instrument_registry.build_report, against a synthetic database
built with the canonical repo's own schema initializer.

    KUNAL_QUANT_REPO=/path/to/KunalQuant python3 proposals/test_reports.py
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
sys.path.insert(0, str(Path(__file__).resolve().parent))

from database.schema import initialize_database  # noqa: E402
from strategies.option_contract_resolver import OptionContractResolver  # noqa: E402

import diagnose_instrument_registry as registry_report  # noqa: E402
import diagnose_option_data_coverage_v2 as v2  # noqa: E402
from unresolved_event_classifier import EventClassification, classify_event  # noqa: E402

TZ = zoneinfo.ZoneInfo("Asia/Kolkata")


def ts(y, m, d, hh, mm):
    return int(datetime.datetime(y, m, d, hh, mm, tzinfo=TZ).timestamp())


def build_db(path: Path) -> None:
    if path.exists():
        path.unlink()
    initialize_database(path)
    c = sqlite3.connect(path)

    def inst(symbol, expiry, strike, opt):
        c.execute(
            """INSERT INTO instruments
            (broker, exchange, segment, symbol, underlying, instrument_type,
             expiry_date, strike, option_type, lot_size, tick_size)
            VALUES ('FYERS','NSE','FO',?,'NIFTY','OPTION',?,?,?,75,0.05)""",
            (symbol, expiry, strike, opt),
        )
        return c.execute("SELECT id FROM instruments WHERE symbol=?", (symbol,)).fetchone()[0]

    # Registered expiries: Sep 15 (limited strikes) then Sep 22 - note NO
    # Aug 25 / Sep 1 / Sep 8, so an Aug 21 signal lands on Sep 15.
    # Sep 15 exists in the registry, but only at strike 24000 (CE and PE):
    # a 24250 signal on Aug 21 lands on Sep 15 and cannot find its strike.
    inst("NSE:NIFTY2691524000CE", "2026-09-15", 24000, "CE")
    inst("NSE:NIFTY2691524000PE", "2026-09-15", 24000, "PE")
    id_ce = inst("NSE:NIFTY2692223300CE", "2026-09-22", 23300, "CE")
    inst("NSE:NIFTY2692223300PE", "2026-09-22", 23300, "PE")   # zero candles

    c.execute(
        """INSERT INTO candles
        (instrument_id, timestamp, open, high, low, close, volume,
         open_interest, resolution, source)
        VALUES (?, ?, 100, 101, 99, 100, 10, 5, '1', 'FYERS_FNO_HISTORY')""",
        (id_ce, ts(2026, 9, 16, 9, 20)),
    )
    c.commit()
    c.close()


def main() -> None:
    db = Path("/tmp/kq_reports_synthetic.db")
    build_db(db)
    resolver = OptionContractResolver(db)
    failures = []

    def check(label, ok):
        print(f"[{'PASS' if ok else 'FAIL'}] {label}")
        if not ok:
            failures.append(label)

    # ---- structured fields on classification results -----------------
    r = classify_event(resolver, underlying_price=24240, entry_date=datetime.date(2026, 8, 21),
                       direction="SHORT", signal_timestamp=ts(2026, 8, 21, 11, 57), database_path=db)
    check("CONTRACT_NOT_FOUND carries parsed expiry/strike/type "
          "(24250 PE on Sep 15 is not registered)",
          r.classification == EventClassification.CONTRACT_NOT_FOUND
          and r.expiry == datetime.date(2026, 9, 15) and r.strike == 24250 and r.option_type == "PE")

    r = classify_event(resolver, underlying_price=23300, entry_date=datetime.date(2026, 9, 16),
                       direction="SHORT", signal_timestamp=ts(2026, 9, 16, 9, 18), database_path=db)
    check("NO_OPTION_DATA carries the real symbol, not just text",
          r.classification == EventClassification.NO_OPTION_DATA
          and r.symbol == "NSE:NIFTY2692223300PE" and r.strike == 23300)

    # ---- full report over hand-made events -----------------------------
    rows = [
        v2.EventRow(ts(2026, 8, 21, 10, 30), 24250.8, "LONG", "LONG_SHORT_SPEED"),
        v2.EventRow(ts(2026, 8, 21, 10, 30), 24250.8, "LONG", "MOMENTUM_ONLY"),
        v2.EventRow(ts(2026, 9, 16, 9, 18), 23300.0, "LONG", "LONG_SHORT_SPEED"),
        v2.EventRow(ts(2026, 9, 16, 9, 18), 23300.0, "SHORT", "MOMENTUM_ONLY"),
        v2.EventRow(ts(2026, 10, 1, 9, 18), 23300.0, "LONG", "MOMENTUM_ONLY"),
    ]
    report = v2.build_report(rows, resolver, db, sample_bars=2500)

    check("counts: 5 events, 4 distinct entry moments", "KTMI events                    : 5" in report
          and "Distinct entry moments         : 4" in report)
    check("counts by strategy shown", "events from LONG_SHORT_SPEED" in report
          and "events from MOMENTUM_ONLY" in report)
    check("category totals correct (1 resolved, 1 no-data, 2 not-found, 1 expiry-not-found)",
          "RESOLVED_WITH_CANDLE    : 1" in report and "NO_OPTION_DATA          : 1" in report
          and "CONTRACT_NOT_FOUND      : 2" in report and "EXPIRY_NOT_FOUND        : 1" in report)
    check("resolved contracts grouped by real symbol (regression: was 'NSE')",
          "NSE:NIFTY2692223300CE" in report and "NSE:NIFTY2692223300PE" in report)
    check("per-expiry table shows Sep 15 as the landed expiry",
          "2026-09-15" in report and "BY EXPIRY THE RESOLVER LANDED ON" in report)
    check("worklist 1 lists the missing contract, 2 events affected",
          "NIFTY 2026-09-15 24250 CE   [2]" in report)
    check("worklist 2 lists the registered-but-empty contract",
          "NSE:NIFTY2692223300PE   [1]" in report)

    # ---- registry report --------------------------------------------------
    reg = registry_report.build_report(db, datetime.date(2026, 1, 1))
    check("registry lists both registered expiries", "2026-09-15" in reg and "2026-09-22" in reg)
    check("registry flags the 7-day Sep 15 -> Sep 22 step as NOT a gap", "none" in reg)

    # add a wide hole and re-run
    c = sqlite3.connect(db)
    c.execute("""INSERT INTO instruments
        (broker, exchange, segment, symbol, underlying, instrument_type,
         expiry_date, strike, option_type, lot_size, tick_size)
        VALUES ('FYERS','NSE','FO','NSE:NIFTY2680423000CE','NIFTY','OPTION','2026-08-04',23000,'CE',75,0.05)""")
    c.commit()
    c.close()
    reg = registry_report.build_report(db, datetime.date(2026, 1, 1))
    check("registry flags Aug 4 -> Sep 15 (42 days) as a gap", "42 days" in reg)

    # registry script must not be able to write
    try:
        ro = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
        ro.execute("DELETE FROM instruments")
        wrote = True
    except sqlite3.OperationalError:
        wrote = False
    check("read-only connection mode really blocks writes", not wrote)

    print()
    if failures:
        print(f"{len(failures)} FAILED: {failures}")
        raise SystemExit(1)
    print("All report checks passed.")
    print("\n----- sample of the report as the user will see it -----")
    print(report[:1800])


if __name__ == "__main__":
    main()
