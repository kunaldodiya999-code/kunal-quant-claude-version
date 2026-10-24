from pathlib import Path

from scripts.acquire_opening_breakout_v2_options import build_acquisition_plan


def _manifest(*contracts):
    return {
        "schema_version": 1,
        "contracts": list(contracts),
    }


def _contract(
    expiry="2025-10-28",
    strike=25900,
    option_type="PE",
    symbol=None,
    missing_dates=None,
):
    return {
        "expiry_date": expiry,
        "strike": strike,
        "option_type": option_type,
        "instrument_id": None,
        "symbol": symbol,
        "required_dates": missing_dates if missing_dates is not None else ["2025-10-21"],
        "complete_dates": [],
        "missing_dates": missing_dates if missing_dates is not None else ["2025-10-21"],
        "unregistered_dates": ["2025-10-21"],
    }


def _discovery(*found):
    return {
        "results": [
            {
                "expiry_date": "2025-10-28",
                "found": list(found),
                "missing": [],
            }
        ]
    }


def test_plan_uses_exact_discovered_symbol_and_missing_dates():
    manifest = _manifest(_contract())
    discovery = _discovery(
        {
            "strike": 25900,
            "option_type": "PE",
            "symbol": "NSE:NIFTY25O2825900PE",
        }
    )

    plan = build_acquisition_plan(manifest, discovery)

    assert plan == [
        {
            "expiry_date": "2025-10-28",
            "strike": 25900.0,
            "option_type": "PE",
            "symbol": "NSE:NIFTY25O2825900PE",
            "required_dates": ["2025-10-21"],
        }
    ]


def test_plan_skips_contract_days_already_complete():
    contract = _contract(missing_dates=[])
    contract["required_dates"] = ["2025-10-21"]
    contract["complete_dates"] = ["2025-10-21"]
    manifest = _manifest(contract)

    assert build_acquisition_plan(manifest, {}) == []


def test_plan_prefers_manifest_symbol_when_already_registered():
    manifest = _manifest(
        _contract(
            symbol="NSE:NIFTY25O2825900PE",
        )
    )
    discovery = _discovery(
        {
            "strike": 25900,
            "option_type": "PE",
            "symbol": "NSE:DIFFERENT",
        }
    )

    plan = build_acquisition_plan(manifest, discovery)

    assert plan[0]["symbol"] == "NSE:NIFTY25O2825900PE"


def test_plan_fails_closed_when_discovery_symbol_is_missing():
    manifest = _manifest(_contract())

    try:
        build_acquisition_plan(manifest, {"results": []})
    except RuntimeError as exc:
        assert "No discovered FYERS symbol" in str(exc)
    else:
        raise AssertionError("Expected missing FYERS symbol to fail closed")


def test_plan_does_not_create_broad_date_ranges():
    manifest = _manifest(
        _contract(missing_dates=["2025-10-15", "2025-10-17"])
    )
    discovery = _discovery(
        {
            "strike": 25900,
            "option_type": "PE",
            "symbol": "NSE:NIFTY25O2825900PE",
        }
    )

    plan = build_acquisition_plan(manifest, discovery)

    assert plan[0]["required_dates"] == [
        "2025-10-15",
        "2025-10-17",
    ]


def test_acquisition_script_uses_existing_historical_downloader():
    source = Path(
        "scripts/acquire_opening_breakout_v2_options.py"
    ).read_text(encoding="utf-8")

    assert "HistoricalDownloader" in source
    assert 'mode="expired"' in source
    assert 'resolution="1"' in source
    assert "download_symbol(" in source
    assert "build_acquisition_plan" in source
