"""Read-only forensic inspection of the HFT 10S NIFTY futures signal path.

This script does not modify the database, manifest, strategy configuration, or
existing production logic. It inspects the already-acquired 5S/10S data for a
single trading day and verifies the opening-gap/setup sequence.

Previous futures close is read from the database when available. If the sample
database does not contain an earlier candle for the same historical contract,
the script queries FYERS expired F&O history for a short lookback window. No
data from that fallback is written to the database.

The HFT source architecture remains:
    actual historical NIFTY futures -> FYERS 5S -> local 10S
"""

from __future__ import annotations

import argparse
import sqlite3
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from api.fyers_client import FyersClient
from config.hft_data import HFT_FETCH_RESOLUTION, HFT_RESOLUTION
from config.settings import DATABASE_PATH, TIMEZONE


def _db_connect(database_path: Path | str) -> sqlite3.Connection:
    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    return connection


def _epoch_for_local(day: str, hhmmss: str) -> int:
    local = datetime.fromisoformat(f"{day}T{hhmmss}").replace(
        tzinfo=ZoneInfo(TIMEZONE)
    )
    return int(local.timestamp())


def load_future_rows(
    database_path: Path | str,
    symbol: str,
    trade_date: str,
    resolution: str = HFT_RESOLUTION,
) -> list[dict]:
    start = _epoch_for_local(trade_date, "09:15:00")
    end = _epoch_for_local(trade_date, "15:40:00")

    with _db_connect(database_path) as db:
        rows = db.execute(
            """SELECT c.timestamp, c.open, c.high, c.low, c.close
               FROM candles c
               JOIN instruments i ON i.id = c.instrument_id
               WHERE i.broker = 'FYERS'
                 AND i.symbol = ?
                 AND c.resolution = ?
                 AND c.timestamp BETWEEN ? AND ?
               ORDER BY c.timestamp""",
            (symbol, resolution, start, end),
        ).fetchall()

    return [dict(row) for row in rows]


def _previous_db_close(
    database_path: Path | str,
    symbol: str,
    first_timestamp: int,
) -> float | None:
    with _db_connect(database_path) as db:
        row = db.execute(
            """SELECT c.close
               FROM candles c
               JOIN instruments i ON i.id = c.instrument_id
               WHERE i.broker = 'FYERS'
                 AND i.symbol = ?
                 AND c.timestamp < ?
               ORDER BY c.timestamp DESC
               LIMIT 1""",
            (symbol, first_timestamp),
        ).fetchone()
    return float(row["close"]) if row else None


def _fyers_previous_close(
    client: FyersClient,
    symbol: str,
    trade_date: str,
) -> tuple[float | None, str]:
    """Find the latest candle before the trade date using a bounded FYERS query."""
    day = date.fromisoformat(trade_date)
    start = day - timedelta(days=10)
    response = client.expired_history(
        symbol=symbol,
        resolution=HFT_FETCH_RESOLUTION,
        range_from=start.isoformat(),
        range_to=trade_date,
        include_oi="0",
        include_greeks="0",
    )
    candles = response.get("candles") or []
    if not candles:
        return None, "FYERS_NO_DATA"

    cutoff = _epoch_for_local(trade_date, "09:15:00")
    before = [row for row in candles if int(row[0]) < cutoff]
    if not before:
        return None, "FYERS_NO_PRIOR_CANDLE"

    before.sort(key=lambda row: int(row[0]))
    return float(before[-1][4]), "FYERS_5S"


def previous_futures_close(
    database_path: Path | str,
    symbol: str,
    trade_date: str,
    first_timestamp: int,
) -> tuple[float | None, str]:
    close = _previous_db_close(database_path, symbol, first_timestamp)
    if close is not None:
        return close, "DATABASE"

    client = FyersClient()
    return _fyers_previous_close(client, symbol, trade_date)


def _local_timestamp(timestamp: int) -> str:
    return datetime.fromtimestamp(
        int(timestamp), timezone.utc
    ).astimezone(ZoneInfo(TIMEZONE)).strftime("%Y-%m-%d %H:%M:%S")


def opening_gap(previous_close: float, current_open: float) -> float:
    return float(current_open) - float(previous_close)


def classify_gap(gap: float, threshold: float = 50.0) -> str:
    if gap >= threshold:
        return "CALL"
    if gap <= -threshold:
        return "PUT"
    return "NONE"


def open_equals_low(open_price: float, low_price: float) -> bool:
    return float(open_price) == float(low_price)


def high_breaks(setup_high: float, next_high: float) -> bool:
    return float(next_high) > float(setup_high)


def inspect(
    database_path: Path | str,
    symbol: str,
    trade_date: str,
    gap_threshold: float = 50.0,
) -> dict:
    rows = load_future_rows(database_path, symbol, trade_date)
    if len(rows) < 2:
        raise RuntimeError(
            f"Need at least two {HFT_RESOLUTION} futures candles for {trade_date}; "
            f"found {len(rows)}."
        )

    first = rows[0]
    second = rows[1]

    previous_close, previous_close_source = previous_futures_close(
        database_path,
        symbol,
        trade_date,
        int(first["timestamp"]),
    )
    if previous_close is None:
        raise RuntimeError(
            f"Could not determine previous futures close for {symbol} on {trade_date}."
        )

    gap = opening_gap(previous_close, float(first["open"]))
    direction = classify_gap(gap, gap_threshold)
    setup_valid = open_equals_low(float(first["open"]), float(first["low"]))
    break_valid = high_breaks(float(first["high"]), float(second["high"]))
    final_signal = direction != "NONE" and setup_valid and break_valid

    return {
        "trade_date": trade_date,
        "symbol": symbol,
        "resolution": HFT_RESOLUTION,
        "source_resolution": HFT_FETCH_RESOLUTION,
        "previous_close": previous_close,
        "previous_close_source": previous_close_source,
        "futures_open": float(first["open"]),
        "opening_gap": gap,
        "direction": direction,
        "first_candle": {
            "timestamp": _local_timestamp(int(first["timestamp"])),
            "open": float(first["open"]),
            "high": float(first["high"]),
            "low": float(first["low"]),
            "close": float(first["close"]),
            "open_equals_low": setup_valid,
        },
        "next_candle": {
            "timestamp": _local_timestamp(int(second["timestamp"])),
            "open": float(second["open"]),
            "high": float(second["high"]),
            "low": float(second["low"]),
            "close": float(second["close"]),
            "breaks_setup_high": break_valid,
        },
        "gap_valid": direction != "NONE",
        "setup_valid": setup_valid,
        "break_valid": break_valid,
        "final_signal": final_signal,
        "observed_10s_candles": len(rows),
    }


def print_report(result: dict) -> None:
    first = result["first_candle"]
    second = result["next_candle"]

    print("=" * 72)
    print("KUNAL QUANT — HFT 10S SIGNAL FORENSIC")
    print("=" * 72)
    print(f"Date                 : {result['trade_date']}")
    print(f"Underlying           : {result['symbol']}")
    print(f"Resolution           : {result['resolution']}")
    print(f"FYERS source         : {result['source_resolution']}")
    print()
    print(f"Previous FUT Close   : {result['previous_close']:.2f}")
    print(f"Previous-close source: {result['previous_close_source']}")
    print(f"FUT Open             : {result['futures_open']:.2f}")
    print(f"Opening Gap          : {result['opening_gap']:+.2f}")
    print(f"Direction            : {result['direction']}")
    print()
    print("FIRST 10S CANDLE")
    print("-" * 72)
    print(f"Time                 : {first['timestamp']}")
    print(f"Open                 : {first['open']:.2f}")
    print(f"High                 : {first['high']:.2f}")
    print(f"Low                  : {first['low']:.2f}")
    print(f"Close                : {first['close']:.2f}")
    print(f"Open == Low          : {'YES' if first['open_equals_low'] else 'NO'}")
    print()
    print("NEXT 10S CANDLE")
    print("-" * 72)
    print(f"Time                 : {second['timestamp']}")
    print(f"High                 : {second['high']:.2f}")
    print(f"Breaks setup high    : {'YES' if second['breaks_setup_high'] else 'NO'}")
    print()
    print("SIGNAL")
    print("-" * 72)
    print(f"Gap valid            : {'YES' if result['gap_valid'] else 'NO'}")
    print(f"Setup valid          : {'YES' if result['setup_valid'] else 'NO'}")
    print(f"Break valid          : {'YES' if result['break_valid'] else 'NO'}")
    print(f"Final signal         : {'VALID' if result['final_signal'] else 'INVALID'}")
    print(f"Observed 10S candles : {result['observed_10s_candles']}")
    print("=" * 72)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Inspect one-day HFT 10S NIFTY futures signal path."
    )
    parser.add_argument("--date", default="2026-08-21")
    parser.add_argument("--symbol", default="NSE:NIFTY26AUGFUT")
    parser.add_argument("--database", default=str(DATABASE_PATH))
    parser.add_argument("--gap-threshold", type=float, default=50.0)
    parser.add_argument("--json", default=None)
    args = parser.parse_args()

    result = inspect(
        args.database,
        args.symbol,
        args.date,
        args.gap_threshold,
    )
    print_report(result)

    if args.json:
        import json
        output = Path(args.json)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(f"Report: {output}")


if __name__ == "__main__":
    main()
