"""
Kunal Quant — Option Data Coverage Diagnostic v2

Drop-in replacement for scripts/diagnose_option_data_coverage.py in the
canonical repo. Same inputs, same "diagnostic only" guarantee -- Resolver
V2, the KTMI pipeline, and stored candle/instrument data are all read-only
here. The only behavioural change: instead of one "unresolved" pile, the
unresolved bucket is split using unresolved_event_classifier.py into
EXPIRY_NOT_FOUND / CONTRACT_NOT_FOUND / UNKNOWN, and the resolved bucket is
split into RESOLVED_WITH_CANDLE / NO_ENTRY_CANDLE.

NOT independently run end-to-end: load_complete_3m_bars() and
run_ktmi_trigger_pipeline() need the real database this environment
doesn't have. The classification logic itself (the actual change from v1)
is verified separately in test_classifier.py against synthetic data --
this file only wires that already-tested logic into the original script's
reporting structure. Syntax-checked, not run.

To use: drop into the canonical repo's scripts/ directory alongside
unresolved_event_classifier.py, or point PYTHONPATH at both.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime
from zoneinfo import ZoneInfo

from backtest.ktmi_trigger_pipeline import run_ktmi_trigger_pipeline
from config.settings import DATABASE_PATH
from scripts.run_real_option_sample import build_ktmi_config, load_complete_3m_bars
from strategies.option_contract_resolver import OptionContractResolver

from unresolved_event_classifier import EventClassification, classify_event

TZ = ZoneInfo("Asia/Kolkata")


def main() -> None:
    bars = load_complete_3m_bars()
    pipeline = run_ktmi_trigger_pipeline(bars, build_ktmi_config())
    resolver = OptionContractResolver(DATABASE_PATH)

    buckets: dict[EventClassification, list] = {
        classification: [] for classification in EventClassification
    }

    for event in pipeline.events:
        bar = bars[event.index]
        entry_date = datetime.fromtimestamp(bar.timestamp, tz=TZ).date()

        result = classify_event(
            resolver,
            underlying_price=bar.close,
            entry_date=entry_date,
            direction=event.direction.value,
            signal_timestamp=bar.timestamp,
            database_path=DATABASE_PATH,
        )
        buckets[result.classification].append((event, bar, result))

    print("=" * 100)
    print("KUNAL QUANT — OPTION DATA COVERAGE DIAGNOSTIC v2 (classified)")
    print("=" * 100)
    print("DIAGNOSTIC ONLY — no production strategy/resolver/data changes")
    print()
    print(f"Sample 3M bars                 : {len(bars):,}")
    print(f"KTMI events                    : {len(pipeline.events):,}")
    print()

    for classification in EventClassification:
        items = buckets[classification]
        print(f"{classification.value:24s}: {len(items):,}")
    print()

    for classification in (
        EventClassification.EXPIRY_NOT_FOUND,
        EventClassification.CONTRACT_NOT_FOUND,
        EventClassification.UNKNOWN,
    ):
        items = buckets[classification]
        if not items:
            continue
        print(f"{classification.value} — SAMPLES")
        for event, bar, result in items[:20]:
            print(
                f"{datetime.fromtimestamp(bar.timestamp, tz=TZ)} | "
                f"price={bar.close:.2f} | "
                f"{event.direction.value} | {result.detail}"
            )
        print()

    resolved_symbols = Counter(
        result.detail.split(" ")[0]
        for classification in (
            EventClassification.RESOLVED_WITH_CANDLE,
            EventClassification.NO_ENTRY_CANDLE,
        )
        for _, _, result in buckets[classification]
    )
    print("RESOLVED CONTRACT COVERAGE")
    for symbol, count in resolved_symbols.most_common(20):
        print(f"{symbol:35s} {count:4d} events")
    print()

    no_candle = buckets[EventClassification.NO_ENTRY_CANDLE]
    if no_candle:
        print("NO_ENTRY_CANDLE — SAMPLES")
        for event, bar, result in no_candle[:20]:
            print(f"{datetime.fromtimestamp(bar.timestamp, tz=TZ)} | {result.detail}")
        print()


if __name__ == "__main__":
    main()
