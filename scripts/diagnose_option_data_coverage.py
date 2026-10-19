"""Diagnostic-only report for historical NIFTY option data coverage.

Does not modify Resolver V2, option selection, signal logic, or candle data.
"""

from __future__ import annotations

import sqlite3
from collections import Counter
from datetime import datetime
from zoneinfo import ZoneInfo

from backtest.ktmi_trigger_pipeline import run_ktmi_trigger_pipeline
from config.settings import DATABASE_PATH
from scripts.run_real_option_sample import build_ktmi_config, load_complete_3m_bars
from strategies.option_contract_resolver import OptionContractResolver

TZ = ZoneInfo("Asia/Kolkata")


def main() -> None:
    bars = load_complete_3m_bars()
    pipeline = run_ktmi_trigger_pipeline(bars, build_ktmi_config())
    resolver = OptionContractResolver(DATABASE_PATH)

    unresolved = []
    resolved = []
    no_candle_1h = []
    candle_1h = []

    with sqlite3.connect(DATABASE_PATH) as db:
        for event in pipeline.events:
            bar = bars[event.index]
            direction = event.direction.value
            entry_date = datetime.fromtimestamp(bar.timestamp, tz=TZ).date()

            try:
                contract = resolver.resolve(
                    underlying_price=bar.close,
                    entry_date=entry_date,
                    direction=direction,
                )
            except LookupError:
                unresolved.append((event, bar))
                continue

            resolved.append((event, bar, contract))
            row = db.execute(
                """
                SELECT COUNT(*), MIN(timestamp), MAX(timestamp)
                FROM candles
                WHERE instrument_id = ?
                  AND resolution = '1'
                  AND source = 'FYERS_FNO_HISTORY'
                  AND timestamp > ?
                  AND timestamp <= ?
                """,
                (contract.instrument_id, bar.timestamp, bar.timestamp + 3600),
            ).fetchone()

            count = int(row[0])
            item = (event, bar, contract, count, row[1], row[2])
            (candle_1h if count else no_candle_1h).append(item)

        total_option_instruments = db.execute(
            """
            SELECT COUNT(*)
            FROM instruments
            WHERE broker='FYERS'
              AND underlying='NIFTY'
              AND option_type IN ('CE','PE')
            """
        ).fetchone()[0]

        candle_instruments = db.execute(
            """
            SELECT COUNT(DISTINCT instrument_id)
            FROM candles
            WHERE source='FYERS_FNO_HISTORY'
              AND resolution='1'
            """
        ).fetchone()[0]

        candle_rows = db.execute(
            """
            SELECT COUNT(*)
            FROM candles
            WHERE source='FYERS_FNO_HISTORY'
              AND resolution='1'
            """
        ).fetchone()[0]

        expiries = db.execute(
            """
            SELECT COUNT(DISTINCT expiry_date)
            FROM instruments
            WHERE broker='FYERS'
              AND underlying='NIFTY'
              AND option_type IN ('CE','PE')
              AND expiry_date IS NOT NULL
            """
        ).fetchone()[0]

    print("=" * 100)
    print("KUNAL QUANT — OPTION DATA COVERAGE DIAGNOSTIC")
    print("=" * 100)
    print("DIAGNOSTIC ONLY — no production strategy/resolver/data changes")
    print()
    print(f"Sample 3M bars                 : {len(bars):,}")
    print(f"KTMI events                    : {len(pipeline.events):,}")
    print(f"Option instruments             : {total_option_instruments:,}")
    print(f"Distinct candle instruments    : {candle_instruments:,}")
    print(f"FYERS F&O 1M candle rows       : {candle_rows:,}")
    print(f"Distinct NIFTY option expiries : {expiries:,}")
    print()
    print(f"Resolver-unresolved events     : {len(unresolved):,}")
    print(f"Resolver-resolved events       : {len(resolved):,}")
    print(f"Resolved + candles within 1h   : {len(candle_1h):,}")
    print(f"Resolved + NO candles within 1h: {len(no_candle_1h):,}")
    print()

    if unresolved:
        print("UNRESOLVED CONTRACT SAMPLES")
        for event, bar in unresolved[:20]:
            try:
                resolver.resolve(
                    underlying_price=bar.close,
                    entry_date=datetime.fromtimestamp(
                        bar.timestamp, tz=TZ
                    ).date(),
                    direction=event.direction.value,
                )
            except LookupError as exc:
                print(
                    f"{datetime.fromtimestamp(bar.timestamp, tz=TZ)} | "
                    f"price={bar.close:.2f} | "
                    f"{event.direction.value} | {exc}"
                )
        print()

    print("RESOLVED CONTRACT COVERAGE")
    contract_counts = Counter(
        contract.symbol for _, _, contract, *_ in resolved
    )
    for symbol, count in contract_counts.most_common(20):
        print(f"{symbol:35s} {count:4d} events")
    print()

    if no_candle_1h:
        print("RESOLVED BUT NO OPTION CANDLE WITHIN 1H — SAMPLES")
        for event, bar, contract, *_ in no_candle_1h[:20]:
            print(
                f"{datetime.fromtimestamp(bar.timestamp, tz=TZ)} | "
                f"{contract.symbol} | instrument={contract.instrument_id}"
            )
        print()

    print("3M TIMESTAMP SEMANTICS")
    first = bars[0]
    print(
        f"3M bar timestamp={datetime.fromtimestamp(first.timestamp, tz=TZ)} "
        f"represents the bucket beginning at that timestamp."
    )
    print(
        "For a 3-minute bar anchored at 09:15, the completed bar is "
        "09:15–09:17; this diagnostic does not change the current entry rule."
    )


if __name__ == "__main__":
    main()
