"""
Kunal Quant — Bar Timestamp / Lookahead Diagnostic (PROPOSAL)

Read-only audit of time semantics in the bounded real option pipeline.

Source-code fact being audited
------------------------------
The derived 3M resampler stores each bar timestamp at the BUCKET START.
A 3M bar starting at 09:15 contains the 1M candles stamped 09:15,
09:16 and 09:17, so its close is only knowable after 09:18.

The current KTMI event pipeline attaches the event timestamp to
bars[index].timestamp and the current option bridge chooses the first
1M option candle with timestamp strictly greater than that event time.

This diagnostic quantifies:
- how much earlier the current option entry timestamp is than the earliest
  timestamp after the completed 3M signal bar;
- whether KTMI event timestamps are bar starts;
- the current vs corrected KAMA underlying-bar alignment at option timestamps;
- counts of event/entry rows potentially using the still-forming 3M bar.

Canonical KunalQuant is not modified.
No trading rules are changed by this diagnostic.
"""

from __future__ import annotations

from bisect import bisect_right
from datetime import datetime
from zoneinfo import ZoneInfo

from backtest.fyers_option_candles import FyersOptionCandleLoader
from backtest.ktmi_trigger_pipeline import run_ktmi_trigger_pipeline
from backtest.real_option_trade_runner import calculate_nifty_kama
from config.settings import DATABASE_PATH
from scripts.run_real_option_sample import build_ktmi_config, load_complete_3m_bars
from strategies.option_contract_resolver import OptionContractResolver

TZ = ZoneInfo("Asia/Kolkata")


def local_dt(ts: int) -> str:
    return datetime.fromtimestamp(ts, tz=TZ).isoformat()


def main() -> None:
    bars = load_complete_3m_bars()
    pipeline = run_ktmi_trigger_pipeline(bars, build_ktmi_config())
    loader = FyersOptionCandleLoader(DATABASE_PATH)
    resolver = OptionContractResolver()

    underlying_timestamps = [bar.timestamp for bar in bars]
    kama_results = calculate_nifty_kama(bars)

    current_early_entries = 0
    expected_no_lookahead_entries = 0
    entry_delay_seconds = []
    kama_current_forming = 0
    sample_rows = []

    for event in sorted(pipeline.events, key=lambda e: (e.index, e.timestamp)):
        bar = bars[event.index]
        start_ts = bar.timestamp

        # aggregate_day() builds a 3M bucket from start_ts through
        # start_ts + 120 seconds. Its close is knowable at start_ts + 180.
        completed_signal_boundary = start_ts + 180

        try:
            contract = resolver.resolve(
                underlying_price=bar.close,
                entry_date=datetime.fromtimestamp(
                    start_ts,
                    tz=TZ,
                ).date(),
                direction=event.direction.value,
            )
        except LookupError:
            continue

        candles = sorted(
            loader.load(
                contract.instrument_id,
                start_ts - 3600,
                completed_signal_boundary + 3600,
            ),
            key=lambda c: c.timestamp,
        )

        current_entry = next(
            (c for c in candles if c.timestamp > start_ts),
            None,
        )
        corrected_entry = next(
            (c for c in candles if c.timestamp > completed_signal_boundary),
            None,
        )

        if current_entry is not None and current_entry.timestamp < completed_signal_boundary:
            current_early_entries += 1
            if len(sample_rows) < 20:
                sample_rows.append(
                    (
                        event.index,
                        local_dt(start_ts),
                        local_dt(completed_signal_boundary),
                        local_dt(current_entry.timestamp),
                        local_dt(corrected_entry.timestamp)
                        if corrected_entry is not None else "NONE",
                        event.strategy_id.value,
                        event.direction.value,
                    )
                )

        if corrected_entry is not None:
            expected_no_lookahead_entries += 1

        if current_entry is not None and corrected_entry is not None:
            entry_delay_seconds.append(
                corrected_entry.timestamp - current_entry.timestamp
            )

        # The existing management/KAMA mapping picks the latest 3M bar whose
        # START timestamp is <= the option candle timestamp. If that timestamp
        # still falls inside that 3M bar, its close/KAMA is not knowable yet.
        if current_entry is not None:
            idx = bisect_right(
                underlying_timestamps,
                current_entry.timestamp,
            ) - 1
            if idx >= 0:
                current_bar_end = underlying_timestamps[idx] + 180
                if current_entry.timestamp < current_bar_end:
                    kama_current_forming += 1

    print("=" * 100)
    print("KUNAL QUANT — BAR TIMESTAMP / LOOKAHEAD DIAGNOSTIC")
    print("=" * 100)
    print("PROPOSAL ONLY — read-only; canonical KunalQuant unchanged")
    print()
    print(f"Sample                    : {local_dt(bars[0].timestamp)} -> {local_dt(bars[-1].timestamp)}")
    print(f"KTMI events               : {len(pipeline.events):,}")
    print()
    print("TIMESTAMP SEMANTICS")
    print("3M derived bar timestamp  : BUCKET START")
    print("Example 3M bucket         : 09:15, 09:16, 09:17")
    print("3M bar information ready : 09:18")
    print()
    print("OPTION ENTRY AUDIT")
    print(f"Events with early entry   : {current_early_entries:,}")
    print(f"Events with later candle  : {expected_no_lookahead_entries:,}")
    print(
        "Average entry correction  : "
        f"{sum(entry_delay_seconds) / len(entry_delay_seconds):.1f}s"
        if entry_delay_seconds
        else "Average entry correction  : N/A"
    )
    print()
    print("KAMA TIME ALIGNMENT AUDIT")
    print(
        "Current entries mapped to "
        "still-forming 3M bar      : "
        f"{kama_current_forming:,}"
    )
    print()
    print("FIRST 20 EARLY-ENTRY EXAMPLES")
    for row in sample_rows:
        (
            event_index,
            event_ts,
            completion_ts,
            current_entry_ts,
            corrected_entry_ts,
            strategy,
            direction,
        ) = row
        print(
            f"event={event_index} | signal={event_ts} | "
            f"3M_ready={completion_ts} | "
            f"current_entry={current_entry_ts} | "
            f"corrected_entry={corrected_entry_ts} | "
            f"{strategy} | {direction}"
        )

    print()
    print(
        "This diagnostic does not patch execution. "
        "The timestamp contract should be resolved before trusting "
        "performance results."
    )


if __name__ == "__main__":
    main()
