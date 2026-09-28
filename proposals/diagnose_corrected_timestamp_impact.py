"""
Kunal Quant — Corrected Timestamp Impact Diagnostic (PROPOSAL)

Read-only audit of the timing correction implied by the existing derived
3M bar construction.

No canonical KunalQuant code is changed.

Timing model under audit
------------------------
A 3M derived bar is timestamped at its bucket start. Therefore a bar at
09:15 contains 09:15, 09:16 and 09:17 source minutes and becomes fully
known at 09:18.

This diagnostic does NOT choose a new execution rule. It compares:
A) current event timestamp = 3M bucket start
B) signal availability timestamp = bucket start + 180 seconds
while preserving the current bridge convention of entering from the close
of the first option candle strictly after the relevant signal timestamp.

It also compares:
A) current KAMA alignment = latest 3M bar start <= option timestamp
B) no-lookahead KAMA alignment = latest 3M bar whose completion timestamp
   (start + 180 seconds) <= option timestamp.

The goal is to quantify how many entries and KAMA references would move
before any production patch is considered.
"""

from __future__ import annotations

from bisect import bisect_right
from datetime import datetime, time
from zoneinfo import ZoneInfo

from backtest.fyers_option_candles import FyersOptionCandleLoader
from backtest.ktmi_trigger_pipeline import run_ktmi_trigger_pipeline
from config.settings import DATABASE_PATH, MARKET_CLOSE, TIMEZONE
from scripts.run_real_option_sample import build_ktmi_config, load_complete_3m_bars
from strategies.option_contract_resolver import OptionContractResolver

TZ = ZoneInfo(TIMEZONE)
CANDLE_SECONDS = 180


def local_dt(ts: int) -> str:
    return datetime.fromtimestamp(ts, tz=TZ).isoformat()


def market_close_timestamp(day) -> int:
    dt = datetime.combine(
        day,
        time.fromisoformat(MARKET_CLOSE),
        tzinfo=TZ,
    )
    return int(dt.timestamp())


def main() -> None:
    bars = load_complete_3m_bars()
    pipeline = run_ktmi_trigger_pipeline(bars, build_ktmi_config())
    loader = FyersOptionCandleLoader(DATABASE_PATH)
    resolver = OptionContractResolver()

    starts = [bar.timestamp for bar in bars]
    completions = [ts + CANDLE_SECONDS for ts in starts]

    early_entry_count = 0
    corrected_entry_count = 0
    corrected_entry_at_or_after_close = 0
    current_forming_kama_count = 0
    corrected_forming_kama_count = 0
    kama_shift_counts = {}
    entry_delay_seconds = []
    examples = []

    event_count = len(pipeline.events)

    for event in sorted(
        pipeline.events,
        key=lambda e: (e.index, e.timestamp),
    ):
        start_ts = bars[event.index].timestamp
        available_ts = start_ts + CANDLE_SECONDS

        try:
            contract = resolver.resolve(
                underlying_price=bars[event.index].close,
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
                available_ts + 3600,
            ),
            key=lambda c: c.timestamp,
        )

        current_entry = next(
            (c for c in candles if c.timestamp > start_ts),
            None,
        )
        corrected_entry = next(
            (c for c in candles if c.timestamp > available_ts),
            None,
        )

        if current_entry is not None and current_entry.timestamp < available_ts:
            early_entry_count += 1

        if corrected_entry is not None:
            corrected_entry_count += 1
            entry_delay_seconds.append(
                corrected_entry.timestamp - current_entry.timestamp
                if current_entry is not None
                else 0
            )

            close_ts = market_close_timestamp(
                datetime.fromtimestamp(
                    corrected_entry.timestamp,
                    tz=TZ,
                ).date()
            )
            if corrected_entry.timestamp >= close_ts:
                corrected_entry_at_or_after_close += 1

        if current_entry is not None:
            current_idx = bisect_right(starts, current_entry.timestamp) - 1
            if current_idx >= 0:
                if current_entry.timestamp < completions[current_idx]:
                    current_forming_kama_count += 1
            else:
                current_idx = None
        else:
            current_idx = None

        if corrected_entry is not None:
            corrected_idx = bisect_right(
                completions,
                corrected_entry.timestamp,
            ) - 1
            if corrected_idx < 0:
                corrected_idx = None
            else:
                # completions is increasing; this is by construction a
                # completed underlying bar, so the corrected alignment cannot
                # be a still-forming bar.
                pass
        else:
            corrected_idx = None

        if current_idx is not None and corrected_idx is not None:
            shift = current_idx - corrected_idx
            kama_shift_counts[shift] = kama_shift_counts.get(shift, 0) + 1
            if len(examples) < 20 and (
                shift != 0
                or current_entry.timestamp != corrected_entry.timestamp
            ):
                examples.append(
                    (
                        event.index,
                        event.strategy_id.value,
                        event.direction.value,
                        local_dt(start_ts),
                        local_dt(available_ts),
                        local_dt(current_entry.timestamp)
                        if current_entry is not None else "NONE",
                        local_dt(corrected_entry.timestamp),
                        shift,
                        starts[current_idx],
                        starts[corrected_idx],
                    )
                )

    print("=" * 100)
    print("KUNAL QUANT — CORRECTED TIMESTAMP IMPACT DIAGNOSTIC")
    print("=" * 100)
    print("PROPOSAL ONLY — read-only; canonical KunalQuant unchanged")
    print()
    print(f"KTMI events                        : {event_count:,}")
    print()
    print("ENTRY TIMING")
    print(
        "Early entries under current model : "
        f"{early_entry_count:,}"
    )
    print(
        "Corrected entries with candle     : "
        f"{corrected_entry_count:,}"
    )
    print(
        "Corrected entry >= market close   : "
        f"{corrected_entry_at_or_after_close:,}"
    )
    print(
        "Average entry delay               : "
        f"{sum(entry_delay_seconds) / len(entry_delay_seconds):.1f}s"
        if entry_delay_seconds else
        "Average entry delay               : N/A"
    )
    print()
    print("KAMA ALIGNMENT")
    print(
        "Current model uses forming 3M bar : "
        f"{current_forming_kama_count:,}"
    )
    print(
        "Corrected model forming 3M bar    : "
        f"{corrected_forming_kama_count:,}"
    )
    print("KAMA bar-index shift distribution :", dict(sorted(kama_shift_counts.items())))
    print()
    print("FIRST 20 CORRECTED-TIMING EXAMPLES")
    for row in examples:
        (
            idx,
            strategy,
            direction,
            signal,
            available,
            current_entry,
            corrected_entry,
            shift,
            current_bar,
            corrected_bar,
        ) = row
        print(
            f"event={idx} | {strategy} | {direction} | "
            f"signal={signal} | ready={available} | "
            f"current_entry={current_entry} | corrected_entry={corrected_entry} | "
            f"kama_shift={shift} | "
            f"current_kama_bar={local_dt(current_bar)} | "
            f"corrected_kama_bar={local_dt(corrected_bar)}"
        )

    print()
    print(
        "No execution patch is made by this diagnostic. "
        "The timestamp contract should be locked before comparing strategy P&L."
    )


if __name__ == "__main__":
    main()
