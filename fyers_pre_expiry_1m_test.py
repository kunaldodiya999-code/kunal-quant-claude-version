import os
import json
from datetime import datetime
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from fyers_apiv3 import fyersModel


# ============================================================
# KUNAL QUANT
# FYERS PRE-EXPIRY 1-MINUTE OPTIONS TEST
#
# Purpose:
#   Test historical 1-minute CE/PE data on the trading day
#   immediately before the NIFTY expiry.
#
# Test Date:
#   27-Nov-2024
#
# Contracts:
#   NSE:NIFTY24NOV22500CE
#   NSE:NIFTY24NOV22500PE
#
# Checks:
#   - Historical data availability
#   - 1-minute candle count
#   - First/last timestamp
#   - OHLC
#   - Volume
#   - Open Interest
#   - IV / Greeks population
#   - Missing minute gaps
# ============================================================


# ------------------------------------------------------------
# LOAD ENVIRONMENT
# ------------------------------------------------------------

load_dotenv()

CLIENT_ID = os.getenv("FYERS_CLIENT_ID")

try:
    with open(
        "fyers_access_token.txt",
        "r",
        encoding="utf-8"
    ) as file:
        ACCESS_TOKEN = file.read().strip()
except FileNotFoundError:
    raise RuntimeError(
        "fyers_access_token.txt not found. "
        "Run fyers_auth.py first."
    )


if not CLIENT_ID:
    raise RuntimeError(
        "FYERS_CLIENT_ID is missing from .env"
    )

if not ACCESS_TOKEN:
    raise RuntimeError(
        "FYERS access token is empty."
    )


# ------------------------------------------------------------
# FYERS CLIENT
# ------------------------------------------------------------

fyers = fyersModel.FyersModel(
    client_id=CLIENT_ID,
    token=ACCESS_TOKEN,
    is_async=False,
    log_path=""
)


# ------------------------------------------------------------
# TEST SETTINGS
# ------------------------------------------------------------

TEST_DATE = "2024-11-27"

SYMBOLS = [
    "NSE:NIFTY24NOV22500CE",
    "NSE:NIFTY24NOV22500PE",
]

IST = ZoneInfo("Asia/Kolkata")


# ------------------------------------------------------------
# EXPECTED NSE REGULAR SESSION
# ------------------------------------------------------------

EXPECTED_START_HOUR = 9
EXPECTED_START_MINUTE = 15

EXPECTED_END_HOUR = 15
EXPECTED_END_MINUTE = 29


# ------------------------------------------------------------
# HELPER: UNIX TIMESTAMP → IST
# ------------------------------------------------------------

def timestamp_to_ist(timestamp):
    return datetime.fromtimestamp(
        int(timestamp),
        tz=IST
    )


# ------------------------------------------------------------
# TEST ONE CONTRACT
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

    print("\nRequest:")
    print(request)

    print("\nRequesting FYERS historical data...")

    try:
        response = fyers.fno_historical_data(request)
    except Exception as error:
        print("\nAPI REQUEST ERROR:")
        print(error)
        return None

    # --------------------------------------------------------
    # BASIC RESPONSE
    # --------------------------------------------------------

    print("\nFYERS RESPONSE")
    print("-" * 75)

    print("Status     :", response.get("s"))
    print("Code       :", response.get("code"))
    print("Message    :", response.get("message"))
    print("Symbol     :", response.get("symbol"))
    print("Resolution :", response.get("resolution"))
    print("Schema     :", response.get("schema_version"))
    print("Columns    :", response.get("columns"))

    candles = response.get("candles", [])

    print("\nCandles received:", len(candles))

    if not candles:

        print("\nNo candles returned.")

        print("\nFull response:")
        print(json.dumps(response, indent=2))

        return response

    # --------------------------------------------------------
    # VALIDATE CANDLE STRUCTURE
    # --------------------------------------------------------

    columns = response.get("columns", [])

    if not columns:
        raise RuntimeError(
            "FYERS response does not contain column definitions."
        )

    records = []

    for candle in candles:

        if len(candle) != len(columns):
            print(
                "\nWARNING: Candle length does not match "
                "column count."
            )
            continue

        row = dict(zip(columns, candle))

        # Convert timestamp to IST
        if row.get("timestamp") is not None:

            dt_ist = timestamp_to_ist(
                row["timestamp"]
            )

            row["datetime_ist"] = dt_ist.strftime(
                "%Y-%m-%d %H:%M:%S"
            )

        records.append(row)

    # --------------------------------------------------------
    # FIRST / LAST
    # --------------------------------------------------------

    first = records[0]
    last = records[-1]

    print("\nFirst candle:")
    print(first)

    print("\nLast candle:")
    print(last)

    print("\nTime coverage:")
    print(
        first["datetime_ist"],
        "→",
        last["datetime_ist"]
    )

    # --------------------------------------------------------
    # OHLC / VOLUME / OI / GREEKS COMPLETENESS
    # --------------------------------------------------------

    fields = [
        "open",
        "high",
        "low",
        "close",
        "volume",
        "open_interest",
        "iv",
        "delta",
        "gamma",
        "theta",
        "vega",
    ]

    print("\nField completeness:")
    print("-" * 50)

    for field in fields:

        if field not in columns:
            print(
                f"{field:16s}: NOT PRESENT"
            )
            continue

        populated = sum(
            1
            for row in records
            if row.get(field) is not None
        )

        print(
            f"{field:16s}: "
            f"{populated}/{len(records)}"
        )

    # --------------------------------------------------------
    # ZERO VOLUME COUNT
    # --------------------------------------------------------

    if "volume" in columns:

        zero_volume = sum(
            1
            for row in records
            if row.get("volume") == 0
        )

        print(
            "\nZero-volume candles:",
            f"{zero_volume}/{len(records)}"
        )

    # --------------------------------------------------------
    # OPEN INTEREST CHANGES
    # --------------------------------------------------------

    if "open_interest" in columns:

        oi_values = [
            row.get("open_interest")
            for row in records
            if row.get("open_interest") is not None
        ]

        if oi_values:

            oi_changes = sum(
                1
                for i in range(1, len(oi_values))
                if oi_values[i] != oi_values[i - 1]
            )

            print(
                "Open-interest changes:",
                oi_changes
            )

    # --------------------------------------------------------
    # CHECK MINUTE GAPS
    # --------------------------------------------------------

    timestamps = [
        int(row["timestamp"])
        for row in records
        if row.get("timestamp") is not None
    ]

    timestamps = sorted(set(timestamps))

    gaps = []

    for i in range(1, len(timestamps)):

        difference = timestamps[i] - timestamps[i - 1]

        if difference != 60:
            gaps.append(
                {
                    "previous": timestamps[i - 1],
                    "current": timestamps[i],
                    "gap_seconds": difference
                }
            )

    print("\nTimestamp gap analysis:")
    print(
        "Non-60-second gaps:",
        len(gaps)
    )

    if gaps:

        print("\nFirst 10 gaps:")

        for gap in gaps[:10]:

            prev_dt = timestamp_to_ist(
                gap["previous"]
            )

            curr_dt = timestamp_to_ist(
                gap["current"]
            )

            print(
                prev_dt.strftime("%H:%M:%S"),
                "→",
                curr_dt.strftime("%H:%M:%S"),
                "| gap:",
                gap["gap_seconds"],
                "seconds"
            )

    else:

        print(
            "No timestamp gaps detected "
            "inside the returned sequence."
        )

    # --------------------------------------------------------
    # CHECK EXPECTED START / END
    # --------------------------------------------------------

    first_dt = timestamp_to_ist(
        records[0]["timestamp"]
    )

    last_dt = timestamp_to_ist(
        records[-1]["timestamp"]
    )

    expected_start = (
        f"{TEST_DATE} "
        f"{EXPECTED_START_HOUR:02d}:"
        f"{EXPECTED_START_MINUTE:02d}:00"
    )

    expected_end = (
        f"{TEST_DATE} "
        f"{EXPECTED_END_HOUR:02d}:"
        f"{EXPECTED_END_MINUTE:02d}:00"
    )

    actual_start = first_dt.strftime(
        "%Y-%m-%d %H:%M:%S"
    )

    actual_end = last_dt.strftime(
        "%Y-%m-%d %H:%M:%S"
    )

    print("\nSession boundary check:")
    print("Expected first:", expected_start)
    print("Actual first  :", actual_start)

    print("Expected last :", expected_end)
    print("Actual last   :", actual_end)

    if actual_start == expected_start:
        print("Start check   : PASS")
    else:
        print("Start check   : DIFFERENT")

    if actual_end == expected_end:
        print("End check     : PASS")
    else:
        print("End check     : DIFFERENT")

    # --------------------------------------------------------
    # EXPIRY-DAY / INTRADAY WINDOW CHECK
    # --------------------------------------------------------

    after_1500 = [
        row
        for row in records
        if row["datetime_ist"] >=
        f"{TEST_DATE} 15:00:00"
    ]

    print(
        "\nCandles from 15:00 onward:",
        len(after_1500)
    )

    print("\nLast 10 candles:")

    for row in records[-10:]:
        print(row)

    # --------------------------------------------------------
    # RETURN
    # --------------------------------------------------------

    return response


# ------------------------------------------------------------
# RUN BOTH CONTRACTS
# ------------------------------------------------------------

results = {}

for symbol in SYMBOLS:
    results[symbol] = test_symbol(symbol)


# ------------------------------------------------------------
# SAVE RESULTS
# ------------------------------------------------------------

output_file = (
    "fyers_nifty_pre_expiry_1m_test.json"
)

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


# ------------------------------------------------------------
# FINAL SUMMARY
# ------------------------------------------------------------

print("\n" + "=" * 75)
print("PRE-EXPIRY 1-MINUTE TEST COMPLETE")
print("=" * 75)

for symbol, response in results.items():

    if response is None:
        print(symbol, "→ REQUEST ERROR")
        continue

    status = response.get("s")

    candle_count = len(
        response.get("candles", [])
    )

    print(
        symbol,
        "→",
        status,
        "| candles:",
        candle_count
    )

print("\nSaved:")
print(output_file)

print("=" * 75)