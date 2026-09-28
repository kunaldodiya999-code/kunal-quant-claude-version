"""
Proposal-only semantic tests for generate_reference_backtest_v2.py.

No database, network, or writes.

Checks:
- configurable trigger inputs are preserved;
- BUY PE is treated as a long-premium option position for stop/target;
- BUY PE uses bearish underlying direction for KAMA exit;
- BUY CE uses bullish underlying direction for KAMA exit.
"""

from __future__ import annotations

import argparse
import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from backtest.option_entry_bridge import OptionEntry
from backtest.option_trade_lifecycle import (
    OptionTradeDirection,
    OptionTradeLifecycle,
    OptionTradeExit,
    OptionExitReason,
)
from backtest.models import BacktestBar
from strategies.ktmi_trigger_strategy import (
    KTMITriggerEvent,
    TriggerDirection,
    TriggerStrategyId,
)

from generate_reference_backtest_v2 import (
    TradeState,
    build_trigger_config,
    process_buy_premium_candle,
)

IST = ZoneInfo("Asia/Kolkata")


def fake_args():
    return argparse.Namespace(
        disable_speed_sources=False,
        long_speed_ce_trigger=0.41,
        short_speed_pe_trigger=0.57,
        disable_momentum=False,
        momentum_ce_trigger=0.63,
        momentum_pe_trigger=-0.44,
    )


def make_state(signal_direction: str) -> TradeState:
    day = datetime.date(2026, 9, 22)
    timestamp = int(
        datetime.datetime(2026, 9, 22, 10, 0, tzinfo=IST).timestamp()
    )
    event = KTMITriggerEvent(
        strategy_id=TriggerStrategyId.MOMENTUM_ONLY,
        direction=(
            TriggerDirection.LONG
            if signal_direction == "LONG"
            else TriggerDirection.SHORT
        ),
        previous_value=0.0,
        current_value=0.6,
        trigger_value=0.5,
        index=1,
        timestamp=timestamp,
    )

    contract = SimpleNamespace(
        instrument_id=1,
        symbol="NSE:NIFTYTESTCE" if signal_direction == "LONG"
        else "NSE:NIFTYTESTPE",
        expiry_date=day,
        strike=24000,
        option_type="CE" if signal_direction == "LONG" else "PE",
        underlying="NIFTY",
    )

    entry = OptionEntry(
        event=event,
        contract=contract,
        signal_timestamp=timestamp + 180,
        entry_timestamp=timestamp + 240,
        underlying_price=24000.0,
        entry_price=100.0,
        lifecycle_action=__import__(
            "backtest.position_lifecycle",
            fromlist=["SignalAction"],
        ).SignalAction.ENTER,
        lifecycle_reason="TEST",
    )

    lifecycle = OptionTradeLifecycle()
    position = lifecycle.create_position(
        strategy_id=event.strategy_id.value,
        direction=OptionTradeDirection.LONG,
        symbol=contract.symbol,
        entry_price=100.0,
    )

    return TradeState(
        entry=entry,
        position=position,
        lifecycle=lifecycle,
        signal_direction=signal_direction,
        candles=(),
        next_index=1,
    )


def main() -> None:
    failures = []

    def check(label, condition):
        print(f"[{'PASS' if condition else 'FAIL'}] {label}")
        if not condition:
            failures.append(label)

    cfg = build_trigger_config(fake_args())
    check("Momentum CE trigger configurable", cfg.momentum_long_trigger == 0.63)
    check("Momentum PE trigger configurable", cfg.momentum_short_trigger == -0.44)
    check("Long Speed CE trigger configurable", cfg.long_speed_trigger == 0.41)
    check("Short Speed PE trigger configurable", cfg.short_speed_trigger == 0.57)

    # A BUY PE is long premium: 100 -> 125 must not hit the premium stop.
    pe = make_state("SHORT")
    candle_up = SimpleNamespace(
        timestamp=1,
        open=100.0,
        high=125.0,
        low=99.0,
        close=125.0,
    )
    process_buy_premium_candle(
        state=pe,
        candle=candle_up,
        underlying_close=23900.0,
        kama_value=24000.0,
    )
    check(
        "BUY PE is long-premium: rising PE premium does not hit the 20% premium stop",
        not pe.position.closed and pe.position.gross_pnl == 0.0,
    )

    # For a bearish BUY PE, underlying below KAMA should HOLD, not KAMA-exit.
    pe_hold = make_state("SHORT")
    process_buy_premium_candle(
        state=pe_hold,
        candle=candle_up,
        underlying_close=23900.0,
        kama_value=24000.0,
    )
    check("BUY PE KAMA rule uses bearish underlying direction", OptionExitReason.KAMA_EXIT not in [x.reason for x in pe_hold.exits])

    # For BUY PE, underlying above KAMA should KAMA-exit.
    pe_exit = make_state("SHORT")
    candle_flat = SimpleNamespace(
        timestamp=2,
        open=100.0,
        high=101.0,
        low=99.0,
        close=98.0,
    )
    process_buy_premium_candle(
        state=pe_exit,
        candle=candle_flat,
        underlying_close=24100.0,
        kama_value=24000.0,
    )
    check("BUY PE exits on underlying close above KAMA", pe_exit.position.closed)

    # For BUY CE, underlying below KAMA should KAMA-exit.
    ce_exit = make_state("LONG")
    process_buy_premium_candle(
        state=ce_exit,
        candle=candle_flat,
        underlying_close=23900.0,
        kama_value=24000.0,
    )
    check("BUY CE exits on underlying close below KAMA", ce_exit.position.closed)

    print()
    if failures:
        print(f"{len(failures)} FAILED")
        raise SystemExit(1)
    print("All V2 option-semantics checks passed.")


if __name__ == "__main__":
    main()
