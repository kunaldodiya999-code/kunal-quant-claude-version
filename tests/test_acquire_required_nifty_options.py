from scripts.acquire_required_nifty_options import (
    _discover_required_symbols,
    _extract_symbols,
    _option_type_from_symbol,
    _strike_from_symbol,
)


def test_extract_symbols_and_parse_contract():
    response = {
        "data": {
            "symbols": [
                "NSE:NIFTY2692223250CE",
                "NSE:NIFTY2692223250PE",
                "ignore-me",
            ]
        }
    }
    symbols = _extract_symbols(response)
    assert "NSE:NIFTY2692223250CE" in symbols
    assert "NSE:NIFTY2692223250PE" in symbols
    assert _strike_from_symbol("NSE:NIFTY2692223250CE") == 23250
    assert _option_type_from_symbol("NSE:NIFTY2692223250PE") == "PE"


def test_extract_symbols_ignores_non_option_values():
    assert _extract_symbols({"data": {"symbols": ["NSE:NIFTY50-INDEX", "x"]}}) == set()


def test_fyers_encoded_symbol_strike_parsing():
    assert _strike_from_symbol("NSE:NIFTY2692223250CE") == 23250
    assert _strike_from_symbol("NSE:NIFTY2692223250PE") == 23250
    assert _strike_from_symbol("NSE:NIFTY2692229100CE") == 29100


def test_discover_required_symbols_from_fyers_response():
    class FakeClient:
        def expired_contracts(self, symbol, expiry_date):
            assert symbol == "NSE:NIFTY50-INDEX"
            assert expiry_date == "2026-09-22"

            return {
                "code": 200,
                "data": {
                    "symbol": "NIFTY",
                    "expiry_date": "2026-09-22",
                    "contracts": {
                        "futures": [],
                        "options": [
                            "NSE:NIFTY2692223250CE",
                            "NSE:NIFTY2692223250PE",
                            "NSE:NIFTY2692223300CE",
                            "NSE:NIFTY2692223300PE",
                        ],
                    },
                },
                "message": "",
                "s": "ok",
            }

    required = {
        "2026-09-22": {
            (23250, "CE"): ("2026-09-16", "2026-09-17"),
            (23250, "PE"): ("2026-09-17", "2026-09-17"),
            (23300, "CE"): ("2026-09-16", "2026-09-18"),
        }
    }

    discovered = _discover_required_symbols(
        FakeClient(),
        required,
    )

    assert discovered == {
        ("2026-09-22", 23250, "CE"): "NSE:NIFTY2692223250CE",
        ("2026-09-22", 23250, "PE"): "NSE:NIFTY2692223250PE",
        ("2026-09-22", 23300, "CE"): "NSE:NIFTY2692223300CE",
    }
