import os
import re
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import requests
from dotenv import load_dotenv
from fyers_apiv3.FyersWebsocket import data_ws


# ============================================================
# KUNAL QUANT
# FYERS DATA WEBSOCKET TEST
# ============================================================

load_dotenv()

APP_ID = os.getenv("FYERS_CLIENT_ID")

with open("fyers_access_token.txt", "r", encoding="utf-8") as file:
    ACCESS_TOKEN = file.read().strip()

if not APP_ID:
    raise RuntimeError("FYERS_CLIENT_ID missing from .env")

if not ACCESS_TOKEN:
    raise RuntimeError("FYERS access token missing")

FULL_ACCESS_TOKEN = f"{APP_ID}:{ACCESS_TOKEN}"

SYMBOL_MASTER_URL = "https://public.fyers.in/sym_details/NSE_FO_sym_master.json"
INDIA_TZ = ZoneInfo("Asia/Kolkata")
# Match standard NIFTY monthly futures only. This excludes BANKNIFTY,
# FINNIFTY, NIFTYNXT50, NIFTYFPI and options.
NIFTY_FUTURES_PATTERN = re.compile(r"^NIFTY\d{2}[A-Z]{3}FUT$")


def get_current_nifty_futures_symbol(now=None):
    """Resolve the active front-month NIFTY futures symbol from FYERS master.

    Prefer a contract expiring in the current calendar month. Once that
    contract has expired, roll forward to the nearest unexpired standard
    NIFTY futures contract. Never fall back to a hardcoded symbol.
    """
    now = now or datetime.now(INDIA_TZ)
    response = requests.get(SYMBOL_MASTER_URL, timeout=30)
    response.raise_for_status()
    master = response.json()

    if not isinstance(master, dict):
        raise RuntimeError("Unexpected FYERS symbol-master response format")

    candidates = []
    for symbol, details in master.items():
        if not isinstance(details, dict):
            continue

        exchange_symbol = str(details.get("exSymName", "")).strip().upper()
        if not NIFTY_FUTURES_PATTERN.fullmatch(exchange_symbol):
            continue

        try:
            expiry_epoch = int(details["expiryDate"])
            expiry = datetime.fromtimestamp(expiry_epoch, INDIA_TZ)
        except (KeyError, TypeError, ValueError, OSError, OverflowError):
            continue

        if expiry <= now:
            continue

        candidates.append((expiry, symbol, exchange_symbol))

    if not candidates:
        raise RuntimeError(
            "No unexpired standard NIFTY futures contract found in FYERS symbol master"
        )

    current_month = [
        candidate
        for candidate in candidates
        if candidate[0].year == now.year and candidate[0].month == now.month
    ]

    if current_month:
        expiry, symbol, exchange_symbol = min(current_month, key=lambda item: item[0])
        print(f"Selected current-month NIFTY futures: {exchange_symbol} (expiry {expiry:%d %b %Y})")
    else:
        expiry, symbol, exchange_symbol = min(candidates, key=lambda item: item[0])
        print(
            "Current-month NIFTY futures is no longer available; "
            f"rolling to nearest unexpired contract: {exchange_symbol} "
            f"(expiry {expiry:%d %b %Y})"
        )

    return symbol


FUTURES_SYMBOL = get_current_nifty_futures_symbol()
SYMBOLS = [
    "NSE:NIFTY50-INDEX",
    FUTURES_SYMBOL,
]


def on_message(message):
    print("\nDATA RECEIVED:")
    print(message)


def on_error(message):
    print("\nWEBSOCKET ERROR:")
    print(message)


def on_close(message):
    print("\nWEBSOCKET CLOSED:")
    print(message)


def on_open():
    print("\nWEBSOCKET CONNECTED")

    data_type = "SymbolUpdate"

    print("Subscribing to:")
    for symbol in SYMBOLS:
        print("  ", symbol)

    fyers.subscribe(
        symbols=SYMBOLS,
        data_type=data_type
    )

    print("\nSubscription request sent.")
    print("Waiting for live data...")


fyers = data_ws.FyersDataSocket(
    access_token=FULL_ACCESS_TOKEN,
    log_path="",
    litemode=False,
    write_to_file=False,
    reconnect=True,
    on_connect=on_open,
    on_close=on_close,
    on_error=on_error,
    on_message=on_message
)


print("=" * 70)
print("KUNAL QUANT - FYERS WEBSOCKET TEST")
print("=" * 70)

print("\nConnecting...")

fyers.connect()

# Keep script alive for 30 seconds
time.sleep(30)

print("\n30-second test finished.")
print("Closing WebSocket...")

try:
    fyers.close_connection()
except Exception as error:
    print("Close message:", error)

print("\n" + "=" * 70)
print("WEBSOCKET TEST COMPLETE")
print("=" * 70)
