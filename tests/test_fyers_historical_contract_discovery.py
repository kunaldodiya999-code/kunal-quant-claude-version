from datetime import date

from backtest.fyers_historical_contract_discovery import (
    FyersHistoricalContractDiscovery,
    extract_option_contracts,
    filter_exact_option,
)


def response(options):
    return {"s": "ok", "data": {"contracts": {"options": options}}}


def test_extracts_documented_option_contracts():
    contracts = extract_option_contracts(
        response([
            {"symbol": "NSE:NIFTY24JAN21600CE", "strike": 21600, "option_type": "CE"},
            {"symbol": "NSE:NIFTY24JAN21600PE", "strike": 21600, "option_type": "PE"},
        ])
    )
    assert len(contracts) == 2
    assert contracts[0]["symbol"] == "NSE:NIFTY24JAN21600CE"


def test_filters_exact_strike_and_type():
    contracts = extract_option_contracts(
        response([
            {"symbol": "CE", "strike": 21600, "option_type": "CE"},
            {"symbol": "PE", "strike": 21600, "option_type": "PE"},
            {"symbol": "CE2", "strike": 21650, "option_type": "CE"},
        ])
    )
    matches = filter_exact_option(contracts, strike=21600, option_type="CE")
    assert [item["symbol"] for item in matches] == ["CE"]


def test_parser_accepts_flat_options_fallback():
    contracts = extract_option_contracts(
        {"data": {"options": ["NSE:NIFTY24JAN21600CE"]}}
    )
    assert contracts == [{"symbol": "NSE:NIFTY24JAN21600CE", "strike": 21600.0, "option_type": "CE"}]


def test_discovery_uses_historical_expiry():
    class FakeClient:
        def __init__(self):
            self.calls = []

        def expired_contracts(self, symbol, expiry_date):
            self.calls.append((symbol, expiry_date))
            return response([
                {"symbol": "NSE:NIFTY24JAN21600CE", "strike": 21600, "option_type": "CE"}
            ])

    client = FakeClient()
    discovery = FyersHistoricalContractDiscovery(client)
    matches = discovery.discover_exact(date(2024, 1, 4), 21600, "CE")

    assert len(matches) == 1
    assert client.calls == [("NSE:NIFTY50-INDEX", "2024-01-04")]


def test_symbol_only_contract_infers_strike_and_type():
    contracts = extract_option_contracts(
        response(["NSE:NIFTY24JAN21600CE", "NSE:NIFTY24JAN21600PE"])
    )
    assert contracts[0]["strike"] == 21600.0
    assert contracts[0]["option_type"] == "CE"
    assert contracts[1]["option_type"] == "PE"

from backtest.fyers_historical_contract_discovery import _contract_strike

def test_fyers_expiry_encoded_symbol_parses_strike():
    contract = {"symbol": "NSE:NIFTY2410416800CE"}
    assert _contract_strike(contract, date(2024, 1, 4)) == 16800.0


def test_discovery_script_source_contains_resumable_rate_limit_controls():
    source = open("scripts/discover_opening_breakout_v2_fyers_contracts.py", encoding="utf-8").read()
    assert "--max-retries" in source
    assert "--backoff-seconds" in source
    assert "429" in source
    assert "resumable" in source


def test_discovery_script_source_contains_targeted_expiry_debug_controls():
    source = open("scripts/discover_opening_breakout_v2_fyers_contracts.py", encoding="utf-8").read()
    assert "--start-expiry" in source
    assert "Requested tuples:" in source
    assert "Parsed strike range" in source
    assert "+/-500" in source


def test_fyers_oct_weekly_symbol_parses_strike():
    contract = {"symbol": "NSE:NIFTY24O1019550CE"}
    assert _contract_strike(contract, date(2024, 10, 10)) == 19550.0


def test_discovery_script_source_supports_refreshing_checkpointed_expiries():
    source = open("scripts/discover_opening_breakout_v2_fyers_contracts.py", encoding="utf-8").read()
    assert "--refresh-expiry" in source
    assert "and not args.refresh_expiry" in source


def test_discovery_script_preserves_prior_checkpoints_for_targeted_runs():
    source = open("scripts/discover_opening_breakout_v2_fyers_contracts.py", encoding="utf-8").read()
    assert "results_by_expiry = dict(existing)" in source
    assert "results_by_expiry[expiry_text]" in source
    assert 'sorted(results_by_expiry.values(), key=lambda item: item["expiry_date"])' in source
