"""The REAL-MONEY switch for broker orders. OFF by default, ON for one day only.

Run from C:\\Users\\USER\\Desktop\\Kunal\\kunal-quant-claude-version :

    python scripts\\live_switch.py status     (is it on today?)
    python scripts\\live_switch.py arm        (turn ON for today only; asks you to type a sentence)
    python scripts\\live_switch.py disarm     (turn OFF now)

Even when armed, real orders are sent only if the trading program is started
with:  python scripts\\run_paper_session.py --live-orders
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from live_trading.switch import CONFIRM_PHRASE, LiveSwitch  # noqa: E402

IST = ZoneInfo("Asia/Kolkata")


def main(argv=None, *, ask=input) -> int:
    p = argparse.ArgumentParser(description="Real-money switch for broker orders.")
    p.add_argument("action", choices=("status", "arm", "disarm"))
    p.add_argument("--folder", type=Path, default=PROJECT_ROOT / "data" / "live_trading")
    args = p.parse_args(argv)
    switch = LiveSwitch(args.folder)
    today = datetime.now(IST).date()

    if args.action == "arm":
        print("You are about to allow REAL orders with REAL money on FYERS for today only")
        print(f"({today:%a %d %b %Y}). Limit orders only, never market orders.")
        print(f"To confirm, type exactly:  {CONFIRM_PHRASE}")
        try:
            switch.arm(today, ask("> "))
        except ValueError as exc:
            print(exc)
            return 1
        print("ARMED for today. Start the program with --live-orders to actually send orders.")
    elif args.action == "disarm":
        switch.disarm()
        print("OFF. No real orders will be sent.")
    print(f"Live switch today: {'ON (armed)' if switch.armed_for(today) else 'OFF'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
