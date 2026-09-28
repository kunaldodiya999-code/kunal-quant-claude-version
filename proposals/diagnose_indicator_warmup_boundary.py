"""
Kunal Quant — Indicator Warmup Boundary Diagnostic (PROPOSAL)

Read-only audit of whether running KTMI and KAMA on only the bounded
20-trading-day sample changes indicator state at the beginning of the sample.

Why this matters
----------------
Both KTMI and KAMA are time-series calculations with recursive/rolling
state. If a backtest slices the last 20 trading days first, the first sample
bar may be treated as a fresh history boundary instead of inheriting the
preceding historical state.

This diagnostic compares:
A) indicators calculated over ALL complete 3M history, then inspected over
   the last 20 trading days;
B) indicators calculated only over the last 20 trading days.

For KTMI it compares:
- number of events in the final 20-day window
- event timestamps/directions/strategy IDs
- first mismatches

For KAMA it compares:
- KAMA values over the final 20-day window
- first material mismatch
- maximum absolute difference

Canonical KunalQuant is not modified.
No database writes occur.
"""

from __future__ import annotations

import math
import sqlite3
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from backtest.models import BacktestBar
from backtest.ktmi_trigger_pipeline import run_ktmi_trigger_pipeline
from config.settings import PROCESSED_DATA_DIR
from scripts.run_real_option_sample import (
    build_ktmi_config,
    load_complete_3m_bars,
)
from indicators.kama_trend_follower.config import DEFAULT_KAMA_CONFIG
from indicators.kama_trend_follower.universal import KAMABar, calculate_kama_trend

DERIVED_DB = PROCESSED_DATA_DIR / "nifty_derived.db"
SYMBOL = "NSE:NIFTY50-INDEX"
SOURCE = "KQ_DERIVED_FROM_FYERS_1M"
TZ = ZoneInfo("Asia/Kolkata")


def load_all_complete_3m_bars() -> list[BacktestBar]:
    with sqlite3.connect(DERIVED_DB) as connection:
        rows = connection.execute(
            """
            SELECT timestamp, open, high, low, close, volume, open_interest
            FROM derived_candles
            WHERE symbol = ?
              AND resolution = '3'
              AND source = ?
              AND complete = 1
            ORDER BY timestamp
            """,
            (SYMBOL, SOURCE),
        ).fetchall()

    return [
        BacktestBar(
            timestamp=int(row[0]),
            open=float(row[1]),
            high=float(row[2]),
            low=float(row[3]),
            close=float(row[4]),
            volume=int(row[5] or 0),
            open_interest=None if row[6] is None else int(row[6]),
        )
        for row in rows
    ]


def last_twenty_days(bars: list[BacktestBar]) -> list[BacktestBar]:
    days: list[str] = []
    for bar in bars:
        day = datetime.fromtimestamp(
            bar.timestamp,
            tz=TZ,
        ).date().isoformat()
        if not days or day != days[-1]:
            days.append(day)

    keep = set(days[-20:])
    return [
        bar
        for bar in bars
        if datetime.fromtimestamp(
            bar.timestamp,
            tz=TZ,
        ).date().isoformat() in keep
    ]


def calculate_kama(bars: list[BacktestBar]):
    kama_bars = [
        KAMABar(
            open=bar.open,
            high=bar.high,
            low=bar.low,
            close=bar.close,
        )
        for bar in bars
    ]
    return calculate_kama_trend(
        bars=kama_bars,
        config=DEFAULT_KAMA_CONFIG,
    )


def main() -> None:
    all_bars = load_all_complete_3m_bars()
    sample_bars = last_twenty_days(all_bars)

    full_pipeline = run_ktmi_trigger_pipeline(
        all_bars,
        build_ktmi_config(),
    )
    sample_pipeline = run_ktmi_trigger_pipeline(
        sample_bars,
        build_ktmi_config(),
    )

    sample_start = sample_bars[0].timestamp

    full_events = [
        event
        for event in full_pipeline.events
        if event.timestamp is not None
        and event.timestamp >= sample_start
    ]

    sample_events = list(sample_pipeline.events)

    full_event_keys = [
        (
            event.timestamp,
            event.strategy_id.value,
            event.direction.value,
            event.previous_value,
            event.current_value,
            event.trigger_value,
        )
        for event in full_events
    ]
    sample_event_keys = [
        (
            event.timestamp,
            event.strategy_id.value,
            event.direction.value,
            event.previous_value,
            event.current_value,
            event.trigger_value,
        )
        for event in sample_events
    ]

    event_timestamp_mismatches = 0
    for left, right in zip(full_event_keys, sample_event_keys):
        if left != right:
            event_timestamp_mismatches += 1

    event_count_delta = len(sample_event_keys) - len(full_event_keys)

    full_kama = calculate_kama(all_bars)
    sample_kama = calculate_kama(sample_bars)

    full_index_by_timestamp = {
        bar.timestamp: index
        for index, bar in enumerate(all_bars)
    }

    kama_differences = []
    first_kama_mismatch = None

    for index, bar in enumerate(sample_bars):
        full_index = full_index_by_timestamp[bar.timestamp]
        full_value = full_kama[full_index].kama
        sample_value = sample_kama[index].kama

        if full_value is None or sample_value is None:
            continue

        difference = abs(float(full_value) - float(sample_value))
        kama_differences.append(difference)

        if difference > 1e-9 and first_kama_mismatch is None:
            first_kama_mismatch = (
                bar.timestamp,
                float(full_value),
                float(sample_value),
                difference,
            )

    max_kama_difference = (
        max(kama_differences)
        if kama_differences
        else 0.0
    )

    print("=" * 100)
    print("KUNAL QUANT — INDICATOR WARMUP BOUNDARY DIAGNOSTIC")
    print("=" * 100)
    print("PROPOSAL ONLY — read-only; canonical KunalQuant unchanged")
    print()
    print(f"All complete 3M bars              : {len(all_bars):,}")
    print(f"Last-20-day 3M bars                : {len(sample_bars):,}")
    print(
        "Sample start                       : "
        f"{datetime.fromtimestamp(sample_start, tz=TZ).isoformat()}"
    )
    print()
    print("KTMI WARMUP / EVENT COMPARISON")
    print(f"Full-history events in sample     : {len(full_events):,}")
    print(f"Slice-only events in sample       : {len(sample_events):,}")
    print(f"Event count delta                 : {event_count_delta:+d}")
    print(f"Positional event mismatches       : {event_timestamp_mismatches:,}")

    if full_event_keys != sample_event_keys:
        print()
        print("FIRST EVENT MISMATCHES")
        for index, (left, right) in enumerate(
            zip(full_event_keys, sample_event_keys)
        ):
            if left != right:
                print(
                    f"#{index + 1}: "
                    f"FULL={left} | "
                    f"SAMPLE={right}"
                )
                if index >= 9:
                    break

        if len(full_event_keys) != len(sample_event_keys):
            print(
                "Event sequences have different lengths; "
                "remaining unmatched events are not printed."
            )

    print()
    print("KAMA WARMUP COMPARISON")
    print(
        "Max absolute KAMA difference        : "
        f"{max_kama_difference:.10f}"
    )

    if first_kama_mismatch is None:
        print("KAMA sample-state comparison        : PASS")
    else:
        ts, full_value, sample_value, difference = first_kama_mismatch
        print("KAMA sample-state comparison        : DIFFERENT")
        print(
            f"First mismatch                      : "
            f"{datetime.fromtimestamp(ts, tz=TZ).isoformat()}"
        )
        print(f"Full-history KAMA                   : {full_value:.10f}")
        print(f"Slice-only KAMA                     : {sample_value:.10f}")
        print(f"Absolute difference                 : {difference:.10f}")

    print()
    print(
        "Interpretation: a clean sample should preserve historical indicator "
        "state rather than silently resetting recursive calculations at the "
        "backtest window boundary."
    )


if __name__ == "__main__":
    main()
