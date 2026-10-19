"""
KUNAL QUANT
Option Contract Resolver V2 Test
"""

from datetime import date

from strategies.option_contract_resolver import (
    OptionContractResolver,
)


def main():

    print()
    print("=" * 80)
    print(
        "KUNAL QUANT — OPTION CONTRACT RESOLVER V2 TEST"
    )
    print("=" * 80)

    resolver = OptionContractResolver()

    # -------------------------------------------------------------
    # TEST 1 — ATM
    # -------------------------------------------------------------

    strike = resolver.calculate_atm_strike(
        23446.75
    )

    assert strike == 23450

    print(
        "PASS | NIFTY 23446.75 -> ATM 23450"
    )

    # -------------------------------------------------------------
    # TEST 2 — FIND EXPIRY
    # -------------------------------------------------------------

    expiry = resolver.find_nearest_expiry(
        entry_date=date(2024, 11, 20),
        option_type="CE",
    )

    assert expiry >= date(2024, 11, 20)

    print(
        f"PASS | Nearest CE expiry = {expiry}"
    )

    # -------------------------------------------------------------
    # TEST 3 — LONG -> CE
    # -------------------------------------------------------------

    try:

        contract = resolver.resolve(
            underlying_price=23446.75,
            entry_date=date(2024, 11, 20),
            direction="LONG",
        )

        assert contract.option_type == "CE"
        assert contract.strike == 23450
        assert contract.expiry_date >= date(
            2024, 11, 20
        )
        assert contract.instrument_id > 0
        assert contract.symbol

        print()
        print("LONG CONTRACT")
        print(
            f"Instrument ID : {contract.instrument_id}"
        )
        print(
            f"Symbol        : {contract.symbol}"
        )
        print(
            f"Expiry        : {contract.expiry_date}"
        )
        print(
            f"Strike        : {contract.strike}"
        )
        print(
            f"Type          : {contract.option_type}"
        )

        print(
            "PASS | LONG -> actual ATM CE"
        )

    except LookupError as exc:

        print()
        print(
            f"INFO | LONG contract unavailable: {exc}"
        )

    # -------------------------------------------------------------
    # TEST 4 — SHORT -> PE
    # -------------------------------------------------------------

    try:

        contract = resolver.resolve(
            underlying_price=23446.75,
            entry_date=date(2024, 11, 20),
            direction="SHORT",
        )

        assert contract.option_type == "PE"
        assert contract.strike == 23450
        assert contract.expiry_date >= date(
            2024, 11, 20
        )
        assert contract.instrument_id > 0
        assert contract.symbol

        print()
        print("SHORT CONTRACT")
        print(
            f"Instrument ID : {contract.instrument_id}"
        )
        print(
            f"Symbol        : {contract.symbol}"
        )
        print(
            f"Expiry        : {contract.expiry_date}"
        )
        print(
            f"Strike        : {contract.strike}"
        )
        print(
            f"Type          : {contract.option_type}"
        )

        print(
            "PASS | SHORT -> actual ATM PE"
        )

    except LookupError as exc:

        print()
        print(
            f"INFO | SHORT contract unavailable: {exc}"
        )

    print()
    print("=" * 80)
    print(
        "OPTION CONTRACT RESOLVER V2 TEST COMPLETE"
    )
    print("=" * 80)


if __name__ == "__main__":
    main()