import os
from dotenv import load_dotenv
from fyers_apiv3 import fyersModel


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


print("=" * 70)
print("KUNAL QUANT - FYERS CONNECTION TEST")
print("=" * 70)


# ------------------------------------------------------------
# 1. PROFILE
# ------------------------------------------------------------
print("\n[1] PROFILE")
profile = fyers.get_profile()

print("Status :", profile.get("s"))
print("Code   :", profile.get("code"))
print("Message:", profile.get("message"))


# ------------------------------------------------------------
# 2. FUNDS
# ------------------------------------------------------------
print("\n[2] FUNDS")
funds = fyers.funds()

print("Status :", funds.get("s"))
print("Code   :", funds.get("code"))
print("Message:", funds.get("message"))

if funds.get("s") == "ok":
    print("Funds API: SUCCESS")
else:
    print("Funds API: FAILED")


# ------------------------------------------------------------
# 3. POSITIONS
# ------------------------------------------------------------
print("\n[3] POSITIONS")
positions = fyers.positions()

print("Status :", positions.get("s"))
print("Code   :", positions.get("code"))
print("Message:", positions.get("message"))

if positions.get("s") == "ok":
    position_data = positions.get("netPositions", [])
    print("Open/net positions returned:", len(position_data))
else:
    print("Positions API: FAILED")


# ------------------------------------------------------------
# 4. QUOTE
# ------------------------------------------------------------
print("\n[4] MARKET QUOTE")

quote_request = {
    "symbols": "NSE:NIFTY50-INDEX"
}

quote = fyers.quotes(quote_request)

print("Status :", quote.get("s"))
print("Code   :", quote.get("code"))
print("Message:", quote.get("message"))

if quote.get("s") == "ok":
    print("Quote API: SUCCESS")

    try:
        data = quote["d"][0]
        v = data.get("v", {})

        print("Symbol :", data.get("n"))
        print("LTP    :", v.get("lp"))
        print("Volume :", v.get("volume"))

    except (KeyError, IndexError, TypeError):
        print("Quote received, but response format needs inspection.")
else:
    print("Quote API: FAILED")


print("\n" + "=" * 70)
print("TEST COMPLETE")
print("=" * 70)