from __future__ import annotations

import sqlite3
from datetime import date, timedelta

import pytest

from scripts.repair_nifty_option_candles import build_chunks, load_repair_candidates


def test_build_chunks_are_inclusive_non_overlapping_and_bounded():
    chunks = build_chunks("2024-01-01", "2024-01-31", 15)
    assert chunks == [
        ("2024-01-01", "2024-01-15"),
        ("2024-01-16", "2024-01-30"),
        ("2024-01-31", "2024-01-31"),
    ]


def test_build_chunks_reject_invalid_inputs():
    with pytest.raises(ValueError):
        build_chunks("2024-02-02", "2024-02-01", 10)
    with pytest.raises(ValueError):
        build_chunks("2024-01-01", "2024-01-02", 0)


def test_repair_candidates_include_empty_and_partial_but_respect_threshold(tmp_path):
    database = tmp_path / "repair.sqlite"
    with sqlite3.connect(database) as db:
        db.executescript("""
            CREATE TABLE instruments (
                id INTEGER PRIMARY KEY, broker TEXT, underlying TEXT, option_type TEXT,
                expiry_date TEXT, strike REAL, symbol TEXT
            );
            CREATE TABLE candles (
                instrument_id INTEGER, resolution TEXT, source TEXT, timestamp INTEGER
            );
            INSERT INTO instruments VALUES
                (1, 'FYERS', 'NIFTY', 'CE', '2020-01-02', 10000, 'NSE:NIFTY2000210000CE'),
                (2, 'FYERS', 'NIFTY', 'PE', '2020-01-02', 10000, 'NSE:NIFTY2000210000PE'),
                (3, 'FYERS', 'NIFTY', 'CE', '2020-01-02', 10100, 'NSE:NIFTY2000210100CE'),
                (4, 'FYERS', 'BANKNIFTY', 'CE', '2020-01-02', 10000, 'NSE:BANKNIFTY2000210000CE');
            INSERT INTO candles
                SELECT 2, '1', 'FYERS_FNO_HISTORY', value
                FROM (SELECT 1 AS value UNION ALL SELECT 2 UNION ALL SELECT 3);
            INSERT INTO candles
                SELECT 3, '1', 'FYERS_FNO_HISTORY', value
                FROM (SELECT 1 AS value UNION ALL SELECT 2 UNION ALL SELECT 3 UNION ALL SELECT 4 UNION ALL SELECT 5);
        """)
    rows = load_repair_candidates(database, limit=None, min_candles=5)
    assert [(row["instrument_id"], row["existing_candles"]) for row in rows] == [(1, 0), (2, 3)]
    rows = load_repair_candidates(
        database, limit=None, min_candles=5, symbols=["NSE:NIFTY2000210000PE"]
    )
    assert [row["instrument_id"] for row in rows] == [2]
