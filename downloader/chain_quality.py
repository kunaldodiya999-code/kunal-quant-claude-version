from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Iterable
from zoneinfo import ZoneInfo

from config.settings import DATABASE_PATH


class OptionChainQualityEngine:
    """
    Kunal Quant - Historical Option Chain Quality Engine V2.

    Classifies every option contract for an expiry as:

        COMPLETE
        PARTIAL
        EMPTY
        FAILED

    Important:
    This engine does not fabricate missing data.

    For each contract it checks:

    - stored candle count
    - OI coverage
    - observed trading-day candle completeness
    - failed/empty download jobs
    - first/last available timestamp

    V2 uses the stored NIFTY spot series as the reference
    trading calendar, so weekends/holidays are not treated as
    missing option sessions.
    """

    TIMEZONE = ZoneInfo("Asia/Kolkata")

    EXPECTED_1M_CANDLES_PER_DAY = 375

    OPTION_TYPES = (
        "CE",
        "PE",
    )

    OPTION_SOURCE = "FYERS_FNO_HISTORY"

    REFERENCE_SYMBOL = "NSE:NIFTY50-INDEX"

    REFERENCE_SOURCE = "FYERS_HISTORY"

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
    # OPTION CONTRACTS
    # =========================================================

    def find_contracts(
        self,
        expiry_date: str,
        option_type: str | None = None,
    ) -> list[dict]:

        query = """
        SELECT
            id,
            symbol,
            underlying,
            expiry_date,
            strike,
            option_type
        FROM instruments
        WHERE broker = 'FYERS'
          AND underlying = 'NIFTY'
          AND expiry_date = ?
          AND option_type IN ('CE', 'PE')
        """

        parameters: list = [
            expiry_date
        ]

        if option_type is not None:

            normalized = (
                option_type.upper()
            )

            if normalized not in self.OPTION_TYPES:

                raise ValueError(
                    "option_type must be CE or PE."
                )

            query += """
              AND option_type = ?
            """

            parameters.append(
                normalized
            )

        query += """
        ORDER BY strike, option_type, symbol
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
    # CANDLE RETRIEVAL
    # =========================================================

    def get_contract_candles(
        self,
        instrument_id: int,
        range_from: str,
        range_to: str,
        resolution: str = "1",
    ) -> list[dict]:

        start_timestamp = int(
            datetime.strptime(
                range_from + " 00:00:00",
                "%Y-%m-%d %H:%M:%S",
            )
            .replace(
                tzinfo=self.TIMEZONE
            )
            .timestamp()
        )

        end_timestamp = int(
            datetime.strptime(
                range_to + " 23:59:59",
                "%Y-%m-%d %H:%M:%S",
            )
            .replace(
                tzinfo=self.TIMEZONE
            )
            .timestamp()
        )

        with self._connect() as connection:

            rows = connection.execute(
                """
                SELECT
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
                  AND source = ?
                  AND timestamp BETWEEN ?
                                      AND ?
                ORDER BY timestamp
                """,
                (
                    instrument_id,
                    resolution,
                    self.OPTION_SOURCE,
                    start_timestamp,
                    end_timestamp,
                ),
            ).fetchall()

        return [
            dict(row)
            for row in rows
        ]

    # =========================================================
    # REFERENCE TRADING CALENDAR
    # =========================================================

    def get_reference_trading_dates(
        self,
        range_from: str,
        range_to: str,
        resolution: str = "1",
    ) -> list[str]:

        """
        Use the actual stored NIFTY spot candles as the
        reference trading calendar.

        This avoids assuming that every weekday was an
        NSE trading session.

        Only dates for which NIFTY spot data exists are
        considered trading dates.
        """

        start_timestamp = int(
            datetime.strptime(
                range_from + " 00:00:00",
                "%Y-%m-%d %H:%M:%S",
            )
            .replace(
                tzinfo=self.TIMEZONE
            )
            .timestamp()
        )

        end_timestamp = int(
            datetime.strptime(
                range_to + " 23:59:59",
                "%Y-%m-%d %H:%M:%S",
            )
            .replace(
                tzinfo=self.TIMEZONE
            )
            .timestamp()
        )

        with self._connect() as connection:

            row = connection.execute(
                """
                SELECT id
                FROM instruments
                WHERE broker = 'FYERS'
                  AND symbol = ?
                LIMIT 1
                """,
                (
                    self.REFERENCE_SYMBOL,
                ),
            ).fetchone()

            if row is None:
                return []

            rows = connection.execute(
                """
                SELECT timestamp
                FROM candles
                WHERE instrument_id = ?
                  AND resolution = ?
                  AND source = ?
                  AND timestamp BETWEEN ?
                                      AND ?
                ORDER BY timestamp
                """,
                (
                    int(row["id"]),
                    resolution,
                    self.REFERENCE_SOURCE,
                    start_timestamp,
                    end_timestamp,
                ),
            ).fetchall()

        dates = sorted(
            {
                datetime.fromtimestamp(
                    int(row["timestamp"]),
                    tz=ZoneInfo("UTC"),
                )
                .astimezone(
                    self.TIMEZONE
                )
                .date()
                .isoformat()
                for row in rows
            }
        )

        return dates

    # =========================================================
    # DOWNLOAD JOB STATUS
    # =========================================================

    def get_job_status(
        self,
        symbol: str,
        range_from: str,
        range_to: str,
        resolution: str,
    ) -> dict:

        with self._connect() as connection:

            rows = connection.execute(
                """
                SELECT
                    status,
                    COUNT(*) AS count
                FROM download_jobs
                WHERE broker = 'FYERS'
                  AND symbol = ?
                  AND resolution = ?
                  AND range_from = ?
                  AND range_to = ?
                GROUP BY status
                """,
                (
                    symbol,
                    resolution,
                    range_from,
                    range_to,
                ),
            ).fetchall()

        summary = {
            "COMPLETED": 0,
            "EMPTY": 0,
            "FAILED": 0,
            "RUNNING": 0,
            "PENDING": 0,
        }

        for row in rows:

            status = str(
                row["status"]
            )

            summary[status] = int(
                row["count"]
            )

        return summary

    # =========================================================
    # GROUP BY TRADE DATE
    # =========================================================

    def group_by_date(
        self,
        candles: Iterable[dict],
    ) -> dict[str, list[dict]]:

        grouped: dict[
            str,
            list[dict]
        ] = {}

        for candle in candles:

            timestamp = int(
                candle["timestamp"]
            )

            local_dt = (
                datetime.fromtimestamp(
                    timestamp,
                    tz=ZoneInfo("UTC"),
                )
                .astimezone(
                    self.TIMEZONE
                )
            )

            trade_date = (
                local_dt.date().isoformat()
            )

            grouped.setdefault(
                trade_date,
                []
            ).append(
                candle
            )

        return grouped

    # =========================================================
    # SESSION ANALYSIS
    # =========================================================

    @staticmethod
    def analyze_day(
        candles: list[dict],
    ) -> dict:

        timestamps = sorted(
            int(
                candle["timestamp"]
            )
            for candle in candles
        )

        candle_count = len(
            timestamps
        )

        oi_count = sum(
            1
            for candle in candles
            if candle.get(
                "open_interest"
            ) is not None
        )

        # V1 assumes 1-minute NSE session
        # of 375 candles (09:15-15:29).
        complete = (
            candle_count
            == OptionChainQualityEngine.EXPECTED_1M_CANDLES_PER_DAY
        )

        first_timestamp = (
            timestamps[0]
            if timestamps
            else None
        )

        last_timestamp = (
            timestamps[-1]
            if timestamps
            else None
        )

        return {
            "candle_count": candle_count,
            "expected_candles": (
                OptionChainQualityEngine
                .EXPECTED_1M_CANDLES_PER_DAY
            ),
            "missing_candles": max(
                OptionChainQualityEngine
                .EXPECTED_1M_CANDLES_PER_DAY
                - candle_count,
                0,
            ),
            "oi_count": oi_count,
            "oi_coverage_pct": (
                oi_count
                / candle_count
                * 100.0
                if candle_count
                else 0.0
            ),
            "first_timestamp": first_timestamp,
            "last_timestamp": last_timestamp,
            "complete": complete,
        }

    # =========================================================
    # CONTRACT CLASSIFICATION
    # =========================================================

    def classify_contract(
        self,
        contract: dict,
        range_from: str,
        range_to: str,
        resolution: str = "1",
        expected_trade_dates: list[str] | None = None,
    ) -> dict:

        symbol = contract["symbol"]

        job_status = self.get_job_status(
            symbol=symbol,
            range_from=range_from,
            range_to=range_to,
            resolution=resolution,
        )

        candles = self.get_contract_candles(
            instrument_id=int(
                contract["id"]
            ),
            range_from=range_from,
            range_to=range_to,
            resolution=resolution,
        )

        total_candles = len(
            candles
        )

        total_oi = sum(
            1
            for candle in candles
            if candle.get(
                "open_interest"
            ) is not None
        )

        grouped = self.group_by_date(
            candles
        )

    # -----------------------------------------------------
    # Use the actual NIFTY trading sessions as reference.
    # -----------------------------------------------------

        if expected_trade_dates is None:

            expected_trade_dates = sorted(
                grouped.keys()
            )

        expected_trade_dates = sorted(
            set(expected_trade_dates)
        )

        observed_trade_dates = set(
            grouped.keys()
        )

        missing_trade_dates = sorted(
            set(expected_trade_dates)
            - observed_trade_dates
        )

        session_reports = {}

        partial_days = 0
        complete_days = 0

    # -----------------------------------------------------
    # Evaluate every expected trading day.
    # -----------------------------------------------------

        for trade_date in expected_trade_dates:

            day_candles = grouped.get(
                trade_date,
                []
            )

            analysis = self.analyze_day(
                day_candles
            )

            session_reports[
                trade_date
            ] = analysis

            if not day_candles:

                continue

            if analysis["complete"]:

                complete_days += 1

            else:

                partial_days += 1

        failed_jobs = int(
            job_status.get(
                "FAILED",
                0
            )
        )

        empty_jobs = int(
            job_status.get(
                "EMPTY",
                0
            )
        )

    # -----------------------------------------------------
    # Final classification.
    # -----------------------------------------------------

        if failed_jobs > 0:

            status = "FAILED"

        elif total_candles == 0:

            status = "EMPTY"

        elif (
            missing_trade_dates
            or partial_days > 0
        ):

            status = "PARTIAL"

        else:

            status = "COMPLETE"

        return {
            "symbol": symbol,
            "strike": (
                float(contract["strike"])
                if contract["strike"] is not None
                else None
            ),
            "option_type": (
                contract["option_type"]
            ),
            "expiry_date": (
                contract["expiry_date"]
            ),
            "status": status,
            "total_candles": total_candles,
            "expected_trading_days": len(
                expected_trade_dates
            ),
            "observed_trade_dates": len(
                observed_trade_dates
            ),
            "missing_trade_dates": len(
                missing_trade_dates
            ),
            "missing_trade_date_list": (
                missing_trade_dates
            ),
            "total_oi_rows": total_oi,
            "oi_coverage_pct": (
                total_oi
                / total_candles
                * 100.0
                if total_candles
                else 0.0
            ),
            "complete_days": complete_days,
            "partial_days": partial_days,
            "empty_jobs": empty_jobs,
            "failed_jobs": failed_jobs,
            "first_timestamp": (
                min(
                    (
                        candle["timestamp"]
                        for candle in candles
                    ),
                    default=None,
                )
            ),
            "last_timestamp": (
                max(
                    (
                        candle["timestamp"]
                        for candle in candles
                    ),
                    default=None,
                )
            ),
            "session_reports": session_reports,
        }

    # =========================================================
    # CHAIN REPORT
    # =========================================================

    def build_report(
        self,
        expiry_date: str,
        range_from: str,
        range_to: str,
        resolution: str = "1",
        option_type: str | None = None,
        strike_min: float | None = None,
        strike_max: float | None = None,
    ) -> dict:

        contracts = self.find_contracts(
            expiry_date=expiry_date,
            option_type=option_type,
        )

        # -----------------------------------------------------
        # Strike filters
        # -----------------------------------------------------

        if strike_min is not None:

            contracts = [
                contract
                for contract in contracts
                if (
                    contract["strike"] is not None
                    and float(
                        contract["strike"]
                    )
                    >= strike_min
                )
            ]

        if strike_max is not None:

            contracts = [
                contract
                for contract in contracts
                if (
                    contract["strike"] is not None
                    and float(
                        contract["strike"]
                    )
                    <= strike_max
                )
            ]

        # -----------------------------------------------------
        # REFERENCE TRADING CALENDAR
        # -----------------------------------------------------

        expected_trade_dates = (
            self.get_reference_trading_dates(
                range_from=range_from,
                range_to=range_to,
                resolution=resolution,
            )
        )

        if not expected_trade_dates:

            raise ValueError(
                "No NIFTY reference trading dates "
                "found in the requested range. "
                "Make sure NIFTY spot candles "
                "have been downloaded."
            )

        print(
            "\nReference trading calendar:"
        )

        print(
            f"  Symbol         : "
            f"{self.REFERENCE_SYMBOL}"
        )

        print(
            f"  Trading days   : "
            f"{len(expected_trade_dates)}"
        )

        print(
            f"  First date     : "
            f"{expected_trade_dates[0]}"
        )

        print(
            f"  Last date      : "
            f"{expected_trade_dates[-1]}"
        )

        print(
            f"  Expected 1-min "
            f"session candles/day: "
            f"{self.EXPECTED_1M_CANDLES_PER_DAY}"
        )

        reports = []

        for contract in contracts:

            reports.append(
                self.classify_contract(
                    contract=contract,
                    range_from=range_from,
                    range_to=range_to,
                    resolution=resolution,
                    expected_trade_dates=(
                        expected_trade_dates
                    ),
                )
            )

        counts = {
            "COMPLETE": 0,
            "PARTIAL": 0,
            "EMPTY": 0,
            "FAILED": 0,
        }

        for report in reports:

            counts[
                report["status"]
            ] += 1

        total_candles = sum(
            report["total_candles"]
            for report in reports
        )

        total_oi_rows = sum(
            report["total_oi_rows"]
            for report in reports
        )

        return {
            "underlying": "NIFTY",
            "expiry_date": expiry_date,
            "range_from": range_from,
            "range_to": range_to,
            "reference_symbol": (
                self.REFERENCE_SYMBOL
            ),
            "expected_trading_days": (
                len(expected_trade_dates)
            ),
            "resolution": resolution,
            "expected_contracts": len(
                reports
            ),
            "complete_contracts": (
                counts["COMPLETE"]
            ),
            "partial_contracts": (
                counts["PARTIAL"]
            ),
            "empty_contracts": (
                counts["EMPTY"]
            ),
            "failed_contracts": (
                counts["FAILED"]
            ),
            "total_candles": total_candles,
            "total_oi_rows": total_oi_rows,
            "oi_coverage_pct": (
                total_oi_rows
                / total_candles
                * 100.0
                if total_candles
                else 0.0
            ),
            "contracts": reports,
        }

    # =========================================================
    # SAMPLE
    # =========================================================

    def run_sample(self) -> dict:

        return self.build_report(
            expiry_date="2024-11-28",
            range_from="2024-11-01",
            range_to="2024-11-28",
            resolution="1",
        )


# =============================================================
# CLI
# =============================================================

def main() -> None:

    parser = argparse.ArgumentParser(
        description=(
            "Kunal Quant - "
            "Option Chain Quality Engine"
        )
    )

    parser.add_argument(
        "--sample",
        action="store_true",
        help="Run the 2024-11-28 sample.",
    )

    parser.add_argument(
        "--expiry",
        type=str,
        default=None,
        help="Option expiry YYYY-MM-DD.",
    )

    parser.add_argument(
        "--from",
        dest="range_from",
        type=str,
        default=None,
        help="Start date YYYY-MM-DD.",
    )

    parser.add_argument(
        "--to",
        dest="range_to",
        type=str,
        default=None,
        help="End date YYYY-MM-DD.",
    )

    parser.add_argument(
        "--resolution",
        type=str,
        default="1",
        help="Resolution. Default: 1 minute.",
    )

    parser.add_argument(
        "--option-type",
        type=str,
        default=None,
        choices=["CE", "PE"],
        help="Only CE or PE.",
    )

    parser.add_argument(
        "--strike-min",
        type=float,
        default=None,
        help="Minimum strike.",
    )

    parser.add_argument(
        "--strike-max",
        type=float,
        default=None,
        help="Maximum strike.",
    )

    args = parser.parse_args()

    engine = (
        OptionChainQualityEngine()
    )

    if args.sample:

        result = (
            engine.run_sample()
        )

    else:

        if not args.expiry:

            raise SystemExit(
                "--expiry is required."
            )

        if not args.range_from:

            raise SystemExit(
                "--from is required."
            )

        if not args.range_to:

            raise SystemExit(
                "--to is required."
            )

        result = engine.build_report(
            expiry_date=args.expiry,
            range_from=args.range_from,
            range_to=args.range_to,
            resolution=args.resolution,
            option_type=args.option_type,
            strike_min=args.strike_min,
            strike_max=args.strike_max,
        )

    print(
        "\n" + "=" * 75
    )

    print(
        "KUNAL QUANT - OPTION CHAIN QUALITY REPORT"
    )

    print(
        "=" * 75
    )

    print(
        json.dumps(
            result,
            indent=2,
            default=str,
        )
    )

    print(
        "\n" + "=" * 75
    )


if __name__ == "__main__":
    main()