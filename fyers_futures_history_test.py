import os
import requests

from dotenv import load_dotenv
from fyers_apiv3 import fyersModel


# ============================================================
# KUNAL QUANT
# FYERS NIFTY FUTURES HISTORICAL DATA TEST
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
# FYERS API CLIENT
# ------------------------------------------------------------

fyers = fyersModel.FyersModel(
    client_id=CLIENT_ID,
    token=ACCESS_TOKEN,
    is_async=False,
    log_path=""
)


# ------------------------------------------------------------
# DOWNLOAD CURRENT NSE F&O SYMBOL MASTER
# ------------------------------------------------------------

MASTER_URL = (
    "https://public.fyers.in/"
    "sym_details/NSE_FO_sym_master.json"
)

print("=" * 70)
print("KUNAL QUANT - NIFTY FUTURES HISTORY TEST")
print("=" * 70)

print("\nDownloading NSE F&O symbol master...")

response = requests.get(MASTER_URL, timeout=30)

if response.status_code != 200:
    raise RuntimeError(
        f"Symbol master download failed: {response.status_code}"
    )

symbols = response.json()

print("Symbol master loaded.")
print("Total symbols:", len(symbols))


# ------------------------------------------------------------
# FIND NIFTY FUTURES
# ------------------------------------------------------------

TARGET_DATE = "2026-09-17"

nifty_futures = []

for symbol, details in symbols.items():

    if not isinstance(details, dict):
        continue

    if details.get("underSym") != "NIFTY":
        continue

    # Futures have optType == XX and strikePrice == -1
    if details.get("optType") != "XX":
        continue

    if details.get("strikePrice") != -1.0:
        continue

    expiry = details.get("expiryDate")

    if not expiry:
        continue

    nifty_futures.append(
        {
            "symbol": symbol,
            "fyToken": details.get("fyToken"),
            "exToken": details.get("exToken"),
            "expiryDate": expiry,
            "lotSize": details.get("minLotSize"),
            "tickSize": details.get("tickSize"),
            "description": details.get("symbolDetails")
        }
    )


# ------------------------------------------------------------
# SORT FUTURES BY EXPIRY
# ------------------------------------------------------------

nifty_futures.sort(key=lambda x: x["expiryDate"])


print("\nNIFTY FUTURES FOUND:", len(nifty_futures))

for item in nifty_futures[:5]:
    print(
        item["symbol"],
        "| Expiry:",
        item["expiryDate"],
        "| Lot:",
        item["lotSize"],
        "| Tick:",
        item["tickSize"]
    )


if not nifty_futures:
    raise RuntimeError("No NIFTY futures found in symbol master.")


# ------------------------------------------------------------
# USE THE FIRST AVAILABLE CURRENT FUTURE
# ------------------------------------------------------------

FUTURE_SYMBOL = nifty_futures[0]["symbol"]

print("\nSelected futures contract:")
print(FUTURE_SYMBOL)


# ------------------------------------------------------------
# HISTORICAL DATA REQUEST
# ------------------------------------------------------------

history_request = {
    "symbol": FUTURE_SYMBOL,
    "resolution": "1",
    "date_format": "1",
    "range_from": TARGET_DATE,
    "range_to": TARGET_DATE,
    "cont_flag": "1"
}


print("\nRequesting 1-minute historical data...")
print("Date:", TARGET_DATE)

history_response = fyers.history(
    data=history_request
)


# ------------------------------------------------------------
# RESPONSE
# ------------------------------------------------------------

print("\nFYERS RESPONSE:")
print("Status :", history_response.get("s"))
print("Code   :", history_response.get("code"))
print("Message:", history_response.get("message"))


candles = history_response.get("candles", [])

print("\nCandles received:", len(candles))


if not candles:

    print("\nNo candles returned.")
    print("Full response:")
    print(history_response)

else:

    print("\nFirst 5 candles:")

    for candle in candles[:5]:
        print(candle)

    print("\nLast 5 candles:")

    for candle in candles[-5:]:
        print(candle)


# ------------------------------------------------------------
# SAVE RESULT
# ------------------------------------------------------------

import json

output_file = "fyers_nifty_futures_1m_test.json"

with open(output_file, "w", encoding="utf-8") as file:
    json.dump(history_response, file, indent=2)

print("\nRaw response saved as:")
print(output_file)

print("\n" + "=" * 70)
print("NIFTY FUTURES HISTORY TEST COMPLETE")
print("=" * 70)