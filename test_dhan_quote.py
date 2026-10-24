import os

import requests
from dotenv import load_dotenv

load_dotenv()

CLIENT_ID = os.getenv("DHAN_CLIENT_ID", "").strip()
ACCESS_TOKEN = os.getenv("DHAN_ACCESS_TOKEN", "").strip()
if not ACCESS_TOKEN:
    raise SystemExit("DHAN_ACCESS_TOKEN is missing from local .env; token was not printed.")
if not CLIENT_ID:
    raise SystemExit("DHAN_CLIENT_ID is missing from local .env.")

response = requests.post(
    "https://api.dhan.co/v2/marketfeed/ltp",
    headers={
        "access-token": ACCESS_TOKEN,
        "client-id": CLIENT_ID,
        "Content-Type": "application/json",
    },
    json={"NSE_EQ": ["13"]},
    timeout=15,
)

print("Dhan quote HTTP status:", response.status_code)
if response.ok:
    print("Dhan quote API: SUCCESS")
else:
    print("Dhan quote API: FAILED (response body intentionally not printed)")
