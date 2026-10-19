from instruments.symbol_master import (
    download_symbol_master,
    normalize_master,
    get_instrument,
)


def main():

    print("=" * 70)
    print("KUNAL QUANT - CURRENT NIFTY SYMBOL TEST")
    print("=" * 70)

    raw = download_symbol_master(
        force_refresh=False
    )

    instruments = normalize_master(
        raw
    )

    # Use a currently active contract.
    test_symbols = [
        "NSE:NIFTY26SEPFUT",
    ]

    for symbol in test_symbols:

        result = get_instrument(
            instruments,
            symbol
        )

        print("\nTesting:", symbol)

        if result:

            print("[OK] Current symbol found")

            print(
                "Expiry:",
                result.get("expiry_date")
            )

            print(
                "Lot:",
                result.get("lot_size")
            )

            print(
                "Tick:",
                result.get("tick_size")
            )

        else:

            print("[NOT FOUND]")

    print("\n" + "=" * 70)
    print("CURRENT SYMBOL TEST COMPLETE")
    print("=" * 70)


if __name__ == "__main__":
    main()