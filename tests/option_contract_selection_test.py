"""
Kunal Quant — Option Contract Selection V1

Purpose:
    Convert an underlying NIFTY price + LONG/SHORT signal into
    an ATM NIFTY option contract specification.

IMPORTANT:
    This is a selection layer only.

    It does NOT:
        - download data
        - execute trades
        - calculate P&L
        - modify KTMI
        - modify the backtest engine

LONG  -> ATM CE
SHORT -> ATM PE
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import Enum


# =====================================================================
# ENUMS
# =====================================================================


class OptionType(str, Enum):
    CE = "CE"
    PE = "PE"


class SignalDirection(str, Enum):
    LONG = "LONG"
    SHORT = "SHORT"


# =====================================================================
# CONFIG
# =====================================================================


@dataclass(frozen=True)
class OptionSelectionConfig:
    """
    Configuration for ATM option selection.
    """

    strike_step: int = 50

    # ATM definition:
    # nearest strike to underlying price.
    atm_rounding: str = "NEAREST"

    # LONG underlying signal -> CE
    # SHORT underlying signal -> PE
    long_option_type: OptionType = OptionType.CE
    short_option_type: OptionType = OptionType.PE


DEFAULT_OPTION_SELECTION_CONFIG = (
    OptionSelectionConfig()
)


# =====================================================================
# RESULT
# =====================================================================


@dataclass(frozen=True)
class OptionContract:
    """
    Selected option contract.

    symbol is intentionally optional because the exact broker
    symbol format depends on the broker's instrument master.
    """

    underlying: str

    expiry: date

    strike: int

    option_type: OptionType

    symbol: str | None = None

    @property
    def option_type_name(self) -> str:
        return self.option_type.value


# =====================================================================
# STRIKE CALCULATION
# =====================================================================


def calculate_atm_strike(
    underlying_price: float,
    strike_step: int = 50,
) -> int:
    """
    Select nearest NIFTY strike.

    Examples:

        23424 -> 23400
        23425 -> 23400
        23426 -> 23450

    Uses standard nearest-strike selection.
    """

    if underlying_price <= 0:
        raise ValueError(
            "Underlying price must be positive."
        )

    if strike_step <= 0:
        raise ValueError(
            "Strike step must be positive."
        )

    return int(
        round(
            underlying_price / strike_step
        )
        * strike_step
    )


# =====================================================================
# OPTION TYPE
# =====================================================================


def option_type_for_direction(
    direction: SignalDirection,
    config: OptionSelectionConfig = (
        DEFAULT_OPTION_SELECTION_CONFIG
    ),
) -> OptionType:
    """
    Convert underlying direction into option type.

    LONG  -> CE
    SHORT -> PE
    """

    if direction == SignalDirection.LONG:
        return config.long_option_type

    if direction == SignalDirection.SHORT:
        return config.short_option_type

    raise ValueError(
        f"Unsupported direction: {direction}"
    )


# =====================================================================
# CONTRACT SELECTION
# =====================================================================


def select_atm_option(
    *,
    underlying: str,
    underlying_price: float,
    expiry: date,
    direction: SignalDirection,
    config: OptionSelectionConfig = (
        DEFAULT_OPTION_SELECTION_CONFIG
    ),
) -> OptionContract:
    """
    Select the ATM option corresponding to the signal.
    """

    strike = calculate_atm_strike(
        underlying_price=underlying_price,
        strike_step=config.strike_step,
    )

    option_type = option_type_for_direction(
        direction=direction,
        config=config,
    )

    return OptionContract(
        underlying=underlying,
        expiry=expiry,
        strike=strike,
        option_type=option_type,
    )


# =====================================================================
# TESTS
# =====================================================================


def test_atm_strike_below_midpoint():

    strike = calculate_atm_strike(
        underlying_price=23424,
        strike_step=50,
    )

    assert strike == 23400

    print(
        "PASS | 23424 -> ATM 23400"
    )


def test_atm_strike_above_midpoint():

    strike = calculate_atm_strike(
        underlying_price=23426,
        strike_step=50,
    )

    assert strike == 23450

    print(
        "PASS | 23426 -> ATM 23450"
    )


def test_exact_strike():

    strike = calculate_atm_strike(
        underlying_price=23500,
        strike_step=50,
    )

    assert strike == 23500

    print(
        "PASS | 23500 -> ATM 23500"
    )


def test_long_selects_ce():

    contract = select_atm_option(
        underlying="NIFTY",
        underlying_price=23446.75,
        expiry=date(2026, 9, 24),
        direction=SignalDirection.LONG,
    )

    assert contract.strike == 23450
    assert contract.option_type == OptionType.CE

    print(
        "PASS | LONG -> ATM CE"
    )


def test_short_selects_pe():

    contract = select_atm_option(
        underlying="NIFTY",
        underlying_price=23446.75,
        expiry=date(2026, 9, 24),
        direction=SignalDirection.SHORT,
    )

    assert contract.strike == 23450
    assert contract.option_type == OptionType.PE

    print(
        "PASS | SHORT -> ATM PE"
    )


def test_contract_contains_expiry():

    expiry = date(2026, 9, 24)

    contract = select_atm_option(
        underlying="NIFTY",
        underlying_price=23446.75,
        expiry=expiry,
        direction=SignalDirection.LONG,
    )

    assert contract.expiry == expiry

    print(
        "PASS | Expiry preserved"
    )


def test_invalid_price():

    try:

        calculate_atm_strike(
            underlying_price=0,
            strike_step=50,
        )

    except ValueError:

        print(
            "PASS | Invalid price rejected"
        )

        return

    raise AssertionError(
        "Invalid price was not rejected."
    )


# =====================================================================
# MAIN
# =====================================================================


def main():

    print()
    print("=" * 78)
    print(
        "KUNAL QUANT — OPTION CONTRACT SELECTION V1 TEST"
    )
    print("=" * 78)

    test_atm_strike_below_midpoint()
    test_atm_strike_above_midpoint()
    test_exact_strike()

    test_long_selects_ce()
    test_short_selects_pe()

    test_contract_contains_expiry()

    test_invalid_price()

    print()
    print("=" * 78)
    print(
        "ALL OPTION CONTRACT SELECTION TESTS PASSED"
    )
    print("=" * 78)


if __name__ == "__main__":
    main()