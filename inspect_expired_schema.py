import json

FILE = "fyers_expired_nifty_22500ce_2024_11.json"

with open(FILE, "r", encoding="utf-8") as f:
    data = json.load(f)

print("=" * 70)
print("KUNAL QUANT - EXPIRED F&O RESPONSE SCHEMA")
print("=" * 70)

print("\nTop-level keys:")
print(list(data.keys()))

print("\nSymbol:")
print(data.get("symbol"))

print("\nResolution:")
print(data.get("resolution"))

print("\nSchema version:")
print(data.get("schema_version"))

print("\nColumns:")
print(data.get("columns"))

print("\nNumber of candles:")
print(len(data.get("candles", [])))

print("\nFirst candle:")
print(data.get("candles", [])[0])

print("\nLast candle:")
print(data.get("candles", [])[-1])

print("\n" + "=" * 70)
print("SCHEMA INSPECTION COMPLETE")
print("=" * 70)