import os
import json

from dotenv import load_dotenv
from fyers_apiv3 import fyersModel


# ============================================================
# KUNAL QUANT
# FYERS MARKET DEPTH TEST
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


# Use a currently active F&O contract.
SYMBOL = "NSE:NIFTY26SEPFUT"


request = {
    "symbol": SYMBOL,
    "ohlcv_flag": "1"
}


print("=" * 70)
print("KUNAL QUANT - FYERS MARKET DEPTH TEST")
print("=" * 70)

print("\nSymbol:", SYMBOL)

print("\nRequesting market depth...")

response = fyers.depth(request)


print("\nStatus :", response.get("s"))
print("Code   :", response.get("code"))
print("Message:", response.get("message"))

print("\nTop-level keys:")
print(list(response.keys()))

print("\nFULL RESPONSE:")
print(json.dumps(response, indent=2))


with open(
    "fyers_depth_test.json",
    "w",
    encoding="utf-8"
) as file:
    json.dump(response, file, indent=2)


print("\nSaved as:")
print("fyers_depth_test.json")

print("\n" + "=" * 70)
print("DEPTH TEST COMPLETE")
print("=" * 70)