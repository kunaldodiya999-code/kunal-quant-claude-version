from scripts.audit_nifty_option_chain_completeness import summarize_snapshot


def test_matched_ce_pe_strikes_with_oi_are_candidate():
    contracts = {
        float(strike): {
            "CE": (100.0, 1200),
            "PE": (95.0, 1400),
        }
        for strike in (23000, 23050, 23100, 23150, 23200)
    }

    result = summarize_snapshot(
        contracts=contracts,
        spot=23100.0,
        max_distance=200.0,
        min_paired_oi_strikes=5,
    )

    assert result["ce_strikes_in_band"] == 5
    assert result["pe_strikes_in_band"] == 5
    assert result["paired_strikes_in_band"] == 5
    assert result["paired_oi_strikes_in_band"] == 5
    assert result["candidate_snapshot"] == "YES"


def test_missing_oi_does_not_count_as_oi_covered_pair():
    contracts = {
        23100.0: {"CE": (100.0, 1200), "PE": (95.0, None)},
        23150.0: {"CE": (90.0, 1100), "PE": (85.0, 1300)},
    }

    result = summarize_snapshot(
        contracts=contracts,
        spot=23100.0,
        max_distance=200.0,
        min_paired_oi_strikes=2,
    )

    assert result["paired_strikes_in_band"] == 2
    assert result["paired_oi_strikes_in_band"] == 1
    assert result["candidate_snapshot"] == "NO"


def test_strikes_outside_spot_band_are_excluded():
    contracts = {
        22000.0: {"CE": (100.0, 100), "PE": (100.0, 100)},
        23100.0: {"CE": (100.0, 100), "PE": (100.0, 100)},
        24100.0: {"CE": (100.0, 100), "PE": (100.0, 100)},
    }

    result = summarize_snapshot(
        contracts=contracts,
        spot=23100.0,
        max_distance=500.0,
        min_paired_oi_strikes=1,
    )

    assert result["paired_oi_strikes_in_band"] == 1
    assert result["candidate_snapshot"] == "YES"


def test_missing_synchronized_spot_does_not_claim_band_coverage():
    contracts = {
        23100.0: {"CE": (100.0, 100), "PE": (100.0, 100)},
    }

    result = summarize_snapshot(
        contracts=contracts,
        spot=None,
        max_distance=1000.0,
        min_paired_oi_strikes=1,
    )

    assert result["spot"] is None
    assert result["ce_strikes_in_band"] == 0
    assert result["pe_strikes_in_band"] == 0
    assert result["paired_oi_strikes_in_band"] == 0
    assert result["candidate_snapshot"] == "NO"
