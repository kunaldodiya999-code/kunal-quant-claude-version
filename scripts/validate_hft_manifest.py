"""Validate the targeted HFT 10S manifest before any bulk acquisition."""
from __future__ import annotations
import argparse, csv, json
from collections import defaultdict
from pathlib import Path

def validate(path: str) -> dict:
    with open(path, newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    by_day = defaultdict(list)
    for row in rows:
        by_day[row["trade_date"]].append(row)
    errors = []
    if not rows:
        errors.append({"reason": "EMPTY_MANIFEST"})
    for day, day_rows in sorted(by_day.items()):
        options = [r for r in day_rows if r["kind"] == "OPTION"]
        futures = [r for r in day_rows if r["kind"] == "FUTURES"]
        index = [r for r in day_rows if r["kind"] == "INDEX"]
        option_keys = {(r["strike"], r["option_type"]) for r in options}
        atm_values = {r.get("atm_strike", "").strip() for r in options if r.get("atm_strike", "").strip()}
        if len(atm_values) != 1:
            errors.append({
                "trade_date": day,
                "reason": "ATM_STRIKE_MISSING_OR_INCONSISTENT",
                "atm_values": sorted(atm_values),
            })
            continue
        atm_strike = int(next(iter(atm_values)))
        expected = {(str(atm_strike + offset), typ)
                    for offset in (0, 50, 100, 150, 200, 250)
                    for typ in ("CE", "PE")}
        if len(options) != 12 or option_keys != expected:
            errors.append({"trade_date": day, "reason": "OPTION_LADDER_NOT_EXACTLY_12",
                           "actual_count": len(options), "missing_or_extra": sorted(expected ^ option_keys)})
        if len(futures) != 1:
            errors.append({"trade_date": day, "reason": "FUTURES_COUNT", "count": len(futures)})
        if len(index) != 1:
            errors.append({"trade_date": day, "reason": "INDEX_COUNT", "count": len(index)})
    return {
        "manifest": path, "trading_days": len(by_day),
        "option_rows": sum(1 for r in rows if r["kind"] == "OPTION"),
        "futures_rows": sum(1 for r in rows if r["kind"] == "FUTURES"),
        "index_rows": sum(1 for r in rows if r["kind"] == "INDEX"),
        "errors": len(errors), "error_examples": errors[:100], "valid": not errors,
    }

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--json", default="data/reports/hft_10s_manifest_validation.json")
    args = parser.parse_args()
    result = validate(args.manifest)
    Path(args.json).parent.mkdir(parents=True, exist_ok=True)
    Path(args.json).write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result["valid"] else 1)

if __name__ == "__main__":
    main()
