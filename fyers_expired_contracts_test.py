import os
import requests
import json
from dotenv import load_dotenv


# ============================================================
# KUNAL QUANT
# FYERS EXPIRED F&O CONTRACT TEST
# ============================================================

load_dotenv()

CLIENT_ID = os.getenv("FYERS_CLIENT_ID")

with open("fyers_access_token.txt", "r", encoding="utf-8") as file:
    ACCESS_TOKEN = file.read().strip()

if not CLIENT_ID:
    raise RuntimeError("FYERS_CLIENT_ID missing from .env")

if not ACCESS_TOKEN:
    raise RuntimeError("FYERS access token missing")


URL = (
    "https://api-t1.fyers.in/data/history/"
    "fno/expired/underlying-symbols"
)

HEADERS = {
    "Authorization": f"{CLIENT_ID}:{ACCESS_TOKEN}"
}


# ------------------------------------------------------------
# KNOWN HISTORICAL EXPIRY
# ------------------------------------------------------------

UNDERLYING = "NSE:NIFTY50-INDEX"
EXPIRY_DATE = "2024-11-28"


print("=" * 75)
print("KUNAL QUANT - FYERS EXPIRED F&O CONTRACT TEST")
print("=" * 75)

print("\nUnderlying :", UNDERLYING)
print("Expiry     :", EXPIRY_DATE)


params = {
    "symbol": UNDERLYING,
    "expiry_date": EXPIRY_DATE
}


print("\nRequesting expired contracts...")

response = requests.get(
    URL,
    params=params,
    headers=HEADERS,
    timeout=30
)

print("\nHTTP Status:", response.status_code)

try:
    result = response.json()
except ValueError:
    print(response.text)
    raise SystemExit(1)


print("API Status :", result.get("s"))
print("API Code   :", result.get("code"))
print("Message    :", result.get("message"))


# ------------------------------------------------------------
# SHOW RAW STRUCTURE
# ------------------------------------------------------------

print("\nRAW RESPONSE:")
print(json.dumps(result, indent=2)[:15000])


# ------------------------------------------------------------
# SAVE COMPLETE RESPONSE
# ------------------------------------------------------------

output_file = "fyers_expired_contracts_2024_11_28.json"

with open(
    output_file,
    "w",
    encoding="utf-8"
) as file:
    json.dump(result, file, indent=2)


print("\nComplete response saved as:")
print(output_file)

print("\n" + "=" * 75)
print("EXPIRED CONTRACT TEST COMPLETE")
print("=" * 75)