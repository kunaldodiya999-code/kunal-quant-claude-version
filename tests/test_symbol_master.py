from instruments.symbol_master import (
    download_symbol_master,
    normalize_master,
    find_nifty_options,
    find_nifty_futures,
    get_instrument,
)


def main():

    print("=" * 70)
    print("KUNAL QUANT - SYMBOL MASTER TEST")
    print("=" * 70)

    raw = download_symbol_master(
        force_refresh=True
    )

    print(
        "\nRaw records:",
        len(raw)
    )

    instruments = normalize_master(
        raw
    )

    print(
        "Normalized records:",
        len(instruments)
    )

    nifty_options = find_nifty_options(
        instruments
    )

    nifty_futures = find_nifty_futures(
        instruments
    )

    print(
        "\nNIFTY options:",
        len(nifty_options)
    )

    print(
        "NIFTY futures:",
        len(nifty_futures)
    )

    # --------------------------------------------------------
    # Validate known historical contracts
    # --------------------------------------------------------

    symbols = [
        "NSE:NIFTY24NOV22500CE",
        "NSE:NIFTY24NOV22500PE",
        "NSE:NIFTY24NOVFUT",
    ]

    print("\nKnown contracts:")

    for symbol in symbols:

        result = get_instrument(
            instruments,
            symbol
        )

        if result:

            print(
                f"[OK] {symbol}"
            )

            print(
                "     Expiry:",
                result.get("expiry_date")
            )

            print(
                "     Strike:",
                result.get("strike")
            )

            print(
                "     Option:",
                result.get("option_type")
            )

            print(
                "     Lot:",
                result.get("lot_size")
            )

        else:

            print(
                f"[FAIL] {symbol}"
            )

    print("\n" + "=" * 70)
    print("SYMBOL MASTER TEST COMPLETE")
    print("=" * 70)


if __name__ == "__main__":
    main()