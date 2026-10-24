"""Resumable FYERS fixed-expiry NIFTY options historical downloader.

This acquisition layer preserves exact expired-contract identity. It does not alter
strategy, contract-resolution, risk, execution, or accounting logic.

Default mode is PLAN ONLY. Add --execute to call FYERS.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
from datetime import date, timedelta
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from api.fyers_client import FyersClient  # noqa: E402

UNDERLYING = "NSE:NIFTY50-INDEX"
REQUIRED_COLUMNS = (
    "timestamp", "open", "high", "low", "close", "volume",
    "open_interest", "implied_volatility", "delta", "gamma", "theta", "vega",
)
EXPIRY_WINDOW_DAYS = 365
DEFAULT_RESOLUTION = "5"


def default_dates() -> tuple[str, str]:
    end = date.today()
    start = end - timedelta(days=365)
    return start.isoformat(), end.isoformat()


def build_expiry_windows(from_date: str, to_date: str, max_days: int = EXPIRY_WINDOW_DAYS) -> list[tuple[str, str]]:
    start = date.fromisoformat(from_date)
    end = date.fromisoformat(to_date)
    if end <= start:
        raise ValueError("to-date-exclusive must be later than from-date.")
    if max_days < 1 or max_days > 366:
        raise ValueError("max_days must be between 1 and 366.")
    windows: list[tuple[str, str]] = []
    current = start
    while current < end:
        nxt = min(current + timedelta(days=max_days), end)
        windows.append((current.isoformat(), nxt.isoformat()))
        current = nxt
    return windows


def _walk(value: Any):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)


def extract_expiry_dates(response: dict[str, Any]) -> list[str]:
    found: set[str] = set()

    def collect(value: Any, expiry_context: bool = False) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                collect(child, expiry_context or "expiry" in key.lower())
        elif isinstance(value, list):
            for child in value:
                collect(child, expiry_context)
        elif expiry_context and isinstance(value, str):
            match = re.search(r"\b(20\d{2}-\d{2}-\d{2})\b", value)
            if match:
                try:
                    found.add(date.fromisoformat(match.group(1)).isoformat())
                except ValueError:
                    pass

    collect(response)
    return sorted(found)


def _parse_symbol(symbol: str) -> tuple[float | None, str | None]:
    match = re.search(r"(CE|PE)$", symbol)
    if not match:
        return None, None
    side = match.group(1)
    strike_match = re.search(r"NIFTY(?:\d{2}[A-Z]\d{2}|\d{5})(\d+)(?:CE|PE)$", symbol)
    if not strike_match:
        return None, side
    try:
        return float(strike_match.group(1)), side
    except ValueError:
        return None, side


def extract_contracts(response: dict[str, Any]) -> list[dict[str, Any]]:
    found: dict[str, dict[str, Any]] = {}

    def add_symbol(symbol: str, raw_strike: Any = None) -> None:
        side_match = re.search(r"(CE|PE)$", symbol)
        if not side_match:
            return
        side = side_match.group(1)
        if raw_strike is None:
            parsed_strike, parsed_side = _parse_symbol(symbol)
            raw_strike = parsed_strike
            side = parsed_side or side
        try:
            strike = float(raw_strike)
        except (TypeError, ValueError):
            return
        found[symbol] = {"symbol": symbol, "strike": strike, "side": side}

    def collect(value: Any) -> None:
        if isinstance(value, dict):
            symbol = None
            for key in ("symbol", "trading_symbol", "tradingSymbol", "name"):
                candidate = value.get(key)
                if isinstance(candidate, str) and re.search(r"(CE|PE)$", candidate):
                    symbol = candidate
                    break
            if symbol:
                raw_strike = value.get("strike", value.get("strike_price", value.get("strikePrice")))
                add_symbol(symbol, raw_strike)
            for child in value.values():
                collect(child)
        elif isinstance(value, list):
            for child in value:
                collect(child)
        elif isinstance(value, str) and re.search(r"(CE|PE)$", value):
            add_symbol(value)

    collect(response)
    return sorted(found.values(), key=lambda x: (x["strike"], x["symbol"]))


def cached_catalog_is_valid(cached_catalog: Any, catalog_response_path: Path) -> bool:
    """Return True only when a cached catalog contains a non-empty contract set."""
    if not isinstance(cached_catalog, dict) or not catalog_response_path.exists():
        return False
    contracts = cached_catalog.get("contracts")
    contract_count = cached_catalog.get("contract_count")
    if not isinstance(contracts, list) or not contracts:
        return False
    if not isinstance(contract_count, int) or contract_count <= 0:
        return False
    return len(contracts) == contract_count


def select_contracts(
    contracts: list[dict[str, Any]],
    strike_min: float | None,
    strike_max: float | None,
    side: str | None,
    symbols: list[str] | None = None,
) -> list[dict[str, Any]]:
    if strike_min is not None and strike_max is not None and strike_min > strike_max:
        raise ValueError("strike-min cannot be greater than strike-max.")
    symbol_set = set(symbols) if symbols else None
    selected = []
    for contract in contracts:
        if symbol_set is not None and contract["symbol"] not in symbol_set:
            continue
        if strike_min is not None and contract["strike"] < strike_min:
            continue
        if strike_max is not None and contract["strike"] > strike_max:
            continue
        if side is not None and contract["side"] != side:
            continue
        selected.append(contract)
    return selected


def extract_candles(response: dict[str, Any]) -> list[list[Any]]:
    candles = response.get("candles")
    if isinstance(candles, list):
        return candles
    data = response.get("data")
    if isinstance(data, dict) and isinstance(data.get("candles"), list):
        return data["candles"]
    return []


def response_columns(response: dict[str, Any]) -> list[str]:
    candidates = [response.get("columns")]
    data = response.get("data")
    if isinstance(data, dict):
        candidates.append(data.get("columns"))
    for value in candidates:
        if isinstance(value, list) and all(isinstance(x, str) for x in value):
            return value
    return []


def is_no_data_response(response: dict[str, Any]) -> bool:
    """Return True when FYERS explicitly reports that no candles exist."""
    return isinstance(response, dict) and response.get("s") == "no_data"


def validate_response_shape(response: dict[str, Any]) -> None:
    if response.get("s") != "ok":
        raise ValueError(f"FYERS response is not successful: {response.get('s')!r}")
    columns = response_columns(response)
    missing = [name for name in REQUIRED_COLUMNS if name not in columns]
    if missing:
        raise ValueError(f"FYERS response is missing required columns: {missing}")
    candles = extract_candles(response)
    for index, candle in enumerate(candles):
        if not isinstance(candle, (list, tuple)) or len(candle) != len(columns):
            raise ValueError(
                f"candle {index} has width {len(candle) if isinstance(candle, (list, tuple)) else 'invalid'}; "
                f"expected {len(columns)}"
            )


def normalize_candles(response: dict[str, Any], contract: dict[str, Any], expiry_date: str) -> list[dict[str, Any]]:
    validate_response_shape(response)
    columns = response_columns(response)
    rows = []
    for candle in extract_candles(response):
        mapped = dict(zip(columns, candle))
        mapped.update({
            "symbol": contract["symbol"],
            "expiry_date": expiry_date,
            "strike": contract["strike"],
            "side": contract["side"],
        })
        rows.append(mapped)
    return rows


def inspect_quality(response: dict[str, Any]) -> dict[str, Any]:
    columns = response_columns(response)
    candles = extract_candles(response)
    timestamps = []
    widths = []
    invalid_rows = 0
    for candle in candles:
        if not isinstance(candle, (list, tuple)) or not candle:
            invalid_rows += 1
            continue
        widths.append(len(candle))
        try:
            timestamps.append(int(float(candle[0])))
        except (TypeError, ValueError):
            invalid_rows += 1
    duplicates = sum(1 for a, b in zip(timestamps, timestamps[1:]) if a == b)
    non_monotonic = sum(1 for a, b in zip(timestamps, timestamps[1:]) if b <= a and b != a)
    return {
        "rows": len(candles), "columns": columns, "distinct_widths": sorted(set(widths)),
        "invalid_rows": invalid_rows, "duplicate_timestamps": duplicates,
        "non_monotonic_timestamps": non_monotonic,
        "first_timestamp": min(timestamps) if timestamps else None,
        "last_timestamp": max(timestamps) if timestamps else None,
    }


def safe_name(symbol: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", symbol)
    digest = hashlib.sha1(symbol.encode("utf-8")).hexdigest()[:10]
    return f"{cleaned}_{digest}"


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")


def main() -> int:
    default_from, default_to = default_dates()
    parser = argparse.ArgumentParser(description="Plan or resumably download FYERS fixed-expiry NIFTY options history.")
    parser.add_argument("--from-date", default=default_from, help="YYYY-MM-DD inclusive")
    parser.add_argument("--to-date-exclusive", default=default_to, help="YYYY-MM-DD exclusive")
    parser.add_argument("--expiry-date", help="Download/catalog only this expiry; useful for a bounded pilot.")
    parser.add_argument("--resolution", choices=("1", "3", "5", "10", "15"), default=DEFAULT_RESOLUTION)
    parser.add_argument("--strike-min", type=float)
    parser.add_argument("--strike-max", type=float)
    parser.add_argument("--side", choices=("CE", "PE"))
    parser.add_argument("--symbol", action="append", help="Exact FYERS option symbol; repeat for multiple contracts.")
    parser.add_argument("--delay", type=float, default=0.30)
    parser.add_argument("--output-dir", type=Path, default=PROJECT_ROOT / "data" / "raw" / "fyers_expired_options")
    parser.add_argument("--execute", action="store_true", help="Actually call FYERS; without this, only prints the plan.")
    args = parser.parse_args()

    if args.expiry_date:
        expiry = date.fromisoformat(args.expiry_date)
        start = date.fromisoformat(args.from_date)
        end = date.fromisoformat(args.to_date_exclusive)
        if not start <= expiry < end:
            raise ValueError("--expiry-date must fall inside [from-date, to-date-exclusive).")

    windows = build_expiry_windows(args.from_date, args.to_date_exclusive)
    filter_config = {
        "strike_min": args.strike_min,
        "strike_max": args.strike_max,
        "side": args.side,
        "symbols": args.symbol,
    }

    print("=" * 80)
    print("KUNAL QUANT — FYERS FIXED-EXPIRY OPTIONS HISTORY")
    print("=" * 80)
    print(f"Period (end exclusive): {args.from_date} -> {args.to_date_exclusive}")
    print(f"Resolution: {args.resolution} minute")
    print(f"Discovery windows: {len(windows)} (<=366 days each)")
    print(f"Explicit filters: {filter_config}")
    print("Contract identity: exact FYERS symbol; no rolling/ATM-relative substitution")
    if not args.execute:
        print("PLAN ONLY: no API calls and no files written.")
        if args.expiry_date:
            print(f"Pilot expiry: {args.expiry_date}")
        else:
            for index, window in enumerate(windows, 1):
                print(f"  discovery {index:02d}: {window[0]} -> {window[1]}")
        print("Add --execute to run/resume the acquisition.")
        return 0

    client = FyersClient()
    run_name = f"nifty_{args.from_date}_{args.to_date_exclusive}_{args.resolution}m"
    run_dir = args.output_dir / run_name
    catalog_dir = run_dir / "catalogs"
    response_dir = run_dir / "responses"
    normalized_dir = run_dir / "normalized"
    manifest_path = run_dir / "manifest.json"
    run_dir.mkdir(parents=True, exist_ok=True)

    manifest = {}
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        expected_config = {
            "from_date": args.from_date, "to_date_exclusive": args.to_date_exclusive,
            "resolution": args.resolution, "filter": filter_config, "underlying": UNDERLYING,
        }
        if manifest.get("configuration") != expected_config:
            raise RuntimeError("Existing manifest configuration differs; use a new output directory.")
    else:
        manifest = {
            "configuration": {
                "from_date": args.from_date, "to_date_exclusive": args.to_date_exclusive,
                "resolution": args.resolution, "filter": filter_config, "underlying": UNDERLYING,
            },
            "read_only": True, "database_writes": False, "orders_placed": False,
            "expiry_discovery": {}, "contracts": {}, "history_requests": {},
        }
        write_json(manifest_path, manifest)

    if args.expiry_date:
        expiry_dates = [args.expiry_date]
    else:
        expiry_dates = []
        for index, (range_from, range_to) in enumerate(windows, 1):
            key = f"{range_from}_{range_to}"
            cached = manifest["expiry_discovery"].get(key)
            response_path = catalog_dir / f"expiry_dates_{key}.json"
            if cached and response_path.exists():
                dates = cached["dates"]
            else:
                response = client.expired_expiry_dates(UNDERLYING, range_from, range_to, "1")
                write_json(response_path, response)
                dates = extract_expiry_dates(response)
                manifest["expiry_discovery"][key] = {
                    "from": range_from, "to": range_to, "dates": dates,
                    "response_file": str(response_path.relative_to(run_dir)),
                }
                write_json(manifest_path, manifest)
            expiry_dates.extend(dates)
            print(f"Discovery {index}/{len(windows)}: {range_from} -> {range_to}: {len(dates)} expiries")
        expiry_dates = sorted({d for d in expiry_dates if args.from_date <= d < args.to_date_exclusive})

    if not expiry_dates:
        raise RuntimeError("No expiry dates were discovered in the requested period.")

    total_catalog_contracts = 0
    total_selected_contracts = 0
    total_history_requests = 0
    total_no_data = 0
    for expiry_index, expiry_date in enumerate(expiry_dates, 1):
        catalog_response_path = catalog_dir / f"contracts_{expiry_date}.json"
        cached_catalog = manifest["contracts"].get(expiry_date)
        if cached_catalog_is_valid(cached_catalog, catalog_response_path):
            contracts = cached_catalog["contracts"]
        else:
            response = client.expired_contracts(UNDERLYING, expiry_date)
            write_json(catalog_response_path, response)
            contracts = extract_contracts(response)
            manifest["contracts"][expiry_date] = {
                "contract_count": len(contracts), "contracts": contracts,
                "response_file": str(catalog_response_path.relative_to(run_dir)),
            }
            write_json(manifest_path, manifest)

        selected = select_contracts(contracts, args.strike_min, args.strike_max, args.side, args.symbol)
        total_catalog_contracts += len(contracts)
        total_selected_contracts += len(selected)
        print(f"Expiry {expiry_index}/{len(expiry_dates)} {expiry_date}: {len(contracts)} contracts; {len(selected)} selected")

        for contract_index, contract in enumerate(selected, 1):
            symbol = contract["symbol"]
            key = f"{expiry_date}:{symbol}:{args.resolution}"
            existing = manifest["history_requests"].get(key, {})
            stem = f"{expiry_date}_{safe_name(symbol)}"
            raw_path = response_dir / f"{stem}.json"
            normalized_path = normalized_dir / expiry_date / f"{safe_name(symbol)}.jsonl"

            if existing.get("status") == "ok" and raw_path.exists() and normalized_path.exists():
                total_history_requests += 1
                continue

            try:
                response = client.expired_history(
                    symbol=symbol, resolution=args.resolution, range_from=args.from_date,
                    range_to=expiry_date, include_oi="1", include_greeks="1", date_format="1",
                )
                if is_no_data_response(response):
                    write_json(raw_path, response)
                    manifest["history_requests"][key] = {
                        "status": "no_data", "symbol": symbol, "expiry_date": expiry_date,
                        "raw_response": str(raw_path.relative_to(run_dir)),
                    }
                    write_json(manifest_path, manifest)
                    total_no_data += 1
                    total_history_requests += 1
                    print(f"  no_data {contract_index}/{len(selected)}: {symbol}")
                    if args.delay > 0:
                        time.sleep(args.delay)
                    continue
                quality = inspect_quality(response)
                validate_response_shape(response)
                rows = normalize_candles(response, contract, expiry_date)
            except Exception as exc:
                manifest["history_requests"][key] = {
                    "status": "error", "symbol": symbol, "expiry_date": expiry_date, "error": str(exc),
                }
                write_json(manifest_path, manifest)
                print(f"STOPPED at {expiry_date} {symbol}: {exc}")
                print(f"Rerun the same command to resume. Manifest: {manifest_path}")
                return 1

            write_json(raw_path, response)
            write_jsonl(normalized_path, rows)
            manifest["history_requests"][key] = {
                "status": "ok", "symbol": symbol, "expiry_date": expiry_date, "rows": len(rows),
                "quality": quality, "raw_response": str(raw_path.relative_to(run_dir)),
                "normalized": str(normalized_path.relative_to(run_dir)),
            }
            write_json(manifest_path, manifest)
            total_history_requests += 1

            if contract_index == 1 or contract_index % 25 == 0 or contract_index == len(selected):
                print(f"  history {contract_index}/{len(selected)}: {symbol} -> {len(rows)} candles")
            if args.delay > 0:
                time.sleep(args.delay)

    manifest["finished"] = True
    manifest["summary"] = {
        "expiries": len(expiry_dates), "catalog_contracts": total_catalog_contracts,
        "selected_contracts": total_selected_contracts,
        "history_requests_completed_this_run": total_history_requests,
        "history_requests_no_data": total_no_data,
    }
    write_json(manifest_path, manifest)
    print("-" * 80)
    print("FINISHED")
    print(f"Expiries: {len(expiry_dates)}")
    print(f"Catalog contracts: {total_catalog_contracts}")
    print(f"Selected contracts: {total_selected_contracts}")
    print(f"History requests completed/reused: {total_history_requests}")
    print(f"History requests with no_data: {total_no_data}")
    print(f"Run directory: {run_dir}")
    print("No database writes or orders were performed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
