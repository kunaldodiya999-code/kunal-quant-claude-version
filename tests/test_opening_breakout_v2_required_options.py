from datetime import date, datetime
import sqlite3
from zoneinfo import ZoneInfo

from scripts.audit_opening_breakout_v2_required_options import (
    RequiredContract,
    audit_coverage,
    option_type_for_direction,
    trigger_for_instrument,
)

IST = ZoneInfo("Asia/Kolkata")


def make_db(path):
    with sqlite3.connect(path) as db:
        db.executescript(
            """
            CREATE TABLE instruments (
                id INTEGER PRIMARY KEY,
                broker TEXT,
                underlying TEXT,
                expiry_date TEXT,
                strike INTEGER,
                option_type TEXT,
                symbol TEXT
            );
            CREATE TABLE candles (
                instrument_id INTEGER,
                timestamp INTEGER,
                open REAL,
                high REAL,
                low REAL,
                close REAL,
                resolution TEXT,
                source TEXT
            );
            """
        )


def session_ts(minute_index):
    return int(
        datetime(2026, 9, 23, 9, 15, tzinfo=IST).timestamp()
    ) + minute_index * 60


def test_direction_maps_to_option_type():
    assert option_type_for_direction("LONG") == "CE"
    assert option_type_for_direction("SHORT") == "PE"


def test_direction_uses_matching_breakout_trigger():
    assert trigger_for_instrument("CALL") == "CANDLE_HIGH"
    assert trigger_for_instrument("PUT") == "CANDLE_LOW"


def test_required_option_coverage_classifies_complete_partial_empty_and_unregistered(tmp_path):
    db_path = tmp_path / "coverage.db"
    make_db(db_path)

    with sqlite3.connect(db_path) as db:
        db.executemany(
            "INSERT INTO instruments VALUES (?,?,?,?,?,?,?)",
            [
                (1, "FYERS", "NIFTY", "2026-09-24", 25000, "CE", "NSE:NIFTY26SEP25000CE"),
                (2, "FYERS", "NIFTY", "2026-09-24", 25050, "CE", "NSE:NIFTY26SEP25050CE"),
                (3, "FYERS", "NIFTY", "2026-09-24", 25100, "CE", "NSE:NIFTY26SEP25100CE"),
            ],
        )
        db.executemany(
            "INSERT INTO candles VALUES (?,?,?,?,?,?,?,?)",
            [
                (1, session_ts(i), 1, 1, 1, 1, "1", "FYERS_FNO_HISTORY")
                for i in range(375)
            ],
        )
        db.executemany(
            "INSERT INTO candles VALUES (?,?,?,?,?,?,?,?)",
            [
                (2, session_ts(i), 1, 1, 1, 1, "1", "FYERS_FNO_HISTORY")
                for i in range(10)
            ],
        )
        db.commit()

    items = [
        RequiredContract(date(2026, 9, 23), session_ts(20), "LONG", "CE", 25000, date(2026, 9, 24), 1, "NSE:NIFTY26SEP25000CE"),
        RequiredContract(date(2026, 9, 23), session_ts(20), "LONG", "CE", 25050, date(2026, 9, 24), 2, "NSE:NIFTY26SEP25050CE"),
        RequiredContract(date(2026, 9, 23), session_ts(20), "LONG", "CE", 25100, date(2026, 9, 24), 3, "NSE:NIFTY26SEP25100CE"),
        RequiredContract(date(2026, 9, 23), session_ts(20), "LONG", "CE", 25150, date(2026, 9, 24), None, None),
    ]

    results = audit_coverage(db_path, items)
    statuses = {(r["strike"], r["status"]) for r in results}

    assert (25000, "COMPLETE") in statuses
    assert (25050, "PARTIAL") in statuses
    assert (25100, "EMPTY") in statuses
    assert (25150, "UNREGISTERED") in statuses


def test_required_option_coverage_accepts_short_special_session_when_session_length_matches(tmp_path):
    db_path = tmp_path / "muhurat.db"
    make_db(db_path)

    with sqlite3.connect(db_path) as db:
        db.execute(
            "INSERT INTO instruments VALUES (?,?,?,?,?,?,?)",
            (10, "FYERS", "NIFTY", "2025-10-28", 25900, "PE", "NSE:NIFTY25OCT25900PE"),
        )
        db.executemany(
            "INSERT INTO candles VALUES (?,?,?,?,?,?,?,?)",
            [
                (10, session_ts(i), 1, 1, 1, 1, "1", "FYERS_FNO_HISTORY")
                for i in range(61)
            ],
        )
        db.commit()

    item = RequiredContract(
        date(2026, 9, 23),
        session_ts(20),
        "SHORT",
        "PE",
        25900,
        date(2026, 9, 24),
        10,
        "NSE:NIFTY25OCT25900PE",
    )

    results = audit_coverage(
        db_path,
        [item],
        expected_candles_by_date={date(2026, 9, 23): 61},
    )

    assert results[0]["status"] == "COMPLETE"
    assert results[0]["candles"] == 61
