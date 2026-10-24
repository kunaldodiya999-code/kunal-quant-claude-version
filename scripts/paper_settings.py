"""Show or change the paper-trading strategy settings.

Run from C:\\Users\\USER\\Desktop\\Kunal\\kunal-quant-claude-version :

    python scripts\\paper_settings.py                        (show current settings)
    python scripts\\paper_settings.py --timeframe 5          (use 5-minute candles)
    python scripts\\paper_settings.py --direction LONG       (only BUY CALL trades)
    python scripts\\paper_settings.py --start 09:30 --end 15:00

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
from paper_trading.strategy_settings import StrategySettings, StrategySettingsStore

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
    p.add_argument("--folder", type=Path, default=PROJECT_ROOT / "data" / "paper_trading",
                   help="paper-trading data folder (default: data\\paper_trading)")
    return p


def show(settings: StrategySettings, path: Path | None) -> None:
    print("=" * 64)
    print("KUNAL QUANT - PAPER STRATEGY SETTINGS (KTMI Uni Lite core)")
    print("=" * 64)
    print(f"Timeframe          : {settings.timeframe_minutes} minute candles")
    print(f"Trade direction    : {DIRECTION_TEXT[settings.trade_direction]}")
    print(f"New trades from    : {settings.entry_start} IST")
    print(f"No new trades from : {settings.entry_end} IST")
    print(f"Force exit at      : {settings.force_exit} IST")
    print("Entries happen only after the signal candle has CLOSED.")
    print(f"Saved in           : {path}")
    print("=" * 64)


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    store = StrategySettingsStore(StrategySettings(), journal_dir=args.folder)
    changes = {
        key: value
        for key, value in {
            "timeframe_minutes": args.timeframe,
            "trade_direction": args.direction,
            "entry_start": args.start,
            "entry_end": args.end,
            "force_exit": args.force_exit,
        }.items()
        if value is not None
    }
    if changes:
        try:
            store.update(**changes)
        except ValueError as exc:
            print(f"NOT SAVED: {exc}")
            return 1
        print("Saved.")
    show(store.settings, store.path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
