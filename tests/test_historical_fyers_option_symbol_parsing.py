from instruments.instrument_manager import InstrumentManager


def test_historical_unpadded_month_symbol():
    record = InstrumentManager._build_expired_instrument(
        symbol="NSE:NIFTY2110710600CE",
        underlying="NIFTY",
        expiry_date="2021-01-07",
    )
    assert record["option_type"] == "CE"
    assert record["strike"] == 10600.0
    assert record["expiry_date"] == "2021-01-07"


def test_historical_unpadded_month_put():
    record = InstrumentManager._build_expired_instrument(
        symbol="NSE:NIFTY2110720000PE",
        underlying="NIFTY",
        expiry_date="2021-01-07",
    )
    assert record["option_type"] == "PE"
    assert record["strike"] == 20000.0


def test_monthly_symbol_does_not_consume_strike_as_expiry_day():
    cases = [
        ("NSE:NIFTY24NOV28000CE", "2024-11-28", "CE"),
        ("NSE:NIFTY24NOV28000PE", "2024-11-28", "PE"),
        ("NSE:NIFTY25APR24000CE", "2025-04-24", "CE"),
        ("NSE:NIFTY26SEP29000CE", "2026-09-29", "CE"),
        ("NSE:NIFTY26SEP29000PE", "2026-09-29", "PE"),
    ]

    for symbol, expiry_date, option_type in cases:
        record = InstrumentManager._build_expired_instrument(
            symbol=symbol,
            underlying="NIFTY",
            expiry_date=expiry_date,
        )
        assert record["option_type"] == option_type
        assert record["strike"] > 0
        assert record["strike"] % 50 == 0
