"""Audit exact option contracts required by Opening Breakout V2 signals.

Research-only and read-only. This script does not download data and does not
modify the database. It converts real NIFTY 1-minute sessions into the exact
CALL/PUT contracts the current Resolver V2 would select, then audits whether
those contracts have complete FYERS 1-minute candles for the signal date.

The output is the input for the later targeted FYERS acquisition step.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backtest.opening_breakout_v2_signal_engine import SignalSeries, scan_series
from config.settings import DATABASE_PATH, EXPECTED_1M_CANDLES
from research.opening_breakout_1m_v2 import Candle, IndicatorSnapshot, V2Config
from strategies.option_contract_resolver import OptionContractResolver
from backtest.historical_nifty_expiry import historical_nifty_expiry

IST = ZoneInfo("Asia/Kolkata")
SOURCE = "FYERS_FNO_HISTORY"


@dataclass(frozen=True)
class RequiredContract:
    signal_date: date
    signal_timestamp: int
    direction: str
    option_type: str
    strike: int
    expiry_date: date
    instrument_id: int | None
    symbol: str | None


def epoch_seconds(value: str) -> int:
    return int(datetime.fromisoformat(value).replace(tzinfo=IST).timestamp())


def date_from_ts(timestamp: int) -> date:
    return datetime.fromtimestamp(timestamp, tz=IST).date()


def load_nifty(database_path: Path, start_ts: int, end_ts: int) -> list[Candle]:
    with sqlite3.connect(database_path) as db:
        rows = db.execute(
            """
            SELECT c.timestamp, c.open, c.high, c.low, c.close
            FROM candles c
            JOIN instruments i ON i.id = c.instrument_id
            WHERE i.broker='FYERS'
              AND i.symbol='NSE:NIFTY50-INDEX'
              AND c.resolution='1'
              AND c.timestamp BETWEEN ? AND ?
            ORDER BY c.timestamp
            """,
            (start_ts, end_ts),
        ).fetchall()
    return [Candle(int(ts), float(op), float(hi), float(lo), float(cl)) for ts, op, hi, lo, cl in rows]


def empty_indicator_provider(timestamp: int, candle: Candle) -> IndicatorSnapshot:
    return IndicatorSnapshot()


def session_groups(candles: list[Candle]) -> dict[date, list[Candle]]:
    groups: dict[date, list[Candle]] = defaultdict(list)
    for candle in candles:
        groups[date_from_ts(candle.timestamp)].append(candle)
    return dict(sorted(groups.items()))


def option_type_for_direction(direction: str) -> str:
    return "CE" if direction == "LONG" else "PE"


def trigger_for_instrument(instrument: str) -> str:
    return "CANDLE_HIGH" if instrument == "CALL" else "CANDLE_LOW"


def resolve_required(
    resolver: OptionContractResolver,
    event,
    underlying_candles: list[Candle],
    session_dates: set[date],
) -> RequiredContract:
    signal_date = date_from_ts(event.trigger_timestamp)
    option_type = option_type_for_direction(event.direction)

    candidates = [
        candle
        for candle in underlying_candles
        if candle.timestamp <= event.trigger_timestamp
    ]
    if not candidates:
        raise LookupError("no underlying candle at or before signal timestamp")
    underlying_price = max(candidates, key=lambda candle: candle.timestamp).close
    strike = resolver.calculate_atm_strike(underlying_price)

    # IMPORTANT: do not use Resolver V2 for historical expiry selection.
    # Its local instrument inventory can be incomplete for older dates, which
    # can otherwise select the first later expiry present in the database.
    expiry = historical_nifty_expiry(signal_date, session_dates)

    with sqlite3.connect(resolver.database_path) as db:
        row = db.execute(
            """
            SELECT id, symbol
            FROM instruments
            WHERE broker='FYERS'
              AND underlying='NIFTY'
              AND expiry_date=?
              AND strike=?
              AND option_type=?
            ORDER BY symbol
            LIMIT 1
            """,
            (expiry.isoformat(), strike, option_type),
        ).fetchone()

    return RequiredContract(
        signal_date=signal_date,
        signal_timestamp=event.trigger_timestamp,
        direction=event.direction,
        option_type=option_type,
        strike=strike,
        expiry_date=expiry,
        instrument_id=int(row[0]) if row else None,
        symbol=str(row[1]) if row else None,
    )


def audit_coverage(
    database_path: Path,
    required: list[RequiredContract],
    expected_candles_by_date: dict[date, int] | None = None,
) -> list[dict]:
    unique = {}
    for item in required:
        key = (
            item.signal_date,
            item.expiry_date,
            item.strike,
            item.option_type,
        )
        unique[key] = item

    results = []
    expected_candles_by_date = expected_candles_by_date or {}
    with sqlite3.connect(database_path) as db:
        for item in sorted(
            unique.values(),
            key=lambda x: (x.signal_date, x.expiry_date, x.strike, x.option_type),
        ):
            if item.instrument_id is None:
                results.append(
                    {
                        "signal_date": item.signal_date,
                        "expiry_date": item.expiry_date,
                        "strike": item.strike,
                        "option_type": item.option_type,
                        "instrument_id": None,
                        "symbol": None,
                        "status": "UNREGISTERED",
                        "candles": 0,
                        "first_ts": None,
                        "last_ts": None,
                    }
                )
                continue

            row = db.execute(
                """
                SELECT COUNT(*), MIN(timestamp), MAX(timestamp)
                FROM candles
                WHERE instrument_id=?
                  AND resolution='1'
                  AND source=?
                  AND timestamp BETWEEN ? AND ?
                """,
                (
                    item.instrument_id,
                    SOURCE,
                    int(
                        datetime.combine(
                            item.signal_date,
                            datetime.min.time(),
                            tzinfo=IST,
                        ).timestamp()
                    ),
                    int(
                        datetime.combine(
                            item.signal_date,
                            datetime.max.time(),
                            tzinfo=IST,
                        ).timestamp()
                    ),
                ),
            ).fetchone()

            count, first_ts, last_ts = row
            expected_count = int(
                expected_candles_by_date.get(
                    item.signal_date,
                    EXPECTED_1M_CANDLES,
                )
            )
            status = (
                "COMPLETE"
                if int(count or 0) >= expected_count
                else ("EMPTY" if not count else "PARTIAL")
            )
            results.append(
                {
                    "signal_date": item.signal_date,
                    "expiry_date": item.expiry_date,
                    "strike": item.strike,
                    "option_type": item.option_type,
                    "instrument_id": item.instrument_id,
                    "symbol": item.symbol,
                    "status": status,
                    "candles": int(count or 0),
                    "first_ts": first_ts,
                    "last_ts": last_ts,
                }
            )
    return results


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--from", dest="start", required=True, help="IST datetime")
    parser.add_argument("--to", dest="end", required=True, help="IST datetime")
    parser.add_argument(
        "--instrument",
        choices=("CALL", "PUT", "BOTH"),
        default="CALL",
    )
    parser.add_argument("--database", type=Path, default=DATABASE_PATH)
    args = parser.parse_args()

    start_ts = epoch_seconds(args.start)
    end_ts = epoch_seconds(args.end)
    nifty = load_nifty(args.database, start_ts, end_ts)
    if not nifty:
        raise RuntimeError("No NIFTY 1-minute candles found in requested range.")

    base_config = V2Config(
        trade_instrument="CALL",
        market_bias="NEUTRAL",
        selected_timeframes=("1M",),
        selected_triggers=("CANDLE_HIGH",),
        filter_open_high=False,
        filter_open_low=False,
    )

    resolver = OptionContractResolver(database_path=args.database)
    required: list[RequiredContract] = []
    sessions = session_groups(nifty)
    session_dates = set(sessions)

    print("=" * 110)
    print("KUNAL QUANT — OPENING BREAKOUT V2 REQUIRED OPTION COVERAGE AUDIT")
    print("=" * 110)
    print("READ-ONLY: no FYERS calls, no database changes")
    print(f"NIFTY candles : {len(nifty)}")
    print(f"Sessions      : {len(sessions)}")
    print(f"Instrument    : {args.instrument}")

    instruments = (
        ("CALL", "CE", trigger_for_instrument("CALL")),
        ("PUT", "PE", trigger_for_instrument("PUT")),
    )
    if args.instrument == "BOTH":
        candidates = instruments
    elif args.instrument == "CALL":
        candidates = (instruments[0],)
    else:
        candidates = (instruments[1],)

    for session_date, candles in sessions.items():
        for instrument, option_type, trigger in candidates:
            series = SignalSeries(
                symbol="NIFTY-V2-CANDIDATE",
                option_type=option_type,
                strike=0,
                lot_size=1,
                candles=candles,
            )
            session_config = V2Config(
                **{
                    **base_config.__dict__,
                    "trade_instrument": instrument,
                    "selected_triggers": (trigger,),
                }
            )
            _, signals = scan_series(
                series,
                config=session_config,
                indicator_provider=empty_indicator_provider,
            )
            for event in signals:
                try:
                    required.append(resolve_required(resolver, event, candles, session_dates))
                except LookupError as exc:
                    print(
                        f"[UNRESOLVED] date={session_date} ts={event.trigger_timestamp} "
                        f"direction={event.direction}: {exc}"
                    )

    results = audit_coverage(args.database, required)

    counts = defaultdict(int)
    for row in results:
        counts[row["status"]] += 1

    print("\n[SUMMARY]")
    print(f"Signals requiring option data : {len(required)}")
    print(f"Unique contract-days          : {len(results)}")
    for status in ("COMPLETE", "PARTIAL", "EMPTY", "UNREGISTERED"):
        print(f"{status:<28}: {counts[status]}")

    print("\n[REQUIRED CONTRACT-DAYS]")
    for row in results:
        print(
            f"{row['signal_date']} expiry={row['expiry_date']} "
            f"{row['strike']} {row['option_type']} "
            f"id={row['instrument_id']} candles={row['candles']} "
            f"status={row['status']} symbol={row['symbol']}"
        )

    print("=" * 110)


if __name__ == "__main__":
    main()
