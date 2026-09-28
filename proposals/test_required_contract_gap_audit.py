"""
Synthetic tests for diagnose_required_contract_gaps.py.

No FYERS calls.
No real database.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from database.schema import initialize_database

from diagnose_required_contract_gaps import (
    audit_local_contract,
    extract_option_symbols,
    option_type_from_symbol,
    strike_from_symbol,
)


def test_extract_option_symbols_actual_response_shape() -> None:
    response = {
        "data": {
            "contracts": {
                "futures": [],
                "options": [
                    "NSE:NIFTY2692223250CE",
                    "NSE:NIFTY2692223250PE",
                    "NSE:NIFTY26SEP23400CE",
                    "NSE:NIFTY50-INDEX",
                    "not-an-option",
                ],
            }
        }
    }

    assert extract_option_symbols(response) == {
        "NSE:NIFTY2692223250CE",
        "NSE:NIFTY2692223250PE",
        "NSE:NIFTY26SEP23400CE",
    }


def test_strike_and_type_parsing() -> None:
    cases = {
        "NSE:NIFTY2692223250CE": (23250, "CE"),
        "NSE:NIFTY2692223250PE": (23250, "PE"),
        "NSE:NIFTY26SEP23400CE": (23400, "CE"),
        "NSE:NIFTY24N2118200CE": (18200, "CE"),
    }

    for symbol, expected in cases.items():
        assert (
            strike_from_symbol(symbol),
            option_type_from_symbol(symbol),
        ) == expected


def test_local_contract_present_and_zero_candle(tmp_path, monkeypatch) -> None:
    import diagnose_required_contract_gaps as module

    db_path = Path(tmp_path) / "synthetic.db"
    initialize_database(db_path)

    with sqlite3.connect(db_path) as db:
        db.execute(
            """
            INSERT INTO instruments (
                broker, exchange, segment, symbol, underlying,
                instrument_type, expiry_date, strike, option_type,
                lot_size, tick_size
            )
            VALUES (
                'FYERS', 'NSE', 'FO',
                'NSE:NIFTY26SEP23400CE',
                'NIFTY', 'OPTION',
                '2026-09-24', 23400, 'CE',
                65, 0.05
            )
            """
        )
        db.commit()

    monkeypatch.setattr(module, "DATABASE_PATH", db_path)

    local = audit_local_contract(
        "2026-09-24",
        23400,
        "CE",
    )

    assert local is not None
    assert local["symbol"] == "NSE:NIFTY26SEP23400CE"
    assert local["candle_count"] == 0
