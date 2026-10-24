from datetime import date
from research.hft_contract_discovery import find_nearest_future_symbol, nearest_expiry, option_strike_and_type

def test_nearest_expiry_is_data_driven():
    expiries = {date(2026, 8, 18), date(2026, 8, 25), date(2026, 9, 1)}
    assert nearest_expiry(date(2026, 8, 21), expiries) == date(2026, 8, 25)

def test_weekly_numeric_symbol_parsing():
    assert option_strike_and_type("NSE:NIFTY2692223250CE", date(2026, 9, 22)) == (23250, "CE")

def test_monthly_symbol_parsing():
    assert option_strike_and_type("NSE:NIFTY26AUG24250PE", date(2026, 8, 27)) == (24250, "PE")

def test_future_selection():
    response = {"data": {"contracts": {"futures": ["NSE:NIFTY26AUGFUT", "NSE:NIFTY26SEPFUT"], "options": []}}}
    assert find_nearest_future_symbol(response) == "NSE:NIFTY26AUGFUT"

def test_epoch_expiry_parsing():
    from datetime import datetime, timezone
    from research.hft_contract_discovery import extract_expiry_dates
    epoch = int(datetime(2026, 8, 25, tzinfo=timezone.utc).timestamp())
    response = {"data": {"expiry_dates": {"options": [epoch], "futures": []}}}
    assert extract_expiry_dates(response, "options") == {date(2026, 8, 25)}

def test_nested_epoch_expiry_parsing():
    from datetime import datetime, timezone
    from research.hft_contract_discovery import extract_expiry_dates
    epoch = int(datetime(2026, 8, 25, tzinfo=timezone.utc).timestamp())
    response = {"data": {"expiry_dates": {"options": [{"expiryDateEpoch": epoch}], "futures": []}}}
    assert extract_expiry_dates(response, "options") == {date(2026, 8, 25)}
