from risk.risk_engine import (
    RiskMethod,
    RiskRequest,
    calculate_position_size,
)


def main() -> None:

    print("=" * 78)
    print("KUNAL QUANT — RISK ENGINE TEST")
    print("=" * 78)

    passed = 0

    # ---------------------------------------------------------
    # Test 1 — Fixed risk, single-unit instrument
    # ---------------------------------------------------------

    request = RiskRequest(
        capital=100000.0,
        entry_price=100.0,
        stop_loss_price=95.0,
        lot_size=1,
        risk_method=RiskMethod.FIXED_AMOUNT,
        fixed_risk_amount=2500.0,
    )

    result = calculate_position_size(request)

    assert result.risk_budget == 2500.0
    assert result.risk_per_unit == 5.0
    assert result.quantity == 500
    assert result.lots == 500
    assert result.actual_risk == 2500.0

    print(
        "PASS | Fixed ₹2,500 risk / ₹5 stop distance"
    )

    passed += 1

    # ---------------------------------------------------------
    # Test 2 — Lot-size rounding
    # ---------------------------------------------------------

    request = RiskRequest(
        capital=100000.0,
        entry_price=100.0,
        stop_loss_price=95.0,
        lot_size=65,
        risk_method=RiskMethod.FIXED_AMOUNT,
        fixed_risk_amount=2500.0,
    )

    result = calculate_position_size(request)

    assert result.theoretical_quantity == 500.0
    assert result.lots == 7
    assert result.quantity == 455
    assert result.actual_risk == 2275.0
    assert result.unused_risk == 225.0

    print(
        "PASS | Quantity rounded down to complete 65-unit lots"
    )

    passed += 1

    # ---------------------------------------------------------
    # Test 3 — Percentage risk
    # ---------------------------------------------------------

    request = RiskRequest(
        capital=200000.0,
        entry_price=200.0,
        stop_loss_price=190.0,
        lot_size=1,
        risk_method=RiskMethod.PERCENT_OF_CAPITAL,
        risk_percent=1.0,
    )

    result = calculate_position_size(request)

    assert result.risk_budget == 2000.0
    assert result.risk_per_unit == 10.0
    assert result.quantity == 200
    assert result.actual_risk == 2000.0

    print(
        "PASS | 1% risk on ₹2,00,000 capital"
    )

    passed += 1

    # ---------------------------------------------------------
    # Test 4 — Option-style lot sizing
    # ---------------------------------------------------------

    request = RiskRequest(
        capital=200000.0,
        entry_price=150.0,
        stop_loss_price=125.0,
        lot_size=65,
        risk_method=RiskMethod.FIXED_AMOUNT,
        fixed_risk_amount=2500.0,
    )

    result = calculate_position_size(request)

    assert result.risk_per_unit == 25.0
    assert result.theoretical_quantity == 100.0
    assert result.lots == 1
    assert result.quantity == 65
    assert result.actual_risk == 1625.0

    print(
        "PASS | NIFTY-style option lot sizing"
    )

    passed += 1

    # ---------------------------------------------------------
    # Test 5 — Risk never exceeds budget
    # ---------------------------------------------------------

    assert result.actual_risk <= result.risk_budget

    print(
        "PASS | Actual risk never exceeds risk budget"
    )

    passed += 1

    # ---------------------------------------------------------
    # Test 6 — Zero tradable quantity
    # ---------------------------------------------------------

    request = RiskRequest(
        capital=100000.0,
        entry_price=100.0,
        stop_loss_price=99.0,
        lot_size=100,
        risk_method=RiskMethod.FIXED_AMOUNT,
        fixed_risk_amount=50.0,
    )

    result = calculate_position_size(request)

    assert result.quantity == 0
    assert result.lots == 0
    assert result.actual_risk == 0.0
    assert not result.has_position

    print(
        "PASS | Insufficient risk budget returns zero quantity"
    )

    passed += 1

    # ---------------------------------------------------------
    # Test 7 — Invalid equal prices
    # ---------------------------------------------------------

    try:

        RiskRequest(
            capital=100000.0,
            entry_price=100.0,
            stop_loss_price=100.0,
            lot_size=1,
            fixed_risk_amount=2500.0,
        )

        raise AssertionError(
            "Equal entry/SL prices should fail."
        )

    except ValueError:

        pass

    print(
        "PASS | Equal entry/SL prices rejected"
    )

    passed += 1

    # ---------------------------------------------------------
    # Test 8 — Invalid lot size
    # ---------------------------------------------------------

    try:

        RiskRequest(
            capital=100000.0,
            entry_price=100.0,
            stop_loss_price=95.0,
            lot_size=0,
            fixed_risk_amount=2500.0,
        )

        raise AssertionError(
            "Invalid lot size should fail."
        )

    except ValueError:

        pass

    print(
        "PASS | Invalid lot size rejected"
    )

    passed += 1

    print()
    print(f"Total : 8")
    print(f"Passed: {passed}")
    print(f"Failed: {8 - passed}")

    assert passed == 8

    print()
    print("ALL RISK ENGINE TESTS PASSED")


if __name__ == "__main__":
    main()