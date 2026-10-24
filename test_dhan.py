import os

import requests
from dotenv import load_dotenv

load_dotenv()

ACCESS_TOKEN = os.getenv("DHAN_ACCESS_TOKEN", "").strip()
if not ACCESS_TOKEN:
    raise SystemExit("DHAN_ACCESS_TOKEN is missing from local .env; token was not printed.")

response = requests.get(
    "https://api.dhan.co/v2/profile",
    headers={"access-token": ACCESS_TOKEN},
    timeout=15,
)

print("Dhan profile HTTP status:", response.status_code)
if response.ok:
    print("Dhan authentication: SUCCESS")
else:
    print("Dhan authentication: FAILED (response body intentionally not printed)")
