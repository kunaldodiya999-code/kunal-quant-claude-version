from pathlib import Path
import csv
from scripts.validate_hft_manifest import validate

def test_manifest_validator_accepts_exact_day(tmp_path: Path):
    path = tmp_path / "manifest.csv"
    fields = ["trade_date", "kind", "strike", "option_type", "atm_strike"]
    rows = []
    for offset in (0, 50, 100, 150, 200, 250):
        for option_type in ("CE", "PE"):
            rows.append({"trade_date": "2026-08-21", "kind": "OPTION",
                          "strike": str(25000 + offset), "option_type": option_type, "atm_strike": "25000"})
    rows += [
        {"trade_date": "2026-08-21", "kind": "FUTURES", "strike": "", "option_type": "", "atm_strike": ""},
        {"trade_date": "2026-08-21", "kind": "INDEX", "strike": "", "option_type": "", "atm_strike": ""},
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    result = validate(str(path))
    assert result["valid"]
    assert result["errors"] == 0

def test_manifest_validator_ignores_non_option_rows_for_atm(tmp_path: Path):
    path = tmp_path / "manifest.csv"
    fields = ["trade_date", "kind", "strike", "option_type", "atm_strike"]
    rows = []
    for offset in (0, 50, 100, 150, 200, 250):
        for option_type in ("CE", "PE"):
            rows.append({"trade_date": "2026-08-21", "kind": "OPTION",
                         "strike": str(25000 + offset), "option_type": option_type, "atm_strike": "25000"})
    rows += [
        {"trade_date": "2026-08-21", "kind": "FUTURES", "strike": "", "option_type": "", "atm_strike": ""},
        {"trade_date": "2026-08-21", "kind": "INDEX", "strike": "", "option_type": "", "atm_strike": ""},
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    result = validate(str(path))
    assert result["valid"]
