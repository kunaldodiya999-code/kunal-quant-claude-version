"""Bounded, read-only validation of FYERS expired NIFTY option history.

Uses at most 7 FYERS Data API requests:
  1 expiry-date discovery across the two-year target period
  2 contract lists (one old expiry, one recent expiry)
  4 historical samples (CE + PE at each expiry)
No order APIs, no SQLite writes, no credentials printed.

Run:
  python scripts/validate_fyers_expired_history.py
Optional:
  --old-target 2024-10-24 --recent-target 2026-09-15
  --resolution 5
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from api.fyers_client import FyersClient  # noqa: E402

UNDERLYING = "NSE:NIFTY50-INDEX"
START = "2024-10-12"
END = (date.today() - timedelta(days=1)).isoformat()  # FYERS rejects today/future as range_to


def walk(value: Any):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk(child)


def extract_dates(response: dict[str, Any]) -> list[str]:
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


def extract_contracts(response: dict[str, Any]) -> list[dict[str, Any]]:
    found: dict[str, dict[str, Any]] = {}

    def collect(value: Any) -> None:
        if isinstance(value, dict):
            symbol = next((str(value[k]) for k in ("symbol", "trading_symbol", "tradingSymbol", "name")
                           if isinstance(value.get(k), str) and re.search(r"(CE|PE)$", str(value[k]))), None)
            if symbol:
                side_match = re.search(r"(CE|PE)$", symbol)
                if side_match:
                    side = side_match.group(1)
                    raw_strike = value.get("strike", value.get("strike_price", value.get("strikePrice")))
                    if raw_strike is None:
                        # FYERS symbols concatenate expiry and strike. A naive trailing-number
                        # regex incorrectly turns 19200 into 2419200.
                        strike_match = re.search(
                            r"NIFTY(?:\d{2}[A-Z]\d{2}|\d{5})(\d+)(?:CE|PE)$",
                            symbol,
                        )
                        if strike_match:
                            raw_strike = strike_match.group(1)
                    try:
                        strike = float(raw_strike)
                    except (ValueError, TypeError):
                        strike = None
                    if strike is not None:
                        found[symbol] = {"symbol": symbol, "strike": strike, "side": side}
            for child in value.values():
                collect(child)
        elif isinstance(value, list):
            for child in value:
                collect(child)
        elif isinstance(value, str) and re.search(r"(CE|PE)$", value):
            side_match = re.search(r"(CE|PE)$", value)
            strike_match = re.search(
                r"NIFTY(?:\d{2}[A-Z]\d{2}|\d{5})(\d+)(?:CE|PE)$",
                value,
            )
            if side_match and strike_match:
                found[value] = {
                    "symbol": value,
                    "strike": float(strike_match.group(1)),
                    "side": side_match.group(1),
                }

    collect(response)
    return sorted(found.values(), key=lambda c: (c["side"], c["strike"], c["symbol"]))


def extract_candles(response: dict[str, Any]) -> list:
    candles = response.get("candles")
    if isinstance(candles, list):
        return candles
    data = response.get("data")
    if isinstance(data, dict) and isinstance(data.get("candles"), list):
        return data["candles"]
    return []


def _response_columns(response: dict[str, Any]) -> list[str]:
    """Return candle column names when FYERS exposes them in the response."""
    candidates = [response.get("columns")]
    data = response.get("data")
    if isinstance(data, dict):
        candidates.append(data.get("columns"))
    for value in candidates:
        if isinstance(value, list) and all(isinstance(x, str) for x in value):
            return value
    return []


def _numeric_quality(candles: list, columns: list[str]) -> dict[str, Any]:
    """Inspect actual candle values without assuming a fixed FYERS column order."""
    timestamps: list[int] = []
    widths: list[int] = []
    duplicates = 0
    non_monotonic = 0
    gaps: list[int] = []
    invalid_rows = 0
    for candle in candles:
        if not isinstance(candle, (list, tuple)) or not candle:
            invalid_rows += 1
            continue
        widths.append(len(candle))
        try:
            timestamps.append(int(float(candle[0])))
        except (ValueError, TypeError):
            invalid_rows += 1

    for previous, current in zip(timestamps, timestamps[1:]):
        delta = current - previous
        if delta <= 0:
            if delta == 0:
                duplicates += 1
            else:
                non_monotonic += 1
        elif delta > 3600:
            gaps.append(delta)

    # Inspect named fields when FYERS provides columns. If columns are absent,
    # retain the raw width/sample as evidence rather than guessing field indexes.
    field_stats: dict[str, dict[str, Any]] = {}
    for idx, name in enumerate(columns):
        values = []
        for candle in candles:
            if isinstance(candle, (list, tuple)) and idx < len(candle):
                values.append(candle[idx])
        numeric = []
        for value in values:
            try:
                number = float(value)
                if number == number:  # not NaN
                    numeric.append(number)
            except (ValueError, TypeError):
                pass
        lname = name.lower()
        if any(token in lname for token in ("oi", "open_interest", "openinterest", "delta", "gamma", "theta", "vega", "iv", "implied")):
            field_stats[name] = {
                "present_values": len(numeric),
                "total_values": len(values),
                "missing_or_non_numeric": len(values) - len(numeric),
                "zero_values": sum(1 for x in numeric if x == 0),
                "min": min(numeric) if numeric else None,
                "max": max(numeric) if numeric else None,
            }

    return {
        "invalid_rows": invalid_rows,
        "duplicate_timestamps": duplicates,
        "non_monotonic_timestamps": non_monotonic,
        "gaps_over_60_minutes": len(gaps),
        "largest_gap_seconds": max(gaps) if gaps else 0,
        "distinct_candle_widths": sorted(set(widths)),
        "columns": columns,
        "field_stats": field_stats,
    }


def _session_completeness(candles: list, resolution_minutes: int = 5) -> dict[str, Any]:
    """Evaluate NSE Asia/Kolkata trading-session coverage without treating holidays as failures."""
    ist = ZoneInfo("Asia/Kolkata")
    session_open_minute = 9 * 60 + 15
    session_close_start = 15 * 60 + 25
    step = resolution_minutes * 60
    by_date: dict[str, list[int]] = {}
    invalid_timestamps = 0
    for candle in candles:
        if not isinstance(candle, (list, tuple)) or not candle:
            continue
        try:
            ts = int(float(candle[0]))
            local = datetime.fromtimestamp(ts, timezone.utc).astimezone(ist)
            by_date.setdefault(local.date().isoformat(), []).append(ts)
        except (ValueError, TypeError, OverflowError):
            invalid_timestamps += 1

    sessions = []
    for session_date, timestamps in sorted(by_date.items()):
        unique = sorted(set(timestamps))
        local_times = [datetime.fromtimestamp(ts, timezone.utc).astimezone(ist) for ts in unique]
        in_session = [x for x in local_times if session_open_minute <= x.hour * 60 + x.minute <= session_close_start and x.second == 0]
        expected = int(((session_close_start - session_open_minute) * 60) / step) + 1
        expected_set = {
            int(datetime.combine(date.fromisoformat(session_date), datetime.min.time(), tzinfo=ist).timestamp())
            + (session_open_minute * 60) + i * step
            for i in range(expected)
        }
        actual_set = {int(x.timestamp()) for x in in_session}
        missing = sorted(expected_set - actual_set)
        unexpected = sorted(actual_set - expected_set)
        sessions.append({
            "date": session_date,
            "candles_total": len(timestamps),
            "unique_timestamps": len(unique),
            "in_session_candles": len(in_session),
            "expected_full_session_candles": expected,
            "missing_expected_candles": len(missing),
            "first_ist": local_times[0].isoformat() if local_times else None,
            "last_ist": local_times[-1].isoformat() if local_times else None,
            "outside_session_candles": len(local_times) - len(in_session),
            "full_session": len(in_session) == expected and not missing,
            "partial_or_gap": bool(missing),
            "missing_first": datetime.fromtimestamp(missing[0], timezone.utc).astimezone(ist).isoformat() if missing else None,
            "unexpected_in_expected_window": len(unexpected),
        })

    full = [s for s in sessions if s["full_session"]]
    partial = [s for s in sessions if s["partial_or_gap"] or s["outside_session_candles"]]
    return {
        "timezone": "Asia/Kolkata",
        "session_window_ist": "09:15-15:25 candle starts",
        "resolution_minutes": resolution_minutes,
        "expected_full_session_candles": int(((session_close_start - session_open_minute) * 60) / step) + 1,
        "sessions_found": len(sessions),
        "full_sessions": len(full),
        "partial_or_gap_sessions": len(partial),
        "invalid_timestamps": invalid_timestamps,
        "sessions": sessions,
    }


def summarize_history(response: dict[str, Any], resolution_minutes: int = 5) -> dict[str, Any]:
    candles = extract_candles(response)
    keys = sorted(response.keys())
    if isinstance(response.get("data"), dict):
        keys += [f"data.{k}" for k in sorted(response["data"].keys())]
    timestamps = []
    widths = []
    for candle in candles:
        if isinstance(candle, (list, tuple)) and candle:
            widths.append(len(candle))
            try:
                timestamps.append(int(float(candle[0])))
            except (ValueError, TypeError):
                pass
    dt = [datetime.fromtimestamp(ts, timezone.utc).astimezone().isoformat() for ts in timestamps]
    columns = _response_columns(response)
    quality = _numeric_quality(candles, columns)
    session_quality = _session_completeness(candles, resolution_minutes)
    key_text = " ".join(keys).lower()
    schema_greek = any(word in key_text for word in ("greek", "delta", "gamma", "theta", "vega", "iv", "implied"))
    schema_oi = any(word in key_text for word in ("oi", "open_interest", "openinterest"))
    return {
        "status": response.get("s"),
        "message": response.get("message") or response.get("messageCode"),
        "top_level_keys": sorted(response.keys()),
        "data_keys": sorted(response.get("data", {}).keys()) if isinstance(response.get("data"), dict) else [],
        "candle_count": len(candles),
        "first_timestamp_utc": dt[0] if dt else None,
        "last_timestamp_utc": dt[-1] if dt else None,
        "distinct_candle_widths": sorted(set(widths)),
        "greek_or_iv_key_visible": schema_greek or any(k for k in quality["field_stats"] if k.lower() in ("delta", "gamma", "theta", "vega", "iv")),
        "oi_key_visible": schema_oi or any("oi" in k.lower() for k in quality["field_stats"]),
        "columns": columns,
        "sample_candle": candles[0] if candles else None,
        "value_quality": quality,
        "session_quality": session_quality,
        "raw_error": response.get("error") if response.get("s") == "error" else None,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate FYERS expired NIFTY options data without DB writes.")
    parser.add_argument("--old-target", default="2024-10-24")
    parser.add_argument("--recent-target", default="2026-09-15")
    parser.add_argument("--resolution", choices=["1", "3", "5", "10", "15"], default="5")
    parser.add_argument("--output", type=Path, default=PROJECT_ROOT / "data" / "raw" / "fyers_expired_audit" / "fyers_expired_validation.json")
    args = parser.parse_args()

    client = FyersClient()
    audit: dict[str, Any] = {
        "underlying": UNDERLYING,
        "target_period": {"from": START, "to": END},
        "resolution": args.resolution,
        "read_only": True,
        "database_writes": False,
        "orders_placed": False,
        "steps": [],
    }

    print("=" * 78)
    print("KUNAL QUANT — FYERS EXPIRED OPTIONS DATA VALIDATION")
    print("=" * 78)
    print(f"Target period : {START} to {END} (FYERS rejects today/future as range_to)")
    print(f"Resolution    : {args.resolution} minute")
    print("Request budget: maximum 8 API calls; no DB writes or orders")
    print("Step 1/3: discovering expiry dates...", flush=True)
    # FYERS limits expiry-date discovery to 366 days per request.
    # Use two adjacent windows so we can validate both an older and recent expiry.
    discovery_windows = [
        (START, "2025-10-12"),
        ("2025-10-13", END),
    ]
    expiry_dates: list[str] = []
    audit["expiry_discovery"] = {"windows": [], "requests": len(discovery_windows)}
    for range_from, range_to in discovery_windows:
        response = client.expired_expiry_dates(UNDERLYING, range_from, range_to, "1")
        dates = extract_dates(response)
        audit["expiry_discovery"]["windows"].append({
            "from": range_from,
            "to": range_to,
            "status": response.get("s"),
            "top_level_keys": sorted(response.keys()),
            "data_keys": sorted(response.get("data", {}).keys()) if isinstance(response.get("data"), dict) else [],
            "expiry_count_parsed": len(dates),
            "first_expiries": dates[:5],
            "last_expiries": dates[-5:],
            "response_sample": response if not dates else None,
        })
        if response.get("s") != "ok" or not dates:
            audit["verdict"] = f"BLOCKED: expiry discovery failed for {range_from}..{range_to}."
            return finish(audit, args.output, 2)
        expiry_dates.extend(dates)
    expiry_dates = sorted(set(expiry_dates))
    audit["expiry_discovery"]["expiry_count_parsed"] = len(expiry_dates)
    audit["expiry_discovery"]["first_expiries"] = expiry_dates[:5]
    audit["expiry_discovery"]["last_expiries"] = expiry_dates[-5:]
    audit["expiry_discovery"]["parsed_expiries"] = expiry_dates

    targets = [("old", args.old_target), ("recent", args.recent_target)]
    chosen: list[tuple[str, str]] = []
    for label, target in targets:
        valid = [d for d in expiry_dates if d <= target]
        if not valid:
            audit["verdict"] = f"BLOCKED: no expiry on or before {target}."
            return finish(audit, args.output, 2)
        chosen.append((label, valid[-1]))

    samples = []
    for label, expiry in chosen:
        print(f"Step 2/3: retrieving contracts for {label} expiry {expiry}...", flush=True)
        contracts_response = client.expired_contracts(UNDERLYING, expiry)
        contracts = extract_contracts(contracts_response)
        contract_summary = {
            "label": label,
            "requested_expiry": expiry,
            "status": contracts_response.get("s"),
            "top_level_keys": sorted(contracts_response.keys()),
            "data_keys": sorted(contracts_response.get("data", {}).keys()) if isinstance(contracts_response.get("data"), dict) else [],
            "contracts_parsed": len(contracts),
        }
        audit.setdefault("contract_discovery", []).append(contract_summary)
        if contracts_response.get("s") != "ok" or not contracts:
            audit["verdict"] = f"BLOCKED: no parseable contract symbols for {label} expiry {expiry}."
            audit.setdefault("contract_response_samples", []).append(contracts_response)
            return finish(audit, args.output, 2)

        target_strike = 24000 if label == "old" else 25000
        selected = []
        for side in ("CE", "PE"):
            side_contracts = [c for c in contracts if c["side"] == side]
            if side_contracts:
                selected.append(min(side_contracts, key=lambda c: (abs(c["strike"] - target_strike), c["strike"])))
        if len(selected) != 2:
            audit["verdict"] = f"BLOCKED: could not select both CE and PE for {expiry}."
            return finish(audit, args.output, 2)

        for contract in selected:
            # Keep the requested window narrow and inside the chosen contract's lifetime.
            range_to = expiry
            range_from = (date.fromisoformat(expiry).replace(day=1)).isoformat()
            print(f"Step 3/3: {label} {contract['symbol']} history {range_from}..{range_to} with OI+Greeks...", flush=True)
            response = client.expired_history(
                symbol=contract["symbol"],
                resolution=args.resolution,
                range_from=range_from,
                range_to=range_to,
                include_oi="1",
                include_greeks="1",
                date_format="1",
            )
            summary = {
                "label": label,
                "expiry": expiry,
                "contract": contract,
                "range_from": range_from,
                "range_to": range_to,
                **summarize_history(response, int(args.resolution)),
            }
            samples.append(summary)
            print(f"  status={summary['status']} candles={summary['candle_count']} widths={summary['distinct_candle_widths']} keys={summary['data_keys'] or summary['top_level_keys']}", flush=True)

    audit["historical_samples"] = samples
    audit["quality_checks"] = {
        "all_four_contract_samples_returned_candles": all(s["status"] == "ok" and s["candle_count"] > 0 for s in samples),
        "both_old_and_recent_periods_tested": {s["label"] for s in samples} == {"old", "recent"},
        "oi_or_greeks_visible_in_schema": any(s["oi_key_visible"] or s["greek_or_iv_key_visible"] for s in samples),
        "warning": "Non-empty candles do not prove every candle has valid OI/Greeks or that all sessions are complete. This is a feasibility gate, not full data-quality certification.",
    }
    if not audit["quality_checks"]["all_four_contract_samples_returned_candles"]:
        audit["verdict"] = "FAIL: one or more contract-history samples returned no candles or an API error."
        return finish(audit, args.output, 2)
    audit["verdict"] = "PASS: expired contract history returned for old and recent periods. Review payload schema/Greeks before bulk download; this is not yet a full coverage audit."
    return finish(audit, args.output, 0)


def finish(audit: dict[str, Any], output: Path, code: int) -> int:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(audit, indent=2, default=str), encoding="utf-8")
    print("-" * 78)
    print(f"VERDICT: {audit.get('verdict')}")
    print(f"Report : {output}")
    print("No credentials were printed. No database was modified. No orders were placed.")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
