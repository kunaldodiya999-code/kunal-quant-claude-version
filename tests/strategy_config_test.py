from indicators.ktmi.config import (
    KTMIConfig,
    MomentumConfig,
)
from strategies.config import (
    DEFAULT_STRATEGY_CONFIG,
    ExitConfig,
    RiskConfig,
    StrategyConfig,
)
from strategies.direction_filter import DirectionMode
from strategies.ktmi_strategy import KTMIEntryConfig


def main() -> None:

    print("=" * 78)
    print("KUNAL QUANT — STRATEGY CONFIGURATION TEST")
    print("=" * 78)

    # ---------------------------------------------------------
    # Test 1 — Default configuration
    # ---------------------------------------------------------

    config = DEFAULT_STRATEGY_CONFIG

    assert config.strategy_id == "KTMI_V1"
    assert config.config_version == "1.0"

    print(
        "PASS | Default strategy configuration"
    )

    # ---------------------------------------------------------
    # Test 2 — Direction synchronization
    # ---------------------------------------------------------

    config = StrategyConfig(
        direction_mode=DirectionMode.LONG_ONLY,
        entry=KTMIEntryConfig(
            direction_mode=DirectionMode.BOTH,
        ),
    )

    assert config.direction_mode == DirectionMode.LONG_ONLY
    assert (
        config.entry.direction_mode
        == DirectionMode.LONG_ONLY
    )

    print(
        "PASS | Direction mode synchronized"
    )

    # ---------------------------------------------------------
    # Test 3 — Custom KTMI configuration
    # ---------------------------------------------------------

    ktmi = KTMIConfig(
        momentum=MomentumConfig(
            source="Close",
            speed_length=5,
            signal_length=9,
            smoothing="EMA",
            enabled=True,
            calculation="TRIX",
        ),
        long_momentum=MomentumConfig(
            source="Close",
            speed_length=5,
            signal_length=9,
            smoothing="EMA",
            enabled=True,
            calculation="TRIX",
        ),
        short_momentum=MomentumConfig(
            source="Low",
            speed_length=5,
            signal_length=9,
            smoothing="EMA",
            enabled=True,
            calculation="TRIX",
        ),
    )

    config = StrategyConfig(
        strategy_id="KTMI_TEST",
        config_version="TEST_001",
        ktmi=ktmi,
        direction_mode=DirectionMode.SHORT_ONLY,
    )

    assert config.strategy_id == "KTMI_TEST"
    assert config.config_version == "TEST_001"
    assert config.ktmi == ktmi
    assert (
        config.direction_mode
        == DirectionMode.SHORT_ONLY
    )

    print(
        "PASS | Custom KTMI strategy configuration"
    )

    # ---------------------------------------------------------
    # Test 4 — Risk placeholder
    # ---------------------------------------------------------

    risk = RiskConfig(
        enabled=False,
        max_daily_loss=5000.0,
        max_trade_loss=2500.0,
        risk_per_trade_percent=1.0,
    )

    config = StrategyConfig(
        risk=risk,
    )

    assert config.risk == risk
    assert config.risk.enabled is False
    assert config.risk.max_daily_loss == 5000.0
    assert config.risk.max_trade_loss == 2500.0

    print(
        "PASS | Risk configuration stored without activation"
    )

    # ---------------------------------------------------------
    # Test 5 — Exit placeholder
    # ---------------------------------------------------------

    exit_config = ExitConfig(
        enabled=False,
        stop_loss_enabled=True,
        target_enabled=True,
        trailing_stop_enabled=False,
        stop_loss_value=2500.0,
        target_value=5000.0,
    )

    config = StrategyConfig(
        exit=exit_config,
    )

    assert config.exit == exit_config
    assert config.exit.enabled is False
    assert config.exit.stop_loss_enabled is True
    assert config.exit.target_enabled is True

    print(
        "PASS | Exit configuration stored without activation"
    )

    # ---------------------------------------------------------
    # Test 6 — Configuration immutability
    # ---------------------------------------------------------

    config = DEFAULT_STRATEGY_CONFIG

    try:
        config.strategy_id = "CHANGED"
        raise AssertionError(
            "StrategyConfig should be immutable."
        )

    except AttributeError:
        pass

    print(
        "PASS | Strategy configuration is immutable"
    )

    # ---------------------------------------------------------
    # Test 7 — Reproducibility
    # ---------------------------------------------------------

    config_a = StrategyConfig(
        strategy_id="KTMI_TEST",
        config_version="TEST_001",
        direction_mode=DirectionMode.LONG_ONLY,
    )

    config_b = StrategyConfig(
        strategy_id="KTMI_TEST",
        config_version="TEST_001",
        direction_mode=DirectionMode.LONG_ONLY,
    )

    assert config_a == config_b

    print(
        "PASS | Identical configurations are reproducible"
    )

    print()
    print("Total : 7")
    print("Passed: 7")
    print("Failed: 0")

    print()
    print("ALL STRATEGY CONFIGURATION TESTS PASSED")


if __name__ == "__main__":
    main()
