from datetime import date

from scripts.build_opening_breakout_v2_option_manifest import build_manifest


def _required(d, strike, option_type, instrument_id, symbol):
    from types import SimpleNamespace
    return SimpleNamespace(
        signal_date=d,
        expiry_date=date(2026, 9, 22),
        strike=strike,
        option_type=option_type,
        instrument_id=instrument_id,
        symbol=symbol,
    )


def test_manifest_groups_contract_days_and_separates_complete():
    required = [
        _required(date(2026, 9, 16), 23200, "PE", 5881, "NSE:NIFTY2692223200PE"),
        _required(date(2026, 9, 17), 23200, "PE", 5881, "NSE:NIFTY2692223200PE"),
    ]

    class FakePath:
        pass

    # The manifest builder's audit dependency is intentionally exercised
    # through a patched module-level function so this test stays database-free.
    import scripts.build_opening_breakout_v2_option_manifest as module

    module.audit_coverage = lambda database_path, required: [
        {
            "signal_date": date(2026, 9, 16),
            "expiry_date": date(2026, 9, 22),
            "strike": 23200,
            "option_type": "PE",
            "instrument_id": 5881,
            "symbol": "NSE:NIFTY2692223200PE",
            "status": "COMPLETE",
            "candles": 385,
        },
        {
            "signal_date": date(2026, 9, 17),
            "expiry_date": date(2026, 9, 22),
            "strike": 23200,
            "option_type": "PE",
            "instrument_id": 5881,
            "symbol": "NSE:NIFTY2692223200PE",
            "status": "EMPTY",
            "candles": 0,
        },
    ]

    manifest = build_manifest(FakePath(), required)

    assert manifest["summary"]["unique_contract_days"] == 2
    assert manifest["summary"]["complete"] == 1
    assert manifest["summary"]["empty"] == 1
    assert manifest["summary"]["missing_contract_days"] == 1
    assert manifest["summary"]["unique_contracts"] == 1

    contract = manifest["contracts"][0]
    assert contract["complete_dates"] == ["2026-09-16"]
    assert contract["missing_dates"] == ["2026-09-17"]


def test_manifest_marks_unregistered_days():
    import scripts.build_opening_breakout_v2_option_manifest as module

    module.audit_coverage = lambda database_path, required: [
        {
            "signal_date": date(2026, 9, 18),
            "expiry_date": date(2026, 9, 22),
            "strike": 23350,
            "option_type": "CE",
            "instrument_id": None,
            "symbol": None,
            "status": "UNREGISTERED",
            "candles": 0,
        }
    ]

    manifest = build_manifest(
        object(),
        [_required(date(2026, 9, 18), 23350, "CE", None, None)],
    )

    contract = manifest["contracts"][0]
    assert contract["missing_dates"] == ["2026-09-18"]
    assert contract["unregistered_dates"] == ["2026-09-18"]
