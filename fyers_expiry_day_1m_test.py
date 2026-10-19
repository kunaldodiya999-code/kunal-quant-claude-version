import os
import json
from datetime import datetime
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from fyers_apiv3 import fyersModel


# ============================================================
# KUNAL QUANT
# FYERS EXPIRED OPTION - EXPIRY DAY 1-MINUTE TEST
# ============================================================

load_dotenv()

CLIENT_ID = os.getenv("FYERS_CLIENT_ID")

with open("fyers_access_token.txt", "r", encoding="utf-8") as file:
    ACCESS_TOKEN = file.read().strip()

if not CLIENT_ID:
    raise RuntimeError("FYERS_CLIENT_ID missing from .env")

if not ACCESS_TOKEN:
    raise RuntimeError("FYERS access token missing")


fyers = fyersModel.FyersModel(
    client_id=CLIENT_ID,
    token=ACCESS_TOKEN,
    is_async=False,
    log_path=""
)


# ------------------------------------------------------------
# TEST SETTINGS
# ------------------------------------------------------------

TEST_DATE = "2024-11-28"

SYMBOLS = [
    "NSE:NIFTY24NOV22500CE",
    "NSE:NIFTY24NOV22500PE",
]

IST = ZoneInfo("Asia/Kolkata")


# ------------------------------------------------------------
# FUNCTION
# ------------------------------------------------------------

def test_symbol(symbol):

    print("\n" + "=" * 75)
    print("TESTING:", symbol)
    print("=" * 75)

    request = {
        "symbol": symbol,
        "resolution": "1",
        "date_format": "1",
        "range_from": TEST_DATE,
        "range_to": TEST_DATE,
        "include_greeks": "1",
        "include_oi": "1"
    }

    response = fyers.fno_historical_data(request)

    print("\nStatus :", response.get("s"))
    print("Symbol :", response.get("symbol"))
    print("Resolution:", response.get("resolution"))
    print("Columns:", response.get("columns"))

    candles = response.get("candles", [])

    print("Candles received:", len(candles))

    if not candles:
        print("\nNo candles returned.")
        print(response)
        return response

    columns = response.get("columns", [])

    # --------------------------------------------------------
    # Create readable records
    # --------------------------------------------------------

    records = []

    for candle in candles:

        row = dict(zip(columns, candle))

        timestamp = row.get("timestamp")

        if timestamp is not None:
            dt_ist = datetime.fromtimestamp(
                int(timestamp),
                tz=IST
            )

            row["datetime_ist"] = dt_ist.strftime(
                "%Y-%m-%d %H:%M:%S"
            )

        records.append(row)

    # --------------------------------------------------------
    # Time coverage
    # --------------------------------------------------------

    print("\nFirst candle:")
    print(records[0])

    print("\nLast candle:")
    print(records[-1])

    print("\nTime coverage:")
    print(
        records[0].get("datetime_ist"),
        "→",
        records[-1].get("datetime_ist")
    )

    # --------------------------------------------------------
    # Non-null analysis
    # --------------------------------------------------------

    fields_to_check = [
        "open_interest",
        "iv",
        "delta",
        "gamma",
        "theta",
        "vega"
    ]

    print("\nNon-null field counts:")

    for field in fields_to_check:

        count = sum(
            1
            for row in records
            if row.get(field) is not None
        )

        print(
            f"{field:16s}: "
            f"{count}/{len(records)}"
        )

    # --------------------------------------------------------
    # Check final trading window
    # --------------------------------------------------------

    final_records = [
        r for r in records
        if r.get("datetime_ist", "") >=
           f"{TEST_DATE} 15:00:00"
    ]

    print(
        "\nCandles from 15:00 onward:",
        len(final_records)
    )

    if final_records:
        print("\nLast 10 expiry-day candles:")

        for row in final_records[-10:]:
            print(row)

    return response


# ------------------------------------------------------------
# RUN CE + PE
# ------------------------------------------------------------

results = {}

for symbol in SYMBOLS:

    results[symbol] = test_symbol(symbol)


# ------------------------------------------------------------
# SAVE
# ------------------------------------------------------------

output_file = "fyers_nifty_expiry_day_1m_test.json"

with open(
    output_file,
    "w",
    encoding="utf-8"
) as file:

    json.dump(
        results,
        file,
        indent=2
    )


print("\n" + "=" * 75)
print("EXPIRY DAY 1-MINUTE TEST COMPLETE")
print("=" * 75)

print("\nSaved:")
print(output_file)
