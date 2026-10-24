"""Build the targeted HFT 10S manifest from historical NIFTY 1m data."""
from __future__ import annotations
import argparse, csv, json, math, sqlite3
from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
from api.fyers_client import FyersClient
from config.hft_data import HFT_OPTION_TYPES, HFT_PE_STRIKE_OFFSETS, HFT_RESOLUTION, HFT_STRIKE_OFFSETS
from config.settings import DATABASE_PATH, TIMEZONE
from database.repository import DatabaseRepository
from research.hft_contract_discovery import (
    UNDERLYING_SYMBOL, discover_expiry_dates, find_option_symbols,
    find_nearest_future_symbol, nearest_expiry,
)

def connect():
    connection = sqlite3.connect(DATABASE_PATH)
    connection.row_factory = sqlite3.Row
    return connection

def atm(price: float) -> int:
    return int(math.floor(float(price) / 50.0 + 0.5) * 50)

def load_daily_open_rows(start: str, end: str) -> list[dict]:
    tz = ZoneInfo(TIMEZONE)
    with connect() as db:
        rows = db.execute(
            """SELECT timestamp, open FROM candles JOIN instruments i ON i.id=candles.instrument_id
               WHERE i.broker='FYERS' AND i.symbol=? AND candles.resolution='1'
               AND timestamp BETWEEN strftime('%s', ?) AND strftime('%s', ?) ORDER BY timestamp""",
            (UNDERLYING_SYMBOL, start + " 00:00:00", end + " 23:59:59"),
        ).fetchall()
        by_day = {}
        for row in rows:
            dt = datetime.fromtimestamp(int(row["timestamp"]), timezone.utc).astimezone(tz)
            day = dt.date().isoformat()
            by_day.setdefault(day, {"trade_date": day, "timestamp": int(row["timestamp"]), "open": float(row["open"])})
        result = []
        for day in sorted(by_day):
            previous = db.execute(
                """SELECT close FROM candles JOIN instruments i ON i.id=candles.instrument_id
                   WHERE i.broker='FYERS' AND i.symbol=? AND candles.resolution='1'
                   AND timestamp < ? ORDER BY timestamp DESC LIMIT 1""",
                (UNDERLYING_SYMBOL, by_day[day]["timestamp"]),
            ).fetchone()
            row = dict(by_day[day])
            row["previous_close"] = float(previous["close"]) if previous else None
            result.append(row)
    return result

def register_instrument(repository, symbol, expiry, instrument_type, strike, option_type):
    existing = repository.get_instrument("FYERS", symbol)
    if existing:
        return int(existing["id"])
    return repository.upsert_instrument({
        "broker": "FYERS", "exchange": "NSE", "segment": 10, "symbol": symbol,
        "broker_token": None, "security_id": None, "underlying": "NIFTY",
        "instrument_type": instrument_type, "expiry_date": expiry, "strike": strike,
        "option_type": option_type, "lot_size": None, "tick_size": 0.05,
        "currency": "INR", "is_active": 0,
    })

def main():
    parser = argparse.ArgumentParser(description="Build targeted FYERS HFT 10S manifest.")
    parser.add_argument("--from", dest="start", required=True)
    parser.add_argument("--to", dest="end", required=True)
    parser.add_argument("--output", default="data/reports/hft_10s_manifest.csv")
    parser.add_argument("--json", default="data/reports/hft_10s_manifest_summary.json")
    args = parser.parse_args()

    days = load_daily_open_rows(args.start, args.end)
    if not days:
        raise SystemExit("No NIFTY 1m trading-day opens found in the requested range.")

    client = FyersClient()
    start = date.fromisoformat(days[0]["trade_date"])
    end = date.fromisoformat(days[-1]["trade_date"])
    futures_expiries, option_expiries = discover_expiry_dates(client, start, end)
    cache = {}

    def contracts_for(expiry):
        key = expiry.isoformat()
        if key not in cache:
            cache[key] = client.expired_contracts(UNDERLYING_SYMBOL, key)
        return cache[key]

    manifest, missing = [], []
    repository = DatabaseRepository(DATABASE_PATH)

    for day in days:
        trade_date = date.fromisoformat(day["trade_date"])
        option_expiry = nearest_expiry(trade_date, option_expiries)
        future_expiry = nearest_expiry(trade_date, futures_expiries)
        if option_expiry is None:
            missing.append({"trade_date": day["trade_date"], "reason": "NO_OPTION_EXPIRY"})
            continue
        if future_expiry is None:
            missing.append({"trade_date": day["trade_date"], "reason": "NO_FUTURES_EXPIRY"})
            continue

        atm_strike = atm(day["open"])
        offsets = {"CE": HFT_STRIKE_OFFSETS, "PE": HFT_PE_STRIKE_OFFSETS}
        required = {(atm_strike + offset, option_type)
                    for option_type in HFT_OPTION_TYPES for offset in offsets[option_type]}
        option_symbols = find_option_symbols(contracts_for(option_expiry), option_expiry, required)
        future_symbol = find_nearest_future_symbol(contracts_for(future_expiry))

        if future_symbol:
            iid = register_instrument(repository, future_symbol, future_expiry.isoformat(), 11, None, "XX")
            manifest.append({"kind": "FUTURES", "trade_date": day["trade_date"], "timestamp": day["timestamp"],
                             "symbol": future_symbol, "expiry_date": future_expiry.isoformat(), "instrument_id": iid})
        else:
            missing.append({"trade_date": day["trade_date"], "reason": "NO_FUTURES_SYMBOL",
                            "expiry_date": future_expiry.isoformat()})

        for strike, option_type in sorted(required):
            symbol = option_symbols.get((strike, option_type))
            if not symbol:
                missing.append({"trade_date": day["trade_date"], "reason": "NO_OPTION_SYMBOL",
                                "expiry_date": option_expiry.isoformat(), "strike": strike,
                                "option_type": option_type, "atm_strike": atm_strike})
                continue
            iid = register_instrument(repository, symbol, option_expiry.isoformat(), 14, strike, option_type)
            manifest.append({"kind": "OPTION", "trade_date": day["trade_date"], "timestamp": day["timestamp"],
                             "symbol": symbol, "expiry_date": option_expiry.isoformat(), "strike": strike,
                             "option_type": option_type, "atm_strike": atm_strike, "offset": strike - atm_strike,
                             "instrument_id": iid})

        iid = register_instrument(repository, UNDERLYING_SYMBOL, "", 1, None, "XX")
        manifest.append({"kind": "INDEX", "trade_date": day["trade_date"], "timestamp": day["timestamp"],
                         "symbol": UNDERLYING_SYMBOL, "expiry_date": "", "instrument_id": iid,
                         "previous_close": day["previous_close"], "nifty_open": day["open"]})

    manifest.sort(key=lambda x: (x["trade_date"], x["kind"], x["symbol"]))
    out = Path(args.output); out.parent.mkdir(parents=True, exist_ok=True)
    fields = sorted({key for row in manifest for key in row})
    with out.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields); writer.writeheader(); writer.writerows(manifest)

    summary = {
        "from": args.start, "to": args.end, "resolution": HFT_RESOLUTION, "fetch_resolution": "5S",
        "nifty_1m_trading_days": len(days), "manifest_rows": len(manifest),
        "index_days": len({r["trade_date"] for r in manifest if r["kind"] == "INDEX"}),
        "option_contract_days": len({(r["symbol"], r["trade_date"]) for r in manifest if r["kind"] == "OPTION"}),
        "unique_option_symbols": len({r["symbol"] for r in manifest if r["kind"] == "OPTION"}),
        "future_contract_days": len({(r["symbol"], r["trade_date"]) for r in manifest if r["kind"] == "FUTURES"}),
        "unique_future_symbols": len({r["symbol"] for r in manifest if r["kind"] == "FUTURES"}),
        "missing_rows": len(missing), "missing_examples": missing[:100],
        "generated_at": datetime.now().isoformat(),
    }
    Path(args.json).parent.mkdir(parents=True, exist_ok=True)
    Path(args.json).write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    print(f"Manifest: {out}")

if __name__ == "__main__":
    main()
