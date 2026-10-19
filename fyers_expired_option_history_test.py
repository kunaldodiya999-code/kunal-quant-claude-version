import os
import json

from dotenv import load_dotenv
from fyers_apiv3 import fyersModel


# ============================================================
# KUNAL QUANT
# FYERS EXPIRED OPTION HISTORICAL DATA TEST
# ============================================================

load_dotenv()

CLIENT_ID = os.getenv("FYERS_CLIENT_ID")

with open("fyers_access_token.txt", "r", encoding="utf-8") as file:
    ACCESS_TOKEN = file.read().strip()

if not CLIENT_ID:
    raise RuntimeError("FYERS_CLIENT_ID missing from .env")

if not ACCESS_TOKEN:
    raise RuntimeError("FYERS access token missing")


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
# TEST CONTRACT
# ------------------------------------------------------------

SYMBOL = "NSE:NIFTY24NOV22500CE"

REQUEST = {
    "symbol": SYMBOL,
    "resolution": "5",
    "date_format": "1",
    "range_from": "2024-11-01",
    "range_to": "2024-11-28",
    "include_greeks": "1",
    "include_oi": "1"
}


print("=" * 75)
print("KUNAL QUANT - EXPIRED OPTION HISTORICAL DATA TEST")
print("=" * 75)

print("\nSymbol          :", SYMBOL)
print("Resolution      : 5 minute")
print("From            : 2024-11-01")
print("To              : 2024-11-28")
print("Include OI      : YES")
print("Include Greeks  : YES")

print("\nRequesting expired option historical data...")

response = fyers.fno_historical_data(REQUEST)


print("\nFYERS RESPONSE")
print("-" * 75)

print("Status  :", response.get("s"))
print("Code    :", response.get("code"))
print("Message :", response.get("message"))


# ------------------------------------------------------------
# SHOW RAW KEYS
# ------------------------------------------------------------

print("\nResponse keys:")

if isinstance(response, dict):
    print(list(response.keys()))


# ------------------------------------------------------------
# CANDLES
# ------------------------------------------------------------

candles = response.get("candles", [])

print("\nCandles received:", len(candles))


if candles:

    print("\nFirst 5 candles:")

    for candle in candles[:5]:
        print(candle)

    print("\nLast 5 candles:")

    for candle in candles[-5:]:
        print(candle)

else:

    print("\nNo candles returned.")


# ------------------------------------------------------------
# SAVE COMPLETE RESPONSE
# ------------------------------------------------------------

output_file = "fyers_expired_nifty_22500ce_2024_11.json"

with open(
    output_file,
    "w",
    encoding="utf-8"
) as file:
    json.dump(response, file, indent=2)


print("\nComplete response saved as:")
print(output_file)


print("\n" + "=" * 75)
print("EXPIRED OPTION HISTORY TEST COMPLETE")
print("=" * 75)