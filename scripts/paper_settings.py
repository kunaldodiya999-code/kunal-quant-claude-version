"""Show or change the paper-trading strategy settings.

Run from C:\\Users\\USER\\Desktop\\Kunal\\kunal-quant-claude-version :

    python scripts\\paper_settings.py                              (show settings of all 3 indexes)
    python scripts\\paper_settings.py --index NIFTY --timeframe 5  (NIFTY: 5-minute candles)
    python scripts\\paper_settings.py --index ALL --direction LONG (all indexes: only BUY CALL)
    python scripts\\paper_settings.py --index SENSEX --start 09:30 --end 15:00
    python scripts\\paper_settings.py --index BANKNIFTY --trade OFF  (watch BANK NIFTY, no trades)

Each index (NIFTY, BANKNIFTY, SENSEX) has its own settings.

Several options can be combined in one command. Changes apply the next time
the paper session starts. Nothing here places orders.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from paper_trading.market_data_pipeline import SUPPORTED_RESOLUTIONS
from paper_trading.strategy_settings import SETTINGS_FILE, StrategySettings, StrategySettingsStore
from strategies.index_profiles import INDEX_PROFILES, parse_index_list

DIRECTION_TEXT = {
    "LONG": "Long only  (BUY CALL when Long Speed crosses above +0.5)",
    "SHORT": "Short only (BUY PUT when Short Speed crosses above +0.5)",
    "BOTH": "Both long and short",
}


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Show or change paper-trading strategy settings.")
    p.add_argument("--timeframe", type=int, choices=SUPPORTED_RESOLUTIONS, help="candle size in minutes")
    p.add_argument("--direction", choices=("LONG", "SHORT", "BOTH"), type=str.upper,
                   help="LONG = calls only, SHORT = puts only, BOTH")
    p.add_argument("--start", help="first time a new trade may start, HH:MM (e.g. 09:30)")
    p.add_argument("--end", help="no new trades from this time, HH:MM (e.g. 15:00)")
    p.add_argument("--force-exit", dest="force_exit", help="close open trades at this time, HH:MM")
    p.add_argument("--trade", choices=("ON", "OFF"), type=str.upper,
                   help="ON = this index takes entries, OFF = watch only (same as the dashboard 'Trade in')")
    p.add_argument("--index", default="ALL", help="NIFTY, BANKNIFTY, SENSEX, a comma list, or ALL (default)")
    p.add_argument("--folder", type=Path, default=PROJECT_ROOT / "data" / "paper_trading",
                   help="paper-trading data folder (default: data\\paper_trading)")
    return p


def show(settings: StrategySettings, path: Path | None, label: str = "") -> None:
    print("=" * 64)
    print(f"KUNAL QUANT - {label} STRATEGY SETTINGS (KTMI Uni Lite core)")
    print("=" * 64)
    print(f"Timeframe          : {settings.timeframe_minutes} minute candles")
    print(f"Trade in           : {'ON (takes entries)' if settings.trading_enabled else 'OFF (watch only)'}")
    print(f"Trade direction    : {DIRECTION_TEXT[settings.trade_direction]}")
    print(f"New trades from    : {settings.entry_start} IST")
    print(f"No new trades from : {settings.entry_end} IST")
    print(f"Force exit at      : {settings.force_exit} IST")
    boxes = " + ".join(n for n, on in (("ATM", settings.use_atm), ("ATM+1", settings.use_atm_plus_1)) if on)
    print(f"Strikes            : {boxes + ' (checkboxes)' if boxes else f'CALL {settings.call_strike}, PUT {settings.put_strike} (dropdowns)'}")
    print("Entries happen only after the signal candle has CLOSED.")
    print(f"Saved in           : {path}")
    print("=" * 64)


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    keys = list(INDEX_PROFILES) if args.index.strip().upper() == "ALL" else [p.key for p in parse_index_list(args.index)]
    changes = {
        key: value
        for key, value in {
            "timeframe_minutes": args.timeframe,
            "trade_direction": args.direction,
            "entry_start": args.start,
            "entry_end": args.end,
            "force_exit": args.force_exit,
            "trading_enabled": None if args.trade is None else args.trade == "ON",
        }.items()
        if value is not None
    }
    legacy = args.folder / SETTINGS_FILE
    for key in keys:
        folder = args.folder / key
        if legacy.exists() and not (folder / SETTINGS_FILE).exists():   # carry the old single file over
            folder.mkdir(parents=True, exist_ok=True)
            (folder / SETTINGS_FILE).write_text(legacy.read_text(encoding="utf-8"), encoding="utf-8")
        store = StrategySettingsStore(StrategySettings(), journal_dir=folder)
        if changes:
            try:
                store.update(**changes)
            except ValueError as exc:
                print(f"NOT SAVED: {exc}")
                return 1
            print(f"Saved for {INDEX_PROFILES[key].label}.")
        show(store.settings, store.path, INDEX_PROFILES[key].label)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
