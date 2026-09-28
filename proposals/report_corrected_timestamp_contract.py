"""
Kunal Quant — Corrected Timestamp Contract Report (PROPOSAL)

Read-only report for locking the timestamp semantics before any strategy
performance optimization.

Canonical KunalQuant is not modified.

Timing contract audited
-----------------------
3M bars are timestamped at bucket start. A 3M bar at T contains T, T+1m,
T+2m and is fully known at T+3m.

For this diagnostic only:
- signal availability = 3M bucket start + 180 seconds
- current bridge-style entry remains the first option 1M candle with
  timestamp strictly greater than signal availability
- the entry price remains that candle's close, matching the existing
  execution convention
- corrected entry must remain inside the configured market session
- option candles are 1M start timestamps; their OHLC is fully known one
  minute after the candle timestamp
- KAMA can use only a 3M bar whose completion timestamp is no later than
  the option candle completion timestamp

This file quantifies the correction and lists all signals whose corrected
entry falls at/after the market close.
"""

from __future__ import annotations

from datetime import datetime, time
from zoneinfo import ZoneInfo

from backtest.fyers_option_candles import FyersOptionCandleLoader
from backtest.ktmi_trigger_pipeline import run_ktmi_trigger_pipeline
from backtest.real_option_trade_runner import calculate_nifty_kama
from config.settings import DATABASE_PATH, MARKET_CLOSE, TIMEZONE
from scripts.run_real_option_sample import build_ktmi_config, load_complete_3m_bars
from strategies.option_contract_resolver import OptionContractResolver

TZ = ZoneInfo(TIMEZONE)
THREE_MIN_SECONDS = 180
ONE_MIN_SECONDS = 60


def local_dt(ts: int) -> str:
    return datetime.fromtimestamp(ts, tz=TZ).isoformat()


def close_ts_for_day(day) -> int:
    return int(
        datetime.combine(
            day,
            time.fromisoformat(MARKET_CLOSE),
            tzinfo=TZ,
        ).timestamp()
    )


def main() -> None:
    bars = load_complete_3m_bars()
    pipeline = run_ktmi_trigger_pipeline(bars, build_ktmi_config())
    loader = FyersOptionCandleLoader(DATABASE_PATH)
    resolver = OptionContractResolver()

    corrected_entries = 0
    corrected_within_session = 0
    corrected_late = 0
    entry_deltas = []
    late_rows = []

    for event in sorted(
        pipeline.events,
        key=lambda e: (e.index, e.timestamp),
    ):
        signal_start = bars[event.index].timestamp
        signal_available = signal_start + THREE_MIN_SECONDS

        try:
            contract = resolver.resolve(
                underlying_price=bars[event.index].close,
                entry_date=datetime.fromtimestamp(
                    signal_start,
                    tz=TZ,
                ).date(),
                direction=event.direction.value,
            )
        except LookupError:
            continue

        candles = sorted(
            loader.load(
                contract.instrument_id,
                signal_start - 3600,
                signal_available + 3600,
            ),
            key=lambda candle: candle.timestamp,
        )

        corrected = next(
            (
                candle for candle in candles
                if candle.timestamp > signal_available
            ),
            None,
        )

        if corrected is None:
            continue

        corrected_entries += 1
        entry_deltas.append(
            corrected.timestamp - signal_start
        )

        # Market close is 15:30. A candle at 15:30 is outside the defined
        # regular-session 1M range whose final expected candle is 15:29.
        day = datetime.fromtimestamp(
            corrected.timestamp,
            tz=TZ,
        ).date()
        close_ts = close_ts_for_day(day)

        if corrected.timestamp >= close_ts:
            corrected_late += 1
            late_rows.append(
                (
                    event.index,
                    local_dt(signal_start),
                    local_dt(signal_available),
                    local_dt(corrected.timestamp),
                    event.strategy_id.value,
                    event.direction.value,
                    contract.symbol,
                )
            )
        else:
            corrected_within_session += 1

    print("=" * 100)
    print("KUNAL QUANT — CORRECTED TIMESTAMP CONTRACT REPORT")
    print("=" * 100)
    print("PROPOSAL ONLY — read-only; canonical KunalQuant unchanged")
    print()
    print(f"KTMI events                         : {len(pipeline.events):,}")
    print(f"Corrected entries with candle      : {corrected_entries:,}")
    print(f"Corrected entries within session   : {corrected_within_session:,}")
    print(f"Corrected entries at/after 15:30   : {corrected_late:,}")
    print(
        f"Average signal-to-entry delay     : "
        f"{sum(entry_deltas) / len(entry_deltas):.1f}s"
        if entry_deltas else
        "Average signal-to-entry delay     : N/A"
    )
    print()
    print("LATE CORRECTED ENTRIES")
    if not late_rows:
        print("NONE")
    else:
        for row in late_rows:
            (
                idx,
                signal,
                available,
                entry,
                strategy,
                direction,
                symbol,
            ) = row
            print(
                f"event={idx} | signal={signal} | ready={available} | "
                f"corrected_entry={entry} | {strategy} | {direction} | {symbol}"
            )

    print()
    print(
        "The 3M signal itself is not being changed here. "
        "Only its earliest knowable execution timestamp is audited."
    )


if __name__ == "__main__":
    main()
