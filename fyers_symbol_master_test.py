import requests

URL = "https://public.fyers.in/sym_details/NSE_FO_sym_master.json"

print("=" * 70)
print("KUNAL QUANT - FYERS NSE F&O SYMBOL MASTER TEST")
print("=" * 70)

print("\nDownloading symbol master...")

response = requests.get(URL, timeout=30)

print("HTTP Status:", response.status_code)

if response.status_code != 200:
    print("Download failed.")
    print(response.text[:500])
    raise SystemExit(1)

data = response.json()

print("Download successful.")
print("Total symbols received:", len(data))

# Show a few NIFTY-related symbols
count = 0

print("\nSample NIFTY symbols:")

for symbol, details in data.items():

    if symbol.startswith("NSE:NIFTY"):

        print(symbol)

        if isinstance(details, dict):
            print("  Details:", details)

        count += 1

        if count >= 10:
            break

print("\n" + "=" * 70)
print("SYMBOL MASTER TEST COMPLETE")
print("=" * 70)