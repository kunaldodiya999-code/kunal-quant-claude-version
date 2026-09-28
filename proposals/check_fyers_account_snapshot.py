"""
Kunal Quant — Fyers Account Snapshot (READ-ONLY)

Answers, using your real FYERS account, without a FYERS MCP (none exists
-- see chat): available funds, current holdings, current open positions,
and today's trades (to work out realised P&L). Unrealised P&L is normally
inside the positions response itself.

THIS SCRIPT MAKES EXACTLY 5 API CALLS, ALL READ-ONLY. That is not a
comment you have to trust -- it is true by construction: the only FYERS
SDK methods referenced anywhere below are the five named right here.
Nothing else from fyers_apiv3 is imported or called.

    1. FyersClient.profile()    -- api/fyers_client.py, already in your repo
    2. FyersClient.funds()      -- already in your repo
    3. FyersClient.positions()  -- already in your repo
    4. client.model.holdings()  -- official SDK method, not yet wrapped
    5. client.model.tradebook() -- official SDK method, not yet wrapped

No place_order / modify_order / cancel_order / exit_positions / any
"create_smart_order*" method is referenced anywhere in this file.

Why holdings/tradebook go through `client.model` directly instead of a
new FyersClient method: adding methods to api/fyers_client.py means
editing the canonical repo, which is off-limits without your approval.
`client.model` is already a public attribute of your existing,
already-trusted FyersClient -- this script adds no new auth code at all.

Field names: Fyers doesn't publish one canonical schema I could verify
without a live account, so rather than guess field names and risk
printing something wrong, this prints the REAL response structure and
highlights every key that looks P&L-related (contains pnl/profit/p&l/
realised/unrealised, case-insensitive) so you can see the true field
names directly instead of trusting a guess.

Run from the KunalQuant repo root, with your usual venv active:
    python <path-to-this-file>\\check_fyers_account_snapshot.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # -> KunalQuant, if run in place
try:
    from api.fyers_client import FyersClient
except ImportError:
    print(
        "Could not import api.fyers_client.FyersClient.\n"
        "Run this with PYTHONPATH set to your KunalQuant repo root, e.g.:\n"
        '  $env:PYTHONPATH=(Get-Location).Path\n'
        "  python ..\\kunal-quant-claude-version\\proposals\\check_fyers_account_snapshot.py"
    )
    raise


PNL_HINT_WORDS = ("pnl", "p&l", "profit", "realised", "realized", "unrealised", "unrealized")


def _highlight(obj, path=""):
    """Yield 'path: value' for every dict key that looks P&L-related."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            key_lower = str(k).lower()
            here = f"{path}.{k}" if path else str(k)
            if any(w in key_lower for w in PNL_HINT_WORDS):
                yield f"{here} = {v!r}"
            yield from _highlight(v, here)
    elif isinstance(obj, list):
        for i, item in enumerate(obj[:3]):  # first 3 rows is enough to see the shape
            yield from _highlight(item, f"{path}[{i}]")


def section(title: str) -> None:
    print("\n" + "=" * 100)
    print(title)
    print("=" * 100)


def show(label: str, response: dict) -> None:
    print(f"\n--- {label}: raw response ---")
    print(json.dumps(response, indent=2, default=str)[:4000])
    hints = list(_highlight(response))
    if hints:
        print(f"\n--- {label}: fields that look P&L-related ---")
        for h in hints:
            print(" ", h)


def main() -> None:
    print("KUNAL QUANT — FYERS ACCOUNT SNAPSHOT (READ-ONLY TEST)")
    print("No order was placed, modified, cancelled, or squared off by this script.")

    client = FyersClient()

    section("1/5 — AUTHENTICATION CHECK (profile)")
    profile = client.profile()
    ok = str(profile.get("s", "")).lower() == "ok" or str(profile.get("code")) == "200"
    print(f"Authenticated: {'YES' if ok else 'UNCLEAR — see raw response below'}")
    show("profile", profile)

    section("2/5 — AVAILABLE FUNDS")
    show("funds", client.funds())

    section("3/5 — HOLDINGS")
    show("holdings", client.model.holdings())

    section("4/5 — OPEN POSITIONS (unrealised P&L is normally here)")
    show("positions", client.positions())

    section("5/5 — TODAY'S TRADES (for realised P&L)")
    show("tradebook", client.model.tradebook())

    section("DONE")
    print("Re-run with output redirected to a file if you want to send it back, e.g.:")
    print("  python check_fyers_account_snapshot.py > $HOME\\Desktop\\fyers_snapshot.txt")


if __name__ == "__main__":
    main()
