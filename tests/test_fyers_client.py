from api.fyers_client import FyersClient


# ============================================================
# KUNAL QUANT
# FYERS CLIENT INTEGRATION TEST
# ============================================================


def main():

    print("=" * 70)
    print("KUNAL QUANT - FYERS CLIENT INTEGRATION TEST")
    print("=" * 70)

    client = FyersClient()

    # --------------------------------------------------------
    # 1. PROFILE
    # --------------------------------------------------------

    print("\n[1] PROFILE")

    response = client.profile()

    print(
        "Status:",
        response.get("s")
    )

    # --------------------------------------------------------
    # 2. QUOTE
    # --------------------------------------------------------

    print("\n[2] QUOTE")

    response = client.quotes(
        "NSE:NIFTY50-INDEX"
    )

    print(
        "Status:",
        response.get("s")
    )

    # --------------------------------------------------------
    # 3. HISTORICAL INDEX
    # --------------------------------------------------------

    print("\n[3] HISTORICAL INDEX")

    response = client.history(
        symbol="NSE:NIFTY50-INDEX",
        resolution="1",
        range_from="2024-11-27",
        range_to="2024-11-27",
    )

    candles = response.get(
        "candles",
        []
    )

    print(
        "Status:",
        response.get("s")
    )

    print(
        "Candles:",
        len(candles)
    )

    # --------------------------------------------------------
    # 4. EXPIRED CONTRACTS
    # --------------------------------------------------------

    print("\n[4] EXPIRED CONTRACTS")

    response = client.expired_contracts(
        symbol="NSE:NIFTY50-INDEX",
        expiry_date="2024-11-28",
    )

    contracts = response.get(
        "data",
        {}
    ).get(
        "contracts",
        {}
    )

    print(
        "Status:",
        response.get("s")
    )

    print(
        "Futures:",
        len(
            contracts.get(
                "futures",
                []
            )
        )
    )

    print(
        "Options:",
        len(
            contracts.get(
                "options",
                []
            )
        )
    )

    # --------------------------------------------------------
    # 5. EXPIRED OPTION HISTORY
    # --------------------------------------------------------

    print("\n[5] EXPIRED OPTION HISTORY")

    response = client.expired_history(
        symbol="NSE:NIFTY24NOV22500CE",
        resolution="1",
        range_from="2024-11-27",
        range_to="2024-11-27",
        include_oi="1",
        include_greeks="1",
    )

    candles = response.get(
        "candles",
        []
    )

    print(
        "Status:",
        response.get("s")
    )

    print(
        "Candles:",
        len(candles)
    )

    # --------------------------------------------------------
    # 6. DEPTH
    # --------------------------------------------------------

    print("\n[6] MARKET DEPTH")

    response = client.depth(
        "NSE:NIFTY26SEPFUT"
    )

    print(
        "Status:",
        response.get("s")
    )

    depth_data = (
        response
        .get("d", {})
        .get("NSE:NIFTY26SEPFUT", {})
    )

    print(
        "Bid levels:",
        len(
            depth_data.get(
                "bids",
                []
            )
        )
    )

    print(
        "Ask levels:",
        len(
            depth_data.get(
                "ask",
                []
            )
        )
    )

    # --------------------------------------------------------
    # COMPLETE
    # --------------------------------------------------------

    print("\n" + "=" * 70)
    print("FYERS CLIENT INTEGRATION TEST COMPLETE")
    print("=" * 70)


if __name__ == "__main__":
    main()