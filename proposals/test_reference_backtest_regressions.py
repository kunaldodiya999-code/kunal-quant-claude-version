"""
Regression checks for proposals/generate_no_lookahead_reference_backtest.py
(review of commit 10a3664). Synthetic data only: no database, no network,
no writes, runs in about a second. The reference script itself is NOT
modified -- it is imported as-is, and the proposed fix is applied to an
in-memory copy of its source purely to show before/after.

    KUNAL_QUANT_REPO=/path/to/KunalQuant python3 proposals/test_reference_backtest_regressions.py

Exit code is non-zero while the reproduced bug is still present.
"""

from __future__ import annotations

import datetime
import os
import sys
import types
import zoneinfo
from pathlib import Path

REPO = os.environ.get("KUNAL_QUANT_REPO")
if not REPO:
    raise SystemExit("Set KUNAL_QUANT_REPO to a local KunalQuant clone first.")
sys.path.insert(0, REPO)
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from backtest.models import BacktestBar  # noqa: E402
from backtest.option_entry_bridge import OptionCandle  # noqa: E402
from backtest.option_trade_lifecycle import (  # noqa: E402
    OptionTradeDirection,
    OptionTradeLifecycle,
)
from strategies.ktmi_trigger_strategy import (  # noqa: E402
    KTMITriggerEvent,
    TriggerDirection,
    TriggerStrategyId,
)
from strategies.option_contract_resolver import ResolvedOptionContract  # noqa: E402

REF_PATH = HERE / "generate_no_lookahead_reference_backtest.py"
IST = zoneinfo.ZoneInfo("Asia/Kolkata")
DAY = datetime.date(2026, 9, 22)


def ts(h: int, m: int) -> int:
    return int(datetime.datetime(DAY.year, DAY.month, DAY.day, h, m, tzinfo=IST).timestamp())


# ---------------------------------------------------------------------
# synthetic scenario: two entries; the first is stopped out before the
# second signal arrives.
# ---------------------------------------------------------------------

def make_bars():
    # strong steady uptrend so KAMA stays below price -> no KAMA exit for LONGs
    return [
        BacktestBar(
            timestamp=ts(9, 15) + 180 * i,
            open=24000 + 5 * i, high=24006 + 5 * i, low=23999 + 5 * i, close=24005 + 5 * i,
        )
        for i in range(60)
    ]


def make_events():
    def ev(index, strategy):
        return KTMITriggerEvent(
            strategy_id=strategy, direction=TriggerDirection.LONG,
            previous_value=0.4, current_value=0.6, trigger_value=0.5,
            index=index, timestamp=ts(9, 15) + 180 * index,
        )
    return [ev(5, TriggerStrategyId.LONG_SHORT_SPEED), ev(20, TriggerStrategyId.MOMENTUM_ONLY)]


class StubResolver:
    def resolve(self, *, underlying_price, entry_date, direction):
        return ResolvedOptionContract(
            instrument_id=1, symbol="NSE:NIFTYTESTCE", underlying="NIFTY",
            expiry_date=DAY, strike=24000, option_type="CE",
        )


class StubLoader:
    """1-minute candles 09:15..15:29. Flat at 100, except a spike DOWN to
    79 at 09:50 (stops out a long entered at 100: stop is 80)."""

    def load(self, instrument_id, start, end):
        candles = []
        t = ts(9, 15)
        while t <= ts(15, 29):
            low = 79.0 if t == ts(9, 50) else 99.0
            candles.append(OptionCandle(timestamp=t, open=100.0, high=101.0, low=low, close=100.0))
            t += 60
        return candles


def load_reference(patched: bool):
    src = REF_PATH.read_text(encoding="utf-8")
    if patched:
        old = (
            "        active = [\n"
            "            state\n"
            "            for state in active\n"
            "            if not state.position.closed\n"
            "        ]\n"
        )
        new = (
            "        still_active = []\n"
            "        for state in active:\n"
            "            if state.position.closed:\n"
            "                closed.append(state.managed())\n"
            "            else:\n"
            "                still_active.append(state)\n"
            "        active = still_active\n"
        )
        assert old in src, "reference script changed; update this test's patch"
        src = src.replace(old, new, 1)
    mod = types.ModuleType("ref_patched" if patched else "ref_asis")
    mod.__file__ = str(REF_PATH)
    sys.modules[mod.__name__] = mod  # dataclasses (postponed annotations) needs this
    exec(compile(src, str(REF_PATH), "exec"), mod.__dict__)
    return mod


def run(mod):
    bars, events = make_bars(), make_events()
    result = mod.run_reference(bars=bars, events=events, loader=StubLoader(), resolver=StubResolver())
    c = result["counts"]
    accounted = sum(c[k] for k in (
        "closed", "open", "lifecycle_rejected", "allocation_rejected",
        "unresolved", "no_entry_candle", "outside_session"))
    return result, c, accounted, len(events)


def main() -> int:
    bad = 0
    print("=" * 78)
    print("REFERENCE BACKTEST REVIEW — synthetic regression checks")
    print("=" * 78)

    # ---- 1. dropped closed trades -------------------------------------
    print("\n[1] Trades that close BEFORE the last event boundary")
    print("    scenario: 2 events; trade #1 hits its stop at 09:50, well before")
    print("    event #2 arrives at 10:18. Correct accounting: closed=1, open=1.")

    result, c, accounted, n_events = run(load_reference(patched=False))
    ok = accounted == n_events and c["closed"] == 1
    print(f"    AS-IS  : closed={c['closed']} open={c['open']} -> accounted {accounted}/{n_events} events "
          f"=> {'PASS' if ok else 'BUG REPRODUCED'}")
    bad += 0 if ok else 1

    result, c, accounted, n_events = run(load_reference(patched=True))
    ok2 = accounted == n_events and c["closed"] == 1
    pnl = [float(t.result.total_pnl) for t in result["closed"]]
    print(f"    PATCHED: closed={c['closed']} open={c['open']} -> accounted {accounted}/{n_events} events "
          f"=> {'PASS' if ok2 else 'FAIL'}   closed trade P&L={pnl}")
    if not ok2:
        bad += 1

    # ---- 2. what the SHORT branch does to a bought put ------------------
    print("\n[2] INFORMATION ONLY — SHORT signal => PE, then OptionTradeDirection.SHORT")
    print("    A bearish signal buys a PE. Suppose the market falls and the PE")
    print("    premium RISES 100 -> 125 (good for someone who bought the put).")
    for label, direction in (("as coded (SHORT)", OptionTradeDirection.SHORT),
                             ("long-premium reading (LONG)", OptionTradeDirection.LONG)):
        mgr = OptionTradeLifecycle()
        pos = mgr.create_position(strategy_id="A", direction=direction, symbol="PE", entry_price=100.0)
        exits = mgr.process_candle(position=pos, timestamp=1, option_high=125.0, option_low=99.0,
                                   option_close=125.0, underlying_close=24000.0, kama_value=24100.0)
        e = [(x.reason.value, x.price, round(x.pnl, 2)) for x in exits]
        print(f"    {label:<30} stop={pos.stop_loss:>6.1f} target={pos.target:>6.1f} "
              f"qty={pos.quantity} -> {e or 'no exit'}  gross_pnl={pos.gross_pnl:,.2f}")

    print()
    if bad:
        print(f"{bad} check(s) show a reproduced bug — see docs/reviews/2026-09-28_reference_backtest_review.md")
        return 1
    print("All checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
