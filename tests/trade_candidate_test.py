from portfolio.trade_candidate import (
    TradeCandidate,
    build_trade_plan,
)
from risk.risk_engine import RiskMethod
from strategies.direction_filter import Direction
from strategies.ktmi_strategy import (
    StrategyAction,
    StrategyReason,
    KTMIEntryDecision,
)


def make_long_decision() -> KTMIEntryDecision:
    return KTMIEntryDecision(
        action=StrategyAction.LONG,
        direction=Direction.LONG,
        reason=StrategyReason.LONG_SIGNAL,
        direction_filter=None,

        momentum_buy=True,
        long_buy=False,
        short_buy=False,

        momentum_sell=False,
        long_sell=False,
        short_sell=False,

        bullish_confluence=False,
        bearish_confluence=False,
    )


def main() -> None:

    print("=" * 78)
    print("KUNAL QUANT — TRADE CANDIDATE TEST")
    print("=" * 78)

    decision = make_long_decision()

    candidate = TradeCandidate(
        direction=Direction.LONG,
        entry_price=150.0,
        stop_loss_price=125.0,
        lot_size=65,
        strategy_id="KTMI_V1",
        config_version="1.0",
        timestamp=1732679100,
    )

    plan = build_trade_plan(
        candidate=candidate,
        strategy_decision=decision,
        risk_method=RiskMethod.FIXED_AMOUNT,
        fixed_risk_amount=2500.0,
        capital=200000.0,
    )

    assert plan.candidate == candidate
    assert plan.strategy_decision == decision

    assert plan.risk.risk_budget == 2500.0
    assert plan.risk.risk_per_unit == 25.0

    assert plan.quantity == 65
    assert plan.lots == 1
    assert plan.tradable

    print(
        "PASS | Strategy decision + candidate + risk sizing"
    )

    # Risk must never exceed budget.
    assert plan.risk.actual_risk <= 2500.0

    print(
        "PASS | Actual risk remains within budget"
    )

    # Direction mismatch must be rejected.
    wrong_candidate = TradeCandidate(
        direction=Direction.SHORT,
        entry_price=150.0,
        stop_loss_price=125.0,
        lot_size=65,
    )

    try:
        build_trade_plan(
            candidate=wrong_candidate,
            strategy_decision=decision,
            risk_method=RiskMethod.FIXED_AMOUNT,
            fixed_risk_amount=2500.0,
            capital=200000.0,
        )

        raise AssertionError(
            "Direction mismatch should fail."
        )

    except ValueError:
        pass

    print(
        "PASS | Direction mismatch rejected"
    )

    print()
    print("Total : 3")
    print("Passed: 3")
    print("Failed: 0")

    print()
    print("ALL TRADE CANDIDATE TESTS PASSED")


if __name__ == "__main__":
    main()