"""Arm (or disarm) REAL orders for TODAY only.

    python arm_real_orders.py            asks you to type the phrase, arms today
    python arm_real_orders.py --off      disarms
    python arm_real_orders.py --status   shows the state

Real orders also need the "Real orders" switch ON in the terminal's Settings tab. Tomorrow it is OFF again.
"""

import argparse
from datetime import datetime

from live_trading.switch import CONFIRM_PHRASE, LiveSwitch
from terminal.candles import IST
from terminal.fyers import data_dir


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--off", action="store_true")
    ap.add_argument("--status", action="store_true")
    a = ap.parse_args()
    switch, today = LiveSwitch(data_dir()), datetime.now(IST).date()
    if a.off:
        switch.disarm()
        print("Real orders: OFF.")
    elif a.status:
        print(f"Real orders armed for today ({today}): {'YES' if switch.armed_for(today) else 'NO'}")
    else:
        print(f"Type exactly:  {CONFIRM_PHRASE}")
        switch.arm(today, input("> "))
        print(f"Real orders ARMED for {today} only. Switch 'Real orders' ON in the terminal's Settings tab.")


if __name__ == "__main__":
    main()
