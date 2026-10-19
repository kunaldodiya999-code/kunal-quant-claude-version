from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

from config.settings import (
    DATABASE_PATH,
    EXPECTED_1M_CANDLES,
    MARKET_OPEN,
    EXPECTED_LAST_1M_CANDLE,
)


class DataQualityEngine:
    """
    Kunal Quant historical-data quality engine.

    Validates stored candles for:

    - Missing timestamps
    - Duplicate timestamps
    - OHLC sanity
    - Trading-session completeness
    - Open-interest coverage
    - Zero-volume candles
    - Timestamp ordering

    The engine never fabricates missing data.
    It only detects and records quality events.
    """

    TIMEZONE = ZoneInfo(
        "Asia/Kolkata"
    )

    OPTIONS_TYPES = (
        "CE",
        "PE",
    )

    FUTURE_OPTION_TYPE = "XX"

    def __init__(
        self,
        database_path: Path | str = DATABASE_PATH,
    ) -> None:

        self.database_path = Path(
            database_path
        )

        self.database_path.parent.mkdir(
            parents=True,
            exist_ok=True
        )

    # =========================================================
    # DATABASE
    # =========================================================

    def _connect(self) -> sqlite3.Connection:

        connection = sqlite3.connect(
            self.database_path
        )

        connection.row_factory = sqlite3.Row

        connection.execute(
            "PRAGMA foreign_keys = ON"
        )

        return connection

    # =========================================================
    # INSTRUMENT LOOKUP
    # =========================================================

    def get_instrument(
        self,
        symbol: str,
    ) -> dict | None:

        query = """
        SELECT *
        FROM instruments

        WHERE broker = 'FYERS'
          AND symbol = ?

        LIMIT 1
        """

        with self._connect() as connection:

            row = connection.execute(
                query,
                (symbol,)
            ).fetchone()

        if row is None:

            return None

        return dict(row)

    # =========================================================
    # CANDLE RETRIEVAL
    # =========================================================

    def get_candles(
        self,
        instrument_id: int,
        resolution: str,
        source: str | None = None,
    ) -> list[dict]:

        query = """
        SELECT
            id,
            instrument_id,
            timestamp,
            open,
            high,
            low,
            close,
            volume,
            open_interest,
            resolution,
            source

        FROM candles

        WHERE instrument_id = ?
          AND resolution = ?
        """

        parameters: list = [
            instrument_id,
            resolution,
        ]

        if source is not None:

            query += """
              AND source = ?
            """

            parameters.append(
                source
            )

        query += """
        ORDER BY timestamp
        """

        with self._connect() as connection:

            rows = connection.execute(
                query,
                parameters,
            ).fetchall()

        return [
            dict(row)
            for row in rows
        ]

    # =========================================================
    # TIMESTAMP CONVERSION
    # =========================================================

    @classmethod
    def timestamp_to_local(
        cls,
        timestamp: int,
    ) -> datetime:

        return datetime.fromtimestamp(
            int(timestamp),
            tz=ZoneInfo("UTC")
        ).astimezone(
            cls.TIMEZONE
        )

    # =========================================================
    # EXPECTED SESSION MINUTES
    # =========================================================

    @classmethod
    def expected_session_timestamps(
        cls,
        trade_date: str,
    ) -> list[int]:

        date_value = datetime.strptime(
            trade_date,
            "%Y-%m-%d"
        ).date()

        market_open = datetime.combine(
            date_value,
            time(
                9,
                15
            ),
            tzinfo=cls.TIMEZONE,
        )

        last_candle = datetime.combine(
            date_value,
            time(
                15,
                29
            ),
            tzinfo=cls.TIMEZONE,
        )

        timestamps: list[int] = []

        current = market_open

        while current <= last_candle:

            timestamps.append(
                int(
                    current.timestamp()
                )
            )

            current = (
                current
                + __import__(
                    "datetime"
                ).timedelta(
                    minutes=1
                )
            )

        return timestamps

    # =========================================================
    # GROUP CANDLES BY TRADE DATE
    # =========================================================

    def group_by_trade_date(
        self,
        candles: list[dict],
    ) -> dict[str, list[dict]]:

        grouped: dict[
            str,
            list[dict]
        ] = {}

        for candle in candles:

            local_time = (
                self.timestamp_to_local(
                    candle["timestamp"]
                )
            )

            trade_date = (
                local_time.date()
                .isoformat()
            )

            grouped.setdefault(
                trade_date,
                []
            ).append(
                candle
            )

        return grouped

    # =========================================================
    # QUALITY EVENT INSERT
    # =========================================================

    def record_event(
        self,
        instrument_id: int,
        timestamp: int | None,
        event_type: str,
        severity: str,
        description: str,
    ) -> None:

        sql = """
        INSERT INTO data_quality_events (
            instrument_id,
            timestamp,
            event_type,
            severity,
            description
        )
        VALUES (
            ?,
            ?,
            ?,
            ?,
            ?
        )
        """

        with self._connect() as connection:

            connection.execute(
                sql,
                (
                    instrument_id,
                    timestamp,
                    event_type,
                    severity,
                    description,
                )
            )

            connection.commit()

    # =========================================================
    # DUPLICATE TIMESTAMP CHECK
    # =========================================================

    def check_duplicates(
        self,
        instrument_id: int,
        candles: list[dict],
    ) -> int:

        seen: set[int] = set()

        duplicates = 0

        for candle in candles:

            timestamp = int(
                candle["timestamp"]
            )

            if timestamp in seen:

                duplicates += 1

                self.record_event(
                    instrument_id=instrument_id,
                    timestamp=timestamp,
                    event_type="DUPLICATE_TIMESTAMP",
                    severity="ERROR",
                    description=(
                        "Duplicate candle timestamp "
                        f"detected: {timestamp}"
                    ),
                )

            else:

                seen.add(
                    timestamp
                )

        return duplicates

    # =========================================================
    # TIMESTAMP ORDER CHECK
    # =========================================================

    def check_timestamp_order(
        self,
        instrument_id: int,
        candles: list[dict],
    ) -> int:

        problems = 0

        previous = None

        for candle in candles:

            current = int(
                candle["timestamp"]
            )

            if (
                previous is not None
                and current <= previous
            ):

                problems += 1

                self.record_event(
                    instrument_id=instrument_id,
                    timestamp=current,
                    event_type="TIMESTAMP_ORDER",
                    severity="ERROR",
                    description=(
                        "Candle timestamps are not "
                        "strictly increasing."
                    ),
                )

            previous = current

        return problems

    # =========================================================
    # OHLC CHECK
    # =========================================================

    def check_ohlc(
        self,
        instrument_id: int,
        candles: list[dict],
    ) -> int:

        problems = 0

        for candle in candles:

            timestamp = int(
                candle["timestamp"]
            )

            open_price = float(
                candle["open"]
            )

            high_price = float(
                candle["high"]
            )

            low_price = float(
                candle["low"]
            )

            close_price = float(
                candle["close"]
            )

            valid = (
                high_price >= max(
                    open_price,
                    close_price,
                    low_price,
                )
                and
                low_price <= min(
                    open_price,
                    close_price,
                    high_price,
                )
            )

            if not valid:

                problems += 1

                self.record_event(
                    instrument_id=instrument_id,
                    timestamp=timestamp,
                    event_type="INVALID_OHLC",
                    severity="ERROR",
                    description=(
                        "OHLC relationship is invalid."
                    ),
                )

            if (
                open_price < 0
                or high_price < 0
                or low_price < 0
                or close_price < 0
            ):

                problems += 1

                self.record_event(
                    instrument_id=instrument_id,
                    timestamp=timestamp,
                    event_type="NEGATIVE_PRICE",
                    severity="ERROR",
                    description=(
                        "Negative OHLC price detected."
                    ),
                )

        return problems

    # =========================================================
    # ZERO VOLUME CHECK
    # =========================================================

    def check_zero_volume(
        self,
        instrument_id: int,
        candles: list[dict],
        instrument: dict,
    ) -> int:

        # Index / volatility-index series may return
        # zero volume through the broker API.
        #
        # Preserve the raw value, but do not create
        # a quality event for every candle.
        if instrument.get("instrument_type") == "INDEX":

            return sum(
                1
                for candle in candles
                if candle.get("volume") == 0
            )

        count = 0

        for candle in candles:

            volume = candle.get(
                "volume"
            )

            if volume == 0:

                count += 1

                self.record_event(
                    instrument_id=instrument_id,
                    timestamp=int(
                        candle["timestamp"]
                    ),
                    event_type="ZERO_VOLUME",
                    severity="INFO",
                    description=(
                        "Derivative candle has "
                        "zero volume. "
                        "Record retained."
                    ),
                )

        return count

    # =========================================================
    # OI CHECK
    # =========================================================

    def check_open_interest(
        self,
        instrument: dict,
        candles: list[dict],
    ) -> dict:

        option_type = (
            instrument.get(
                "option_type"
            )
        )

        requires_oi = (
            option_type in self.OPTIONS_TYPES
            or option_type
            == self.FUTURE_OPTION_TYPE
        )

        if not requires_oi:

            return {
                "required": False,
                "missing": 0,
                "coverage_pct": None,
            }

        missing = 0

        for candle in candles:

            if candle.get(
                "open_interest"
            ) is None:

                missing += 1

                self.record_event(
                    instrument_id=int(
                        instrument["id"]
                    ),
                    timestamp=int(
                        candle["timestamp"]
                    ),
                    event_type="MISSING_OI",
                    severity="ERROR",
                    description=(
                        "Open interest missing "
                        "for derivative candle."
                    ),
                )

        total = len(
            candles
        )

        coverage = (
            (
                total - missing
            )
            / total
            * 100
            if total
            else 0
        )

        return {
            "required": True,
            "missing": missing,
            "coverage_pct": coverage,
        }

    # =========================================================
    # SESSION COMPLETENESS
    # =========================================================

    def check_session_completeness(
        self,
        instrument_id: int,
        grouped: dict[str, list[dict]],
    ) -> list[dict]:

        results = []

        for trade_date, candles in sorted(
            grouped.items()
        ):

            actual = sorted(
                int(
                    candle["timestamp"]
                )
                for candle in candles
            )

            expected = (
                self.expected_session_timestamps(
                    trade_date
                )
            )

            actual_set = set(
                actual
            )

            expected_set = set(
                expected
            )

            missing = sorted(
                expected_set
                - actual_set
            )

            unexpected = sorted(
                actual_set
                - expected_set
            )

            count = len(
                actual
            )

            complete = (
                count == EXPECTED_1M_CANDLES
                and not missing
                and not unexpected
            )

            if missing:

                for timestamp in missing:

                    self.record_event(
                        instrument_id=instrument_id,
                        timestamp=timestamp,
                        event_type="MISSING_TIMESTAMP",
                        severity="ERROR",
                        description=(
                            "Expected 1-minute "
                            "candle is missing: "
                            + self.timestamp_to_local(
                                timestamp
                            ).isoformat()
                        ),
                    )

            if unexpected:

                for timestamp in unexpected:

                    self.record_event(
                        instrument_id=instrument_id,
                        timestamp=timestamp,
                        event_type="UNEXPECTED_TIMESTAMP",
                        severity="WARNING",
                        description=(
                            "Candle falls outside "
                            "the expected NSE session: "
                            + self.timestamp_to_local(
                                timestamp
                            ).isoformat()
                        ),
                    )

            results.append(
                {
                    "trade_date": trade_date,
                    "expected": len(
                        expected
                    ),
                    "actual": count,
                    "missing": len(
                        missing
                    ),
                    "unexpected": len(
                        unexpected
                    ),
                    "complete": complete,
                    "missing_timestamps": [
                        self.timestamp_to_local(
                            timestamp
                        ).isoformat()
                        for timestamp in missing
                    ],
                }
            )

        return results

    # =========================================================
    # MAIN INSTRUMENT VALIDATION
    # =========================================================

    def validate_instrument(
        self,
        symbol: str,
        resolution: str = "1",
        source: str | None = None,
    ) -> dict:

        instrument = self.get_instrument(
            symbol
        )

        if instrument is None:

            raise ValueError(
                f"Instrument not found: {symbol}"
            )

        instrument_id = int(
            instrument["id"]
        )

        candles = self.get_candles(
            instrument_id=instrument_id,
            resolution=resolution,
            source=source,
        )

        grouped = (
            self.group_by_trade_date(
                candles
            )
        )

        duplicates = (
            self.check_duplicates(
                instrument_id,
                candles
            )
        )

        order_problems = (
            self.check_timestamp_order(
                instrument_id,
                candles
            )
        )

        ohlc_problems = (
            self.check_ohlc(
                instrument_id,
                candles
            )
        )

        zero_volume = (
            self.check_zero_volume(
                instrument_id,
                candles,
                instrument,
            )
        )

        oi_result = (
            self.check_open_interest(
                instrument,
                candles
            )
        )

        sessions = (
            self.check_session_completeness(
                instrument_id,
                grouped,
            )
        )

        result = {
            "symbol": symbol,
            "instrument_id": instrument_id,
            "instrument_type": instrument.get(
                "instrument_type"
            ),
            "option_type": instrument.get(
                "option_type"
            ),
            "resolution": resolution,
            "source": source,
            "total_candles": len(
                candles
            ),
            "trade_dates": len(
                grouped
            ),
            "duplicate_timestamps": duplicates,
            "timestamp_order_problems": (
                order_problems
            ),
            "ohlc_problems": (
                ohlc_problems
            ),
            "zero_volume_candles": (
                zero_volume
            ),
            "oi": oi_result,
            "sessions": sessions,
        }

        return result

    # =========================================================
    # SAMPLE VALIDATION
    # =========================================================

    def validate_sample(
        self,
    ) -> list[dict]:

        samples = [
            "NSE:NIFTY50-INDEX",
            "NSE:INDIAVIX-INDEX",
            "NSE:NIFTY24NOVFUT",
            "NSE:NIFTY24NOV22500CE",
            "NSE:NIFTY24NOV22500PE",
        ]

        results = []

        source_map = {
            "NSE:NIFTY50-INDEX":
                "FYERS_HISTORY",
            "NSE:INDIAVIX-INDEX":
                "FYERS_HISTORY",
            "NSE:NIFTY24NOVFUT":
                "FYERS_FNO_HISTORY",
            "NSE:NIFTY24NOV22500CE":
                "FYERS_FNO_HISTORY",
            "NSE:NIFTY24NOV22500PE":
                "FYERS_FNO_HISTORY",
        }

        for symbol in samples:

            print(
                f"\nValidating: {symbol}"
            )

            result = (
                self.validate_instrument(
                    symbol=symbol,
                    resolution="1",
                    source=source_map[
                        symbol
                    ],
                )
            )

            results.append(
                result
            )

            print(
                f"  Candles: "
                f"{result['total_candles']}"
            )

            print(
                f"  Sessions: "
                f"{result['trade_dates']}"
            )

            print(
                f"  Duplicates: "
                f"{result['duplicate_timestamps']}"
            )

            print(
                f"  OHLC problems: "
                f"{result['ohlc_problems']}"
            )

            print(
                f"  Zero-volume: "
                f"{result['zero_volume_candles']}"
            )

            if result["oi"]["required"]:

                print(
                    f"  OI coverage: "
                    f"{result['oi']['coverage_pct']:.2f}%"
                )

            for session in result[
                "sessions"
            ]:

                print(
                    f"  {session['trade_date']}: "
                    f"{session['actual']}/"
                    f"{session['expected']} "
                    f"candles | "
                    f"missing={session['missing']}"
                )

                if session[
                    "missing_timestamps"
                ]:

                    for timestamp in session[
                        "missing_timestamps"
                    ]:

                        print(
                            f"    Missing: "
                            f"{timestamp}"
                        )

        return results


# =============================================================
# CLI
# =============================================================

def main() -> None:

    parser = argparse.ArgumentParser(
        description=(
            "Kunal Quant - Data Quality Engine"
        )
    )

    parser.add_argument(
        "--symbol",
        type=str,
        default=None,
        help="Validate one symbol.",
    )

    parser.add_argument(
        "--source",
        type=str,
        default=None,
        help="Optional candle source.",
    )

    parser.add_argument(
        "--sample",
        action="store_true",
        help="Validate the controlled sample.",
    )

    args = parser.parse_args()

    print("=" * 75)

    print(
        "KUNAL QUANT - DATA QUALITY ENGINE"
    )

    print("=" * 75)

    engine = DataQualityEngine()

    if args.sample:

        results = (
            engine.validate_sample()
        )

    elif args.symbol:

        results = [
            engine.validate_instrument(
                symbol=args.symbol,
                resolution="1",
                source=args.source,
            )
        ]

    else:

        raise SystemExit(
            "Use --sample or --symbol."
        )

    print(
        "\n" + "=" * 75
    )

    print(
        "QUALITY RESULT"
    )

    print(
        "=" * 75
    )

    print(
        json.dumps(
            results,
            indent=2,
        )
    )

    print(
        "\n" + "=" * 75
    )

    print(
        "DATA QUALITY CHECK COMPLETE"
    )

    print(
        "=" * 75
    )


if __name__ == "__main__":

    main()