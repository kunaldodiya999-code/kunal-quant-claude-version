"""
Kunal Quant — Option Data Coverage Diagnostic v2

Drop-in replacement for scripts/diagnose_option_data_coverage.py in the
canonical repo. Read-only: Resolver V2, the KTMI pipeline, and stored
candle/instrument data are never modified.

v2.1 (after the first real run on 2026-09-28): the report logic now lives
in a pure function, build_report(), that is unit-tested against a
synthetic database -- the first real run exposed a symbol-grouping bug
that only an end-to-end run could have caught. New in the report:
  - which KTMI strategy (A or B) fired each event, and how many distinct
    entry moments there are (A and B often fire on the same bar)
  - a per-date breakdown
  - a per-expiry breakdown (shows which expiry the resolver landed on)
  - two acquisition worklists: contracts missing from the registry, and
    contracts registered but with no candles downloaded.

Run from the KunalQuant repo root with PYTHONPATH set to that root:
    python <path>/diagnose_option_data_coverage_v2.py
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from unresolved_event_classifier import (
    ClassificationResult,
    EventClassification,
    classify_event,
)

TZ = ZoneInfo("Asia/Kolkata")

ORDER = [
    EventClassification.RESOLVED_WITH_CANDLE,
    EventClassification.NO_OPTION_DATA,
    EventClassification.DATA_GAP,
    EventClassification.CONTRACT_NOT_FOUND,
    EventClassification.EXPIRY_NOT_FOUND,
    EventClassification.UNKNOWN,
]


@dataclass(frozen=True)
class EventRow:
    """Just what the report needs from a KTMI event + its bar."""

    timestamp: int
    price: float
    direction: str
    strategy: str


def _when(ts: int) -> datetime:
    return datetime.fromtimestamp(ts, tz=TZ)


def build_report(
    rows: list[EventRow],
    resolver,
    database_path,
    sample_bars: int,
    sample_limit: int = 8,
) -> str:
    classified: list[tuple[EventRow, ClassificationResult]] = []
    for row in rows:
        result = classify_event(
            resolver,
            underlying_price=row.price,
            entry_date=_when(row.timestamp).date(),
            direction=row.direction,
            signal_timestamp=row.timestamp,
            database_path=database_path,
        )
        classified.append((row, result))

    out: list[str] = []
    w = out.append
    bar = "=" * 100

    w(bar)
    w("KUNAL QUANT — OPTION DATA COVERAGE DIAGNOSTIC v2.1 (classified)")
    w(bar)
    w("DIAGNOSTIC ONLY — no production strategy/resolver/data changes")
    w("")
    w(f"Sample 3M bars                 : {sample_bars:,}")
    w(f"KTMI events                    : {len(rows):,}")
    distinct = {(r.timestamp, r.direction) for r in rows}
    w(f"Distinct entry moments         : {len(distinct):,}  (same bar + direction)")
    by_strategy = Counter(r.strategy for r in rows)
    for name, count in sorted(by_strategy.items()):
        w(f"  events from {name:<22}: {count:,}")
    w("")

    counts = Counter(res.classification for _, res in classified)
    for c in ORDER:
        w(f"{c.value:24s}: {counts.get(c, 0):,}")
    w("")

    # ---- per date ---------------------------------------------------
    w("BY DATE (IST)")
    w(f"{'date':<12}{'events':>7}{'resolved':>10}{'no_data':>9}{'gap':>5}"
      f"{'not_found':>11}{'other':>7}")
    per_date: dict = defaultdict(Counter)
    for row, res in classified:
        per_date[_when(row.timestamp).date()][res.classification] += 1
    for d in sorted(per_date):
        c = per_date[d]
        other = c[EventClassification.EXPIRY_NOT_FOUND] + c[EventClassification.UNKNOWN]
        w(
            f"{d.isoformat():<12}{sum(c.values()):>7}"
            f"{c[EventClassification.RESOLVED_WITH_CANDLE]:>10}"
            f"{c[EventClassification.NO_OPTION_DATA]:>9}"
            f"{c[EventClassification.DATA_GAP]:>5}"
            f"{c[EventClassification.CONTRACT_NOT_FOUND]:>11}{other:>7}"
        )
    w("")

    # ---- per expiry the resolver landed on ---------------------------
    w("BY EXPIRY THE RESOLVER LANDED ON (nearest expiry REGISTERED in `instruments`)")
    per_expiry: dict = defaultdict(Counter)
    for row, res in classified:
        if res.expiry is not None:
            per_expiry[res.expiry][res.classification] += 1
    for expiry in sorted(per_expiry):
        c = per_expiry[expiry]
        parts = ", ".join(f"{k.value}={v}" for k, v in c.items())
        w(f"{expiry.isoformat()}  events={sum(c.values()):>4}  {parts}")
    w("")

    # ---- resolved coverage by contract -------------------------------
    resolved = Counter(
        res.symbol
        for _, res in classified
        if res.classification
        in (
            EventClassification.RESOLVED_WITH_CANDLE,
            EventClassification.NO_OPTION_DATA,
            EventClassification.DATA_GAP,
        )
    )
    w("RESOLVED CONTRACTS (events per contract)")
    for symbol, count in resolved.most_common(25):
        w(f"{symbol:<34}{count:>5} events")
    w("")

    # ---- worklists ----------------------------------------------------
    missing = Counter(
        (res.expiry, res.strike, res.option_type)
        for _, res in classified
        if res.classification == EventClassification.CONTRACT_NOT_FOUND
        and res.expiry is not None
    )
    w("WORKLIST 1 — contracts NOT in the instruments table "
      f"({len(missing)} distinct, events affected in brackets)")
    for (expiry, strike, opt), count in sorted(missing.items(), key=lambda kv: (kv[0][0], kv[0][1], kv[0][2])):
        w(f"  NIFTY {expiry} {strike} {opt}   [{count}]")
    w("")

    no_data = Counter(
        res.symbol
        for _, res in classified
        if res.classification == EventClassification.NO_OPTION_DATA
    )
    w("WORKLIST 2 — contracts registered but with ZERO candles downloaded "
      f"({len(no_data)} distinct)")
    for symbol, count in sorted(no_data.items()):
        w(f"  {symbol}   [{count}]")
    w("")

    # ---- samples ------------------------------------------------------
    for c in (
        EventClassification.CONTRACT_NOT_FOUND,
        EventClassification.NO_OPTION_DATA,
        EventClassification.DATA_GAP,
        EventClassification.EXPIRY_NOT_FOUND,
        EventClassification.UNKNOWN,
    ):
        items = [(r, res) for r, res in classified if res.classification == c]
        if not items:
            continue
        w(f"{c.value} — first {min(sample_limit, len(items))} of {len(items)}")
        for row, res in items[:sample_limit]:
            w(
                f"  {_when(row.timestamp):%Y-%m-%d %H:%M} | {row.strategy} | "
                f"{row.direction} | price={row.price:.2f} | {res.detail}"
            )
        w("")

    return "\n".join(out)


def main() -> None:
    from backtest.ktmi_trigger_pipeline import run_ktmi_trigger_pipeline
    from config.settings import DATABASE_PATH
    from scripts.run_real_option_sample import (
        build_ktmi_config,
        load_complete_3m_bars,
    )
    from strategies.option_contract_resolver import OptionContractResolver

    bars = load_complete_3m_bars()
    pipeline = run_ktmi_trigger_pipeline(bars, build_ktmi_config())
    resolver = OptionContractResolver(DATABASE_PATH)

    rows = [
        EventRow(
            timestamp=bars[e.index].timestamp,
            price=bars[e.index].close,
            direction=e.direction.value,
            strategy=e.strategy_name,
        )
        for e in pipeline.events
    ]
    print(build_report(rows, resolver, DATABASE_PATH, sample_bars=len(bars)))


if __name__ == "__main__":
    main()
