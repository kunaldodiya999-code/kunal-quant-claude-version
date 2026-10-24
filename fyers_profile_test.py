import os

from dotenv import load_dotenv
from fyers_apiv3 import fyersModel


load_dotenv()

CLIENT_ID = os.getenv("FYERS_CLIENT_ID")

with open("fyers_access_token.txt", "r", encoding="utf-8") as file:
    ACCESS_TOKEN = file.read().strip()


if not CLIENT_ID:
    raise RuntimeError("FYERS_CLIENT_ID is missing from .env")

if not ACCESS_TOKEN:
    raise RuntimeError("FYERS access token is empty")


fyers = fyersModel.FyersModel(
    client_id=CLIENT_ID,
    token=ACCESS_TOKEN,
    is_async=False,
    log_path=""
)

print("=" * 60)
print("KUNAL QUANT - FYERS PROFILE TEST")
print("=" * 60)

response = fyers.get_profile()

print("\nFYERS RESPONSE:")
print(response)