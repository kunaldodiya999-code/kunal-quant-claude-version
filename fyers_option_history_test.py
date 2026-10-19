import os
import requests

from dotenv import load_dotenv
from fyers_apiv3 import fyersModel


# ============================================================
# KUNAL QUANT
# FYERS NIFTY OPTION HISTORICAL DATA TEST
# ============================================================

load_dotenv()

CLIENT_ID = os.getenv("FYERS_CLIENT_ID")

with open("fyers_access_token.txt", "r", encoding="utf-8") as file:
    ACCESS_TOKEN = file.read().strip()

if not CLIENT_ID:
    raise RuntimeError("FYERS_CLIENT_ID is missing from .env")

if not ACCESS_TOKEN:
    raise RuntimeError("FYERS access token is missing")


fyers = fyersModel.FyersModel(
    client_id=CLIENT_ID,
    token=ACCESS_TOKEN,
    is_async=False,
    log_path=""
)


# ------------------------------------------------------------
# SETTINGS
# ------------------------------------------------------------

TEST_DATE = "2026-09-17"

MASTER_URL = (
    "https://public.fyers.in/"
    "sym_details/NSE_FO_sym_master.json"
)

UNDERLYING = "NIFTY"


# ------------------------------------------------------------
# DOWNLOAD SYMBOL MASTER
# ------------------------------------------------------------

print("=" * 70)
print("KUNAL QUANT - NIFTY OPTION HISTORY TEST")
print("=" * 70)

print("\nDownloading NSE F&O symbol master...")

response = requests.get(MASTER_URL, timeout=30)

if response.status_code != 200:
    raise RuntimeError(
        f"Symbol master failed: HTTP {response.status_code}"
    )

symbols = response.json()

print("Symbol master loaded.")
print("Total symbols:", len(symbols))


# ------------------------------------------------------------
# FIND NIFTY OPTIONS
# ------------------------------------------------------------

options = []

for symbol, details in symbols.items():

    if not isinstance(details, dict):
        continue

    if details.get("underSym") != UNDERLYING:
        continue

    opt_type = details.get("optType")
    strike = details.get("strikePrice")
    expiry = details.get("expiryDate")

    if opt_type not in ("CE", "PE"):
        continue

    if strike is None or strike <= 0:
        continue

    if not expiry:
        continue

    options.append(
        {
            "symbol": symbol,
            "optionType": opt_type,
            "strike": float(strike),
            "expiry": int(expiry),
            "lotSize": details.get("minLotSize"),
            "tickSize": details.get("tickSize"),
            "fyToken": details.get("fyToken"),
            "exToken": details.get("exToken"),
            "description": details.get("symbolDetails"),
        }
    )


print("\nNIFTY option contracts found:", len(options))


# ------------------------------------------------------------
# SORT BY EXPIRY THEN STRIKE
# ------------------------------------------------------------

options.sort(
    key=lambda x: (
        x["expiry"],
        x["strike"],
        x["optionType"]
    )
)


print("\nSample contracts:")

for item in options[:10]:
    print(
        item["symbol"],
        "|",
        item["optionType"],
        "| Strike:",
        item["strike"],
        "| Lot:",
        item["lotSize"]
    )


if not options:
    raise RuntimeError("No NIFTY options found.")


# ------------------------------------------------------------
# SELECT A CONTRACT
#
# We choose a CE and a PE from the nearest available expiry.
# This verifies both sides of the option chain.
# ------------------------------------------------------------

nearest_expiry = options[0]["expiry"]

nearest_options = [
    x for x in options
    if x["expiry"] == nearest_expiry
]

ce_options = [
    x for x in nearest_options
    if x["optionType"] == "CE"
]

pe_options = [
    x for x in nearest_options
    if x["optionType"] == "PE"
]


if not ce_options or not pe_options:
    raise RuntimeError(
        "Could not find both CE and PE for nearest expiry."
    )


# Select middle strike to avoid extreme strikes
ce_contract = ce_options[len(ce_options) // 2]
pe_contract = pe_options[len(pe_options) // 2]


print("\nSelected CE:")
print(ce_contract["symbol"])

print("\nSelected PE:")
print(pe_contract["symbol"])


# ------------------------------------------------------------
# FUNCTION TO TEST HISTORY
# ------------------------------------------------------------

def test_history(contract):

    symbol = contract["symbol"]

    request = {
        "symbol": symbol,
        "resolution": "1",
        "date_format": "1",
        "range_from": TEST_DATE,
        "range_to": TEST_DATE,
        "cont_flag": "0"
    }

    print("\n" + "-" * 70)
    print("Testing:", symbol)
    print("Date   :", TEST_DATE)
    print("-" * 70)

    result = fyers.history(data=request)

    print("Status :", result.get("s"))
    print("Code   :", result.get("code"))
    print("Message:", result.get("message"))

    candles = result.get("candles", [])

    print("Candles received:", len(candles))

    if candles:
        print("\nFirst 3 candles:")

        for candle in candles[:3]:
            print(candle)

        print("\nLast 3 candles:")

        for candle in candles[-3:] :
            print(candle)

        return result

    print("\nNo candles returned.")
    print("Response:")
    print(result)

    return result


# ------------------------------------------------------------
# TEST CE
# ------------------------------------------------------------

ce_result = test_history(ce_contract)


# ------------------------------------------------------------
# TEST PE
# ------------------------------------------------------------

pe_result = test_history(pe_contract)


# ------------------------------------------------------------
# SAVE RESULTS
# ------------------------------------------------------------

import json

output = {
    "test_date": TEST_DATE,
    "CE": {
        "symbol": ce_contract["symbol"],
        "result": ce_result
    },
    "PE": {
        "symbol": pe_contract["symbol"],
        "result": pe_result
    }
}

with open(
    "fyers_nifty_option_history_test.json",
    "w",
    encoding="utf-8"
) as file:
    json.dump(output, file, indent=2)


print("\n" + "=" * 70)
print("NIFTY OPTION HISTORY TEST COMPLETE")
print("=" * 70)

print("\nSaved as:")
print("fyers_nifty_option_history_test.json")