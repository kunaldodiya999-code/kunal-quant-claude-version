import os
from datetime import datetime, timedelta

from dotenv import load_dotenv
from fyers_apiv3 import fyersModel


# ============================================================
# KUNAL QUANT
# FYERS HISTORICAL DATA TEST
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
# TEST PARAMETERS
# ------------------------------------------------------------

SYMBOL = "NSE:NIFTY50-INDEX"
RESOLUTION = "1"

# One completed historical trading day
FROM_DATE = "2026-09-17"
TO_DATE = "2026-09-17"


print("=" * 70)
print("KUNAL QUANT - FYERS HISTORICAL DATA TEST")
print("=" * 70)

print("\nSymbol     :", SYMBOL)
print("Resolution :", "1 minute")
print("From       :", FROM_DATE)
print("To         :", TO_DATE)


# ------------------------------------------------------------
# HISTORICAL DATA REQUEST
# ------------------------------------------------------------

data = {
    "symbol": SYMBOL,
    "resolution": RESOLUTION,
    "date_format": "1",
    "range_from": FROM_DATE,
    "range_to": TO_DATE,
    "cont_flag": "1"
}


print("\nRequesting historical data...")

response = fyers.history(data=data)

print("\nFYERS RESPONSE STATUS:")
print("Status :", response.get("s"))
print("Code   :", response.get("code"))
print("Message:", response.get("message"))


# ------------------------------------------------------------
# PROCESS RESPONSE
# ------------------------------------------------------------

candles = response.get("candles", [])

print("\nNumber of candles received:", len(candles))


if candles:

    print("\nFirst 5 candles:")

    for candle in candles[:5]:
        print(candle)

    print("\nLast 5 candles:")

    for candle in candles[-5:]:
        print(candle)

    # --------------------------------------------------------
    # SAVE RAW RESPONSE
    # --------------------------------------------------------

    output_file = "fyers_nifty_1m_test.json"

    import json

    with open(output_file, "w", encoding="utf-8") as file:
        json.dump(response, file, indent=2)

    print("\nRaw response saved as:")
    print(output_file)

else:

    print("\nNo candles were returned.")

    print("\nFull response:")
    print(response)


print("\n" + "=" * 70)
print("HISTORICAL DATA TEST COMPLETE")
print("=" * 70)