from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable

from config.settings import DATABASE_PATH, PRIMARY_RESOLUTION
from downloader.historical import HistoricalDownloader


class OptionChainDownloader:
    """
    Kunal Quant - Full Historical Option Chain Downloader V1.

    Responsibilities:

    - Discover all CE/PE contracts for one expiry.
    - Download every contract through HistoricalDownloader.
    - Preserve raw broker responses.
    - Store canonical OHLCV/OI candles.
    - Resume completed chunks safely.
    - Support controlled batches before full-chain runs.
    - Produce a completeness report.
    """

    UNDERLYING = "NIFTY"

    SUPPORTED_OPTION_TYPES = ("CE", "PE")

    DEFAULT_MODE = "expired"

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

        self.downloader = HistoricalDownloader(
            database_path=self.database_path
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
    # DATE HELPERS
    # =========================================================

    @staticmethod
    def _parse_date(
        value: str,
    ) -> datetime:

        return datetime.strptime(
            value,
            "%Y-%m-%d"
        )

    @staticmethod
    def _format_date(
        value: datetime,
    ) -> str:

        return value.strftime(
            "%Y-%m-%d"
        )

    @classmethod
    def _days_before(
        cls,
        date_value: str,
        days: int,
    ) -> str:

        parsed = cls._parse_date(
            date_value
        )

        return cls._format_date(
            parsed - timedelta(
                days=days
            )
        )

    # =========================================================
    # OPTION DISCOVERY
    # =========================================================

    def find_contracts(
        self,
        expiry_date: str,
        option_type: str | None = None,
    ) -> list[dict]:

        query = """
        SELECT
            id,
            broker,
            exchange,
            segment,
            symbol,
            broker_token,
            security_id,
            underlying,
            instrument_type,
            expiry_date,
            strike,
            option_type,
            lot_size,
            tick_size,
            currency,
            is_active
        FROM instruments
        WHERE broker = 'FYERS'
          AND underlying = ?
          AND expiry_date = ?
          AND option_type IN ('CE', 'PE')
        """

        parameters: list = [
            self.UNDERLYING,
            expiry_date,
        ]

        if option_type is not None:

            normalized_type = (
                option_type.upper()
            )

            if normalized_type not in (
                self.SUPPORTED_OPTION_TYPES
            ):

                raise ValueError(
                    "option_type must be CE, PE "
                    "or None."
                )

            query += """
              AND option_type = ?
            """

            parameters.append(
                normalized_type
            )

        query += """
        ORDER BY
            strike ASC,
            option_type ASC,
            symbol ASC
        """

        with self._connect() as connection:

            rows = connection.execute(
                query,
                parameters
            ).fetchall()

        return [
            dict(row)
            for row in rows
        ]

    # =========================================================
    # STRIKE FILTER
    # =========================================================

    @staticmethod
    def filter_by_strike(
        contracts: Iterable[dict],
        strike_min: float | None = None,
        strike_max: float | None = None,
    ) -> list[dict]:

        results = []

        for contract in contracts:

            strike = contract.get(
                "strike"
            )

            if strike is None:

                continue

            strike = float(
                strike
            )

            if (
                strike_min is not None
                and strike < strike_min
            ):

                continue

            if (
                strike_max is not None
                and strike > strike_max
            ):

                continue

            results.append(
                contract
            )

        return results

    # =========================================================
    # MAX SYMBOL LIMIT
    # =========================================================

    @staticmethod
    def limit_contracts(
        contracts: list[dict],
        max_symbols: int | None,
    ) -> list[dict]:

        if max_symbols is None:

            return contracts

        if max_symbols <= 0:

            raise ValueError(
                "max_symbols must be greater "
                "than zero."
            )

        return contracts[
            :max_symbols
        ]

    # =========================================================
    # FULL CHAIN STRUCTURE
    # =========================================================

    @staticmethod
    def chain_strike_summary(
        contracts: list[dict],
    ) -> dict:

        strikes: dict[float, set[str]] = {}

        for contract in contracts:

            strike = contract.get(
                "strike"
            )

            option_type = contract.get(
                "option_type"
            )

            if (
                strike is None
                or option_type not in (
                    "CE",
                    "PE",
                )
            ):

                continue

            strike = float(
                strike
            )

            strikes.setdefault(
                strike,
                set()
            ).add(
                option_type
            )

        complete_pairs = sum(
            1
            for option_types in strikes.values()
            if (
                "CE" in option_types
                and "PE" in option_types
            )
        )

        ce_only = sum(
            1
            for option_types in strikes.values()
            if (
                "CE" in option_types
                and "PE" not in option_types
            )
        )

        pe_only = sum(
            1
            for option_types in strikes.values()
            if (
                "PE" in option_types
                and "CE" not in option_types
            )
        )

        return {
            "unique_strikes": len(
                strikes
            ),
            "complete_ce_pe_pairs": (
                complete_pairs
            ),
            "ce_only_strikes": ce_only,
            "pe_only_strikes": pe_only,
        }

    # =========================================================
    # CANDLE / JOB REPORT
    # =========================================================

    def _symbol_download_summary(
        self,
        symbol: str,
        expiry_date: str,
        range_from: str,
        range_to: str,
        mode: str,
        resolution: str,
    ) -> dict:

        with self._connect() as connection:

            instrument = connection.execute(
                """
                SELECT
                    id,
                    symbol,
                    strike,
                    option_type,
                    expiry_date
                FROM instruments
                WHERE broker = 'FYERS'
                  AND symbol = ?
                LIMIT 1
                """,
                (symbol,)
            ).fetchone()

            if instrument is None:

                return {
                    "symbol": symbol,
                    "status": "MISSING_INSTRUMENT",
                }

            instrument_id = int(
                instrument["id"]
            )

            candle_row = connection.execute(
                """
                SELECT
                    COUNT(*) AS candle_count,
                    MIN(timestamp) AS first_timestamp,
                    MAX(timestamp) AS last_timestamp,
                    SUM(
                        CASE
                            WHEN open_interest IS NOT NULL
                            THEN 1
                            ELSE 0
                        END
                    ) AS oi_rows
                FROM candles
                WHERE instrument_id = ?
                  AND resolution = ?
                """,
                (
                    instrument_id,
                    resolution,
                )
            ).fetchone()

            job_row = connection.execute(
                """
                SELECT
                    COUNT(*) AS job_count,
                    SUM(
                        CASE
                            WHEN status = 'COMPLETED'
                            THEN 1
                            ELSE 0
                        END
                    ) AS completed_jobs,

                    SUM(
                        CASE
                            WHEN status = 'EMPTY'
                            THEN 1
                            ELSE 0
                        END
                    ) AS empty_jobs,

                    SUM(
                        CASE
                            WHEN status = 'FAILED'
                            THEN 1
                            ELSE 0
                        END
                    ) AS failed_jobs,

                    MAX(completed_at)
                        AS last_completed_at
                FROM download_jobs
                WHERE broker = 'FYERS'
                  AND symbol = ?
                  AND resolution = ?
                  AND range_from = ?
                  AND range_to = ?
                """,
                (
                    symbol,
                    resolution,
                    range_from,
                    range_to,
                )
            ).fetchone()

        return {
            "symbol": symbol,
            "expiry_date": expiry_date,
            "strike": (
                float(instrument["strike"])
                if instrument["strike"] is not None
                else None
            ),
            "option_type": (
                instrument["option_type"]
            ),
            "mode": mode,
            "resolution": resolution,
            "candle_count": int(
                candle_row["candle_count"]
                or 0
            ),
            "oi_rows": int(
                candle_row["oi_rows"]
                or 0
            ),
            "first_timestamp": (
                candle_row["first_timestamp"]
            ),
            "last_timestamp": (
                candle_row["last_timestamp"]
            ),
            "job_count": int(
                job_row["job_count"]
                or 0
            ),
            "completed_jobs": int(
                job_row["completed_jobs"]
                or 0
            ),

            "empty_jobs": int(
                job_row["empty_jobs"]
                or 0
            ),

            "failed_jobs": int(
                job_row["failed_jobs"]
                or 0
            ),
            "last_completed_at": (
                job_row["last_completed_at"]
            ),
            "expected_range_from": range_from,
            "expected_range_to": range_to,
        }

    # =========================================================
    # ONE CONTRACT
    # =========================================================

    def download_contract(
        self,
        contract: dict,
        range_from: str,
        range_to: str,
        resolution: str = PRIMARY_RESOLUTION,
        mode: str = DEFAULT_MODE,
    ) -> dict:

        symbol = contract["symbol"]

        print(
            "\n" + "-" * 75
        )

        print(
            "OPTION CONTRACT"
        )

        print(
            f"Symbol     : {symbol}"
        )

        print(
            f"Strike     : {contract.get('strike')}"
        )

        print(
            f"Type       : {contract.get('option_type')}"
        )

        print(
            f"Expiry     : {contract.get('expiry_date')}"
        )

        print(
            f"Range      : {range_from} -> {range_to}"
        )

        print(
            f"Resolution : {resolution}"
        )

        print(
            f"Mode       : {mode}"
        )

        print(
            "-" * 75
        )

        result = (
            self.downloader.download_symbol(
                symbol=symbol,
                range_from=range_from,
                range_to=range_to,
                resolution=resolution,
                mode=mode,
            )
        )

        result[
            "strike"
        ] = contract.get(
            "strike"
        )

        result[
            "option_type"
        ] = contract.get(
            "option_type"
        )

        result[
            "expiry_date"
        ] = contract.get(
            "expiry_date"
        )

        return result

    # =========================================================
    # FULL CHAIN DOWNLOAD
    # =========================================================

    def download_chain(
        self,
        expiry_date: str,
        range_from: str,
        range_to: str,
        resolution: str = PRIMARY_RESOLUTION,
        mode: str = DEFAULT_MODE,
        option_type: str | None = None,
        strike_min: float | None = None,
        strike_max: float | None = None,
        max_symbols: int | None = None,
    ) -> dict:

        # -----------------------------------------------------
        # Validate dates.
        # -----------------------------------------------------

        start = self._parse_date(
            range_from
        )

        end = self._parse_date(
            range_to
        )

        if start > end:

            raise ValueError(
                "range_from cannot be after range_to."
            )

        expiry = self._parse_date(
            expiry_date
        )

        if end < expiry:

            print(
                "\nWARNING:"
            )

            print(
                "Requested historical range ends "
                "before expiry."
            )

            print(
                "This is allowed, but it will not "
                "contain expiry-day candles."
            )

        # -----------------------------------------------------
        # Discover contracts.
        # -----------------------------------------------------

        contracts = self.find_contracts(
            expiry_date=expiry_date,
            option_type=option_type,
        )

        discovered_contract_count = len(
            contracts
        )

        if not contracts:

            raise ValueError(
                "No CE/PE contracts found in "
                "the instruments table for "
                f"expiry {expiry_date}."
            )

        # -----------------------------------------------------
        # Strike filtering.
        # -----------------------------------------------------

        contracts = self.filter_by_strike(
            contracts=contracts,
            strike_min=strike_min,
            strike_max=strike_max,
        )

        filtered_contract_count = len(
            contracts
        )

        # -----------------------------------------------------
        # Controlled batch limit.
        # -----------------------------------------------------

        contracts = self.limit_contracts(
            contracts=contracts,
            max_symbols=max_symbols,
        )

        selected_contract_count = len(
            contracts
        )

        chain_shape = (
            self.chain_strike_summary(
                contracts
            )
        )

        print(
            "\n" + "=" * 75
        )

        print(
            "KUNAL QUANT - OPTION CHAIN DOWNLOAD"
        )

        print(
            "=" * 75
        )

        print(
            f"Underlying              : {self.UNDERLYING}"
        )

        print(
            f"Expiry                  : {expiry_date}"
        )

        print(
            f"Range                   : "
            f"{range_from} -> {range_to}"
        )

        print(
            f"Resolution              : {resolution}"
        )

        print(
            f"Mode                    : {mode}"
        )

        print(
            f"Discovered contracts    : "
            f"{discovered_contract_count}"
        )

        print(
            f"After strike filter     : "
            f"{filtered_contract_count}"
        )

        print(
            f"Selected for this run   : "
            f"{selected_contract_count}"
        )

        print(
            f"Unique strikes          : "
            f"{chain_shape['unique_strikes']}"
        )

        print(
            f"Complete CE/PE pairs    : "
            f"{chain_shape['complete_ce_pe_pairs']}"
        )

        print(
            f"CE-only strikes         : "
            f"{chain_shape['ce_only_strikes']}"
        )

        print(
            f"PE-only strikes         : "
            f"{chain_shape['pe_only_strikes']}"
        )

        print(
            "=" * 75
        )

        if not contracts:

            raise ValueError(
                "No contracts remain after filters."
            )

        results: list[dict] = []

        completed = 0
        skipped = 0
        failed = 0
        received = 0
        inserted = 0
        duplicates = 0

        for position, contract in enumerate(
            contracts,
            start=1,
        ):

            print(
                "\n"
                f"[{position}/{selected_contract_count}] "
                f"{contract['symbol']}"
            )

            try:

                result = (
                    self.download_contract(
                        contract=contract,
                        range_from=range_from,
                        range_to=range_to,
                        resolution=resolution,
                        mode=mode,
                    )
                )

            except Exception as exc:

                result = {
                    "status": "FAILED",
                    "symbol": contract[
                        "symbol"
                    ],
                    "expiry_date": contract[
                        "expiry_date"
                    ],
                    "strike": contract.get(
                        "strike"
                    ),
                    "option_type": contract.get(
                        "option_type"
                    ),
                    "error": str(exc),
                }

            results.append(
                result
            )

            status = result.get(
                "status"
            )

            if status == "COMPLETED":
                completed += 1

            elif status == "SKIPPED":
                skipped += 1

            elif status == "FAILED":
                failed += 1

            received += int(
                result.get(
                    "received",
                    0
                )
            )

            inserted += int(
                result.get(
                    "inserted",
                    0
                )
            )

            duplicates += int(
                result.get(
                    "duplicates",
                    0
                )
            )

            print(
                "\nContract result:"
            )

            print(
                json.dumps(
                    result,
                    indent=2,
                    default=str,
                )
            )

        # -----------------------------------------------------
        # Final report.
        # -----------------------------------------------------

        report = (
            self.build_completeness_report(
                expiry_date=expiry_date,
                range_from=range_from,
                range_to=range_to,
                resolution=resolution,
                mode=mode,
                option_type=option_type,
                strike_min=strike_min,
                strike_max=strike_max,
            )
        )

        return {
            "expiry_date": expiry_date,
            "range_from": range_from,
            "range_to": range_to,
            "resolution": resolution,
            "mode": mode,
            "discovered_contracts": (
                discovered_contract_count
            ),
            "filtered_contracts": (
                filtered_contract_count
            ),
            "selected_contracts": (
                selected_contract_count
            ),
            "completed": completed,
            "skipped": skipped,
            "failed": failed,
            "received_candles": received,
            "inserted_candles": inserted,
            "duplicate_candles": duplicates,
            "contract_results": results,
            "completeness": report,
        }

    # =========================================================
    # COMPLETENESS REPORT
    # =========================================================

    def build_completeness_report(
        self,
        expiry_date: str,
        range_from: str,
        range_to: str,
        resolution: str = PRIMARY_RESOLUTION,
        mode: str = DEFAULT_MODE,
        option_type: str | None = None,
        strike_min: float | None = None,
        strike_max: float | None = None,
    ) -> dict:

        contracts = self.find_contracts(
            expiry_date=expiry_date,
            option_type=option_type,
        )

        contracts = self.filter_by_strike(
            contracts=contracts,
            strike_min=strike_min,
            strike_max=strike_max,
        )

        contract_reports = []

        for contract in contracts:

            contract_reports.append(
                self._symbol_download_summary(
                    symbol=contract[
                        "symbol"
                    ],
                    expiry_date=expiry_date,
                    range_from=range_from,
                    range_to=range_to,
                    mode=mode,
                    resolution=resolution,
                )
            )

        expected_contracts = len(
            contract_reports
        )

        contracts_with_candles = sum(
            1
            for item in contract_reports
            if item.get(
                "candle_count",
                0
            ) > 0
        )

        contracts_with_oi = sum(
            1
            for item in contract_reports
            if item.get(
                "oi_rows",
                0
            ) > 0
        )

        completed_jobs = sum(
            item.get(
                "completed_jobs",
                0
            )
            for item in contract_reports
        )

        empty_jobs = sum(
            item.get(
                "empty_jobs",
                0
            )
            for item in contract_reports
        )

        failed_jobs = sum(
            item.get(
                "failed_jobs",
                0
            )
            for item in contract_reports
        )

        total_candles = sum(
            item.get(
                "candle_count",
                0
            )
            for item in contract_reports
        )

        total_oi_rows = sum(
            item.get(
                "oi_rows",
                0
            )
            for item in contract_reports
        )

        missing_symbols = [
            item["symbol"]
            for item in contract_reports
            if item.get(
                "candle_count",
                0
            ) == 0
        ]

        failed_symbols = [
            item["symbol"]
            for item in contract_reports
            if item.get(
                "failed_jobs",
                0
            ) > 0
        ]

        return {
            "underlying": self.UNDERLYING,
            "expiry_date": expiry_date,
            "range_from": range_from,
            "range_to": range_to,
            "resolution": resolution,
            "mode": mode,
            "expected_contracts": (
                expected_contracts
            ),
            "contracts_with_candles": (
                contracts_with_candles
            ),
            "contracts_with_oi": (
                contracts_with_oi
            ),
            "contracts_missing_candles": (
                len(missing_symbols)
            ),
            "completed_jobs": (
                completed_jobs
            ),
            "empty_jobs": (
                empty_jobs
            ),
            "failed_jobs": (
                failed_jobs
            ),
            "total_candles": (
                total_candles
            ),
            "total_oi_rows": (
                total_oi_rows
            ),
            "coverage_pct": (
                (
                    contracts_with_candles
                    / expected_contracts
                    * 100.0
                )
                if expected_contracts
                else 0.0
            ),
            "oi_coverage_pct": (
                (
                    contracts_with_oi
                    / expected_contracts
                    * 100.0
                )
                if expected_contracts
                else 0.0
            ),
            "missing_symbols": missing_symbols,
            "failed_symbols": failed_symbols,
        }

    # =========================================================
    # SAMPLE
    # =========================================================

    def run_sample(
        self,
    ) -> dict:

        # Controlled test:
        #
        # Only a small ATM-area strike band.
        #
        # 2024-11-27 -> 2024-11-28
        #
        # This tests the complete-chain machinery
        # without downloading hundreds of symbols.
        #
        # NIFTY around 23,900 during this historical
        # sample, so 23,700 -> 24,100 gives a controlled
        # CE/PE window.

        return self.download_chain(
            expiry_date="2024-11-28",
            range_from="2024-11-27",
            range_to="2024-11-28",
            resolution="1",
            mode="expired",
            strike_min=23700,
            strike_max=24100,
        )

    # =========================================================
    # CONTROLLED ATM WINDOW
    # =========================================================

    def run_atm_window(
        self,
        expiry_date: str,
        range_from: str,
        range_to: str,
        center_strike: float,
        strikes_each_side: int = 5,
        strike_step: float = 50.0,
        resolution: str = PRIMARY_RESOLUTION,
        mode: str = DEFAULT_MODE,
    ) -> dict:

        if strikes_each_side < 0:

            raise ValueError(
                "strikes_each_side cannot be negative."
            )

        if strike_step <= 0:

            raise ValueError(
                "strike_step must be positive."
            )

        strike_min = (
            center_strike
            - (
                strikes_each_side
                * strike_step
            )
        )

        strike_max = (
            center_strike
            + (
                strikes_each_side
                * strike_step
            )
        )

        print(
            "\nATM window:"
        )

        print(
            f"  Center strike : {center_strike}"
        )

        print(
            f"  Strike step   : {strike_step}"
        )

        print(
            f"  Each side     : {strikes_each_side}"
        )

        print(
            f"  Minimum       : {strike_min}"
        )

        print(
            f"  Maximum       : {strike_max}"
        )

        return self.download_chain(
            expiry_date=expiry_date,
            range_from=range_from,
            range_to=range_to,
            resolution=resolution,
            mode=mode,
            strike_min=strike_min,
            strike_max=strike_max,
        )


# =============================================================
# CLI
# =============================================================

def main() -> None:

    parser = argparse.ArgumentParser(
        description=(
            "Kunal Quant - "
            "Full Historical Option Chain Downloader"
        )
    )

    parser.add_argument(
        "--sample",
        action="store_true",
        help=(
            "Run the controlled "
            "2024-11-27/28 chain sample."
        ),
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
        help="Historical start date YYYY-MM-DD.",
    )

    parser.add_argument(
        "--to",
        dest="range_to",
        type=str,
        default=None,
        help="Historical end date YYYY-MM-DD.",
    )

    parser.add_argument(
        "--resolution",
        type=str,
        default="1",
        help="FYERS resolution. Default: 1 minute.",
    )

    parser.add_argument(
        "--mode",
        type=str,
        default="expired",
        choices=["standard", "expired"],
        help="Historical endpoint mode.",
    )

    parser.add_argument(
        "--option-type",
        type=str,
        default=None,
        choices=["CE", "PE"],
        help="Download only CE or PE.",
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

    parser.add_argument(
        "--max-symbols",
        type=int,
        default=None,
        help=(
            "Controlled batch size. "
            "Example: 20"
        ),
    )

    parser.add_argument(
        "--report",
        action="store_true",
        help=(
            "Only build and print the "
            "completeness report."
        ),
    )

    args = parser.parse_args()

    downloader = OptionChainDownloader()

    # ---------------------------------------------------------
    # SAMPLE
    # ---------------------------------------------------------

    if args.sample:

        result = (
            downloader.run_sample()
        )

        print(
            "\n" + "=" * 75
        )

        print(
            "OPTION CHAIN SAMPLE RESULT"
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

        return

    # ---------------------------------------------------------
    # Generic CLI validation.
    # ---------------------------------------------------------

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

    # ---------------------------------------------------------
    # Report-only mode.
    # ---------------------------------------------------------

    if args.report:

        result = (
            downloader.build_completeness_report(
                expiry_date=args.expiry,
                range_from=args.range_from,
                range_to=args.range_to,
                resolution=args.resolution,
                mode=args.mode,
                option_type=args.option_type,
                strike_min=args.strike_min,
                strike_max=args.strike_max,
            )
        )

        print(
            "\n" + "=" * 75
        )

        print(
            "OPTION CHAIN COMPLETENESS REPORT"
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

        return

    # ---------------------------------------------------------
    # Download.
    # ---------------------------------------------------------

    result = downloader.download_chain(
        expiry_date=args.expiry,
        range_from=args.range_from,
        range_to=args.range_to,
        resolution=args.resolution,
        mode=args.mode,
        option_type=args.option_type,
        strike_min=args.strike_min,
        strike_max=args.strike_max,
        max_symbols=args.max_symbols,
    )

    print(
        "\n" + "=" * 75
    )

    print(
        "OPTION CHAIN DOWNLOAD COMPLETE"
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