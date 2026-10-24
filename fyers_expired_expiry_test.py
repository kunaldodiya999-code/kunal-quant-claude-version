import os
import requests
from datetime import date, timedelta
from dotenv import load_dotenv


# ============================================================
# KUNAL QUANT
# FYERS EXPIRED F&O - EXPIRY DATE TEST
# ============================================================

load_dotenv()

CLIENT_ID = os.getenv("FYERS_CLIENT_ID")

with open("fyers_access_token.txt", "r", encoding="utf-8") as file:
    ACCESS_TOKEN = file.read().strip()

if not CLIENT_ID:
    raise RuntimeError("FYERS_CLIENT_ID is missing from .env")

if not ACCESS_TOKEN:
    raise RuntimeError("FYERS access token is missing")


# ------------------------------------------------------------
# SETTINGS
# ------------------------------------------------------------

UNDERLYING = "NSE:NIFTY50-INDEX"

START_DATE = date(2021, 9, 18)
END_DATE = date(2026, 9, 17)

MAX_DAYS_PER_REQUEST = 365

URL = (
    "https://api-t1.fyers.in/data/history/"
    "fno/expired/expiry-dates"
)

HEADERS = {
    "Authorization": f"{CLIENT_ID}:{ACCESS_TOKEN}"
}


# ------------------------------------------------------------
# FETCH ONE CHUNK
# ------------------------------------------------------------

def fetch_chunk(start_date, end_date):

    params = {
        "symbol": UNDERLYING,
        "range_from": start_date.strftime("%Y-%m-%d"),
        "range_to": end_date.strftime("%Y-%m-%d"),
        "date_format": "1",
    }

    print(
        f"\nRequesting: "
        f"{params['range_from']} → {params['range_to']}"
    )

    response = requests.get(
        URL,
        params=params,
        headers=HEADERS,
        timeout=30
    )

    print("HTTP Status:", response.status_code)

    try:
        result = response.json()
    except ValueError:
        print("Invalid JSON response:")
        print(response.text[:1000])
        return None

    print(
        "API Status:",
        result.get("s"),
        "| Code:",
        result.get("code"),
        "| Message:",
        result.get("message")
    )

    return result


# ------------------------------------------------------------
# MAIN
# ------------------------------------------------------------

print("=" * 75)
print("KUNAL QUANT - FYERS EXPIRED F&O EXPIRY TEST")
print("=" * 75)

print("\nUnderlying :", UNDERLYING)
print("Start date :", START_DATE)
print("End date   :", END_DATE)


all_futures_expiries = []
all_option_expiries = []

current_start = START_DATE

while current_start <= END_DATE:

    current_end = min(
        current_start + timedelta(days=MAX_DAYS_PER_REQUEST - 1),
        END_DATE
    )

    result = fetch_chunk(
        current_start,
        current_end
    )

    if result is None:
        print("\nRequest failed.")
        break

    if result.get("s") != "ok":
        print("\nChunk failed.")
        print("Full response:")
        print(result)
        break

    # --------------------------------------------------------
    # CURRENT FYERS RESPONSE STRUCTURE
    #
    # response["data"]["expiry_dates"]["futures"]
    # response["data"]["expiry_dates"]["options"]
    # --------------------------------------------------------

    data = result.get("data", {})
    expiry_dates = data.get("expiry_dates", {})

    futures = expiry_dates.get("futures", [])
    options = expiry_dates.get("options", [])

    print("Futures expiries returned:", len(futures))
    print("Options expiries returned:", len(options))

    all_futures_expiries.extend(futures)
    all_option_expiries.extend(options)

    current_start = current_end + timedelta(days=1)


# ------------------------------------------------------------
# REMOVE DUPLICATES
# ------------------------------------------------------------

def unique_records(records):

    cleaned = {}

    for record in records:

        if isinstance(record, dict):

            expiry = record.get("expiry")

            if expiry is not None:
                cleaned[str(expiry)] = record

        else:

            cleaned[str(record)] = {
                "expiry": record
            }

    return list(cleaned.values())


unique_futures = unique_records(all_futures_expiries)
unique_options = unique_records(all_option_expiries)


# Sort by expiry timestamp
unique_futures.sort(
    key=lambda x: str(x.get("expiry", ""))
)

unique_options.sort(
    key=lambda x: str(x.get("expiry", ""))
)


# ------------------------------------------------------------
# RESULTS
# ------------------------------------------------------------

print("\n" + "=" * 75)
print("RESULT")
print("=" * 75)

print("\nUnique FUTURES expiry records:", len(unique_futures))
print("Unique OPTIONS expiry records:", len(unique_options))


print("\nFIRST 10 FUTURES EXPIRIES")

for item in unique_futures[:10]:
    print(item)


print("\nFIRST 10 OPTIONS EXPIRIES")

for item in unique_options[:10]:
    print(item)


print("\nLAST 10 OPTIONS EXPIRIES")

for item in unique_options[-10:]:
    print(item)


# ------------------------------------------------------------
# SAVE RESULTS
# ------------------------------------------------------------

import json

output_file = "fyers_nifty_expired_expiry_dates.json"

output = {
    "underlying": UNDERLYING,
    "range_from": str(START_DATE),
    "range_to": str(END_DATE),
    "futures_expiries": unique_futures,
    "options_expiries": unique_options
}

with open(
    output_file,
    "w",
    encoding="utf-8"
) as file:
    json.dump(output, file, indent=2)


print("\nSaved complete expiry data as:")
print(output_file)

print("\n" + "=" * 75)
print("5-YEAR EXPIRY TEST COMPLETE")
print("=" * 75)