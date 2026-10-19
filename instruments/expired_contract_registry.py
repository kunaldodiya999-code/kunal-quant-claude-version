from __future__ import annotations

import argparse
import json
import re
import sqlite3
import time
from datetime import datetime
from pathlib import Path

from api.fyers_client import FyersClient

from config.settings import DATABASE_PATH

from database.repository import (
    DatabaseRepository,
)


class ExpiredContractRegistry:
    """
    Discover and store historical FYERS contracts for
    every expiry date recorded in expiry_registry.

    This component provides:

    1. Expiry-job creation
    2. Resume-safe processing
    3. FYERS expired-contract discovery
    4. Historical instrument registration
    5. Success / failure tracking
    """

    def __init__(
        self,
        database_path: Path | str = DATABASE_PATH,
        max_api_attempts: int = 3,
        retry_delay_seconds: float = 2.0,
    ) -> None:

        self.database_path = Path(
            database_path
        )

        self.database_path.parent.mkdir(
            parents=True,
            exist_ok=True
        )

        self.repository = (
            DatabaseRepository(
                self.database_path
            )
        )

        self.fyers = FyersClient()

        self.max_api_attempts = max(
            1,
            int(max_api_attempts)
        )

        self.retry_delay_seconds = max(
            0.0,
            float(retry_delay_seconds)
        )

        self._ensure_table()

    # =========================================================
    # DATABASE CONNECTION
    # =========================================================

    def _connect(self) -> sqlite3.Connection:

        connection = sqlite3.connect(
            self.database_path
        )

        connection.row_factory = sqlite3.Row

        return connection

    # =========================================================
    # DATABASE TABLE
    # =========================================================

    def _ensure_table(self) -> None:

        sql = """
        CREATE TABLE IF NOT EXISTS expired_contract_registry (
            id INTEGER PRIMARY KEY AUTOINCREMENT,

            broker TEXT NOT NULL,

            underlying_symbol TEXT NOT NULL,

            expiry_date TEXT NOT NULL,

            status TEXT NOT NULL DEFAULT 'PENDING',

            attempts INTEGER NOT NULL DEFAULT 0,

            futures_count INTEGER NOT NULL DEFAULT 0,

            options_count INTEGER NOT NULL DEFAULT 0,

            total_count INTEGER NOT NULL DEFAULT 0,

            error_message TEXT,

            created_at TEXT NOT NULL
                DEFAULT CURRENT_TIMESTAMP,

            updated_at TEXT NOT NULL
                DEFAULT CURRENT_TIMESTAMP,

            started_at TEXT,

            completed_at TEXT,

            UNIQUE (
                broker,
                underlying_symbol,
                expiry_date
            )
        )
        """

        index_sql = """
        CREATE INDEX IF NOT EXISTS
        idx_expired_contract_registry_status
        ON expired_contract_registry (
            broker,
            underlying_symbol,
            status,
            expiry_date
        )
        """

        with self._connect() as connection:

            connection.execute(sql)

            connection.execute(index_sql)

            connection.commit()

    # =========================================================
    # UNDERLYING NORMALIZATION
    # =========================================================

    @staticmethod
    def _normalise_underlying(
        underlying_symbol: str,
    ) -> str:

        value = (
            underlying_symbol
            .split(":", 1)[-1]
            .upper()
            .strip()
        )

        known_index_mappings = {
            "NIFTY50-INDEX": "NIFTY",
            "NIFTYBANK-INDEX": "BANKNIFTY",
            "FINNIFTY-INDEX": "FINNIFTY",
            "MIDCPNIFTY-INDEX": "MIDCPNIFTY",
            "SENSEX-INDEX": "SENSEX",
            "BANKEX-INDEX": "BANKEX",
        }

        if value in known_index_mappings:

            return known_index_mappings[value]

        if value.endswith("-INDEX"):

            return value[:-6]

        return value

    # =========================================================
    # CONTRACT SYMBOL EXTRACTION
    # =========================================================

    @staticmethod
    def _extract_contract_symbol(
        contract,
    ) -> tuple[str, str | None]:

        if isinstance(contract, str):

            symbol = contract.strip()

            if not symbol:

                raise ValueError(
                    "Expired contract returned "
                    "an empty symbol."
                )

            return symbol, None

        if isinstance(contract, dict):

            symbol_keys = (
                "symbol",
                "symTicker",
                "fySymbol",
                "ticker",
            )

            token_keys = (
                "fyToken",
                "fy_token",
                "token",
                "broker_token",
            )

            symbol = None

            for key in symbol_keys:

                value = contract.get(key)

                if value:

                    symbol = str(
                        value
                    ).strip()

                    break

            if not symbol:

                raise ValueError(
                    "Could not find contract symbol "
                    f"in response record: {contract}"
                )

            token = None

            for key in token_keys:

                value = contract.get(key)

                if value is not None:

                    token = str(
                        value
                    )

                    break

            return symbol, token

        raise TypeError(
            "Unsupported contract type: "
            f"{type(contract).__name__}"
        )

    # =========================================================
    # CONTRACT CLASSIFICATION
    # =========================================================

    @staticmethod
    def _build_instrument(
        symbol: str,
        underlying: str,
        expiry_date: str,
        broker_token: str | None = None,
    ) -> dict:

        clean_symbol = symbol.strip()

        exchange = "NSE"

        if ":" in clean_symbol:

            exchange, ticker = (
                clean_symbol.split(
                    ":",
                    1
                )
            )

        else:

            ticker = clean_symbol

        strike = None

        option_type = "XX"

        instrument_type = 11

        # -----------------------------------------------------
        # OPTION
        # -----------------------------------------------------

        option_match = re.match(
            r"^(.*?)(CE|PE)$",
            ticker,
            flags=re.IGNORECASE,
        )

        if option_match:

            option_type = (
                option_match.group(2).upper()
            )

            instrument_type = 14

            option_body = (
                option_match.group(1)
            )

            # -------------------------------------------------
            # Historical FYERS symbols use different expiry
            # encodings.
            #
            # Weekly example:
            #   NIFTY24N2118200CE
            #          24N21 18200
            #
            # Monthly example:
            #   NIFTY24NOV22500CE
            #          24NOV 22500
            #
            # The supplied expiry_date is authoritative.
            # -------------------------------------------------

            expiry_value = datetime.strptime(
                expiry_date,
                "%Y-%m-%d",
            )

            year_code = (
                expiry_value.strftime("%y")
            )

            month_number = (
                expiry_value.strftime("%m")
            )

            day_code = (
                expiry_value.strftime("%d")
            )

            month_letter = (
                expiry_value.strftime("%b")[0].upper()
            )

            month_short = (
                expiry_value.strftime("%b").upper()
            )

            expiry_candidates = [
                year_code
                + month_letter
                + day_code,

                year_code
                + month_short
                + day_code,

                year_code
                + month_short,

                year_code
                + month_number
                + day_code,

                year_code
                + month_number,
            ]

            expiry_candidates = sorted(
                set(expiry_candidates),
                key=len,
                reverse=True,
            )

            expiry_index = None
            expiry_prefix = None
            strike_text = None

            for candidate in expiry_candidates:

                index = option_body.find(
                    candidate
                )

                if index <= 0:

                    continue

                possible_strike = (
                    option_body[
                        index
                        + len(candidate):
                    ]
                )

                if not possible_strike:

                    continue

                if not possible_strike.isdigit():

                    continue

                expiry_index = index
                expiry_prefix = candidate
                strike_text = possible_strike

                break

            if (
                expiry_index is None
                or expiry_prefix is None
                or strike_text is None
            ):

                raise ValueError(
                    "Unable to decode expiry/strike "
                    f"from expired option symbol: "
                    f"{symbol} | expiry={expiry_date}"
                )

            strike = float(
                strike_text
            )

        # -----------------------------------------------------
        # FUTURE
        # -----------------------------------------------------

        elif ticker.upper().endswith("FUT"):

            option_type = "XX"

        # -----------------------------------------------------
        # SAFETY CHECK
        # -----------------------------------------------------

        else:

            raise ValueError(
                "Unable to classify expired contract: "
                f"{clean_symbol}"
            )

        return {
            "broker": "FYERS",
            "exchange": exchange,
            "segment": 10,
            "symbol": clean_symbol,
            "broker_token": broker_token,
            "security_id": None,
            "underlying": underlying,
            "instrument_type": instrument_type,
            "expiry_date": expiry_date,
            "strike": strike,
            "option_type": option_type,
            "lot_size": None,
            "tick_size": None,
            "currency": "INR",
            "is_active": 0,
        }
    # =========================================================
    # EXPIRY JOB CREATION
    # =========================================================

    def seed_expiry_jobs(
        self,
        underlying_symbol: str,
    ) -> int:

        query = """
        SELECT DISTINCT expiry_date
        FROM expiry_registry
        WHERE broker = 'FYERS'
          AND underlying_symbol = ?
        ORDER BY expiry_date
        """

        with self._connect() as connection:

            rows = connection.execute(
                query,
                (underlying_symbol,),
            ).fetchall()

        if not rows:

            return 0

        insert_sql = """
        INSERT OR IGNORE INTO expired_contract_registry (
            broker,
            underlying_symbol,
            expiry_date,
            status
        )
        VALUES (
            'FYERS',
            ?,
            ?,
            'PENDING'
        )
        """

        records = [
            (
                underlying_symbol,
                row["expiry_date"],
            )
            for row in rows
        ]

        with self._connect() as connection:

            cursor = connection.executemany(
                insert_sql,
                records,
            )

            connection.commit()

            return max(
                cursor.rowcount,
                0
            )

    # =========================================================
    # ENSURE ONE EXPIRY JOB
    # =========================================================

    def ensure_expiry_job(
        self,
        underlying_symbol: str,
        expiry_date: str,
    ) -> None:

        sql = """
        INSERT OR IGNORE INTO
        expired_contract_registry (
            broker,
            underlying_symbol,
            expiry_date,
            status
        )
        VALUES (
            'FYERS',
            ?,
            ?,
            'PENDING'
        )
        """

        with self._connect() as connection:

            connection.execute(
                sql,
                (
                    underlying_symbol,
                    expiry_date,
                )
            )

            connection.commit()

    # =========================================================
    # JOB STATUS UPDATE
    # =========================================================

    def _mark_running(
        self,
        underlying_symbol: str,
        expiry_date: str,
    ) -> None:

        sql = """
        UPDATE expired_contract_registry
        SET
            status = 'RUNNING',
            attempts = attempts + 1,
            error_message = NULL,
            started_at = CURRENT_TIMESTAMP,
            updated_at = CURRENT_TIMESTAMP
        WHERE broker = 'FYERS'
          AND underlying_symbol = ?
          AND expiry_date = ?
        """

        with self._connect() as connection:

            connection.execute(
                sql,
                (
                    underlying_symbol,
                    expiry_date,
                )
            )

            connection.commit()

    def _mark_completed(
        self,
        underlying_symbol: str,
        expiry_date: str,
        futures_count: int,
        options_count: int,
        total_count: int,
    ) -> None:

        sql = """
        UPDATE expired_contract_registry
        SET
            status = 'COMPLETED',
            futures_count = ?,
            options_count = ?,
            total_count = ?,
            error_message = NULL,
            updated_at = CURRENT_TIMESTAMP,
            completed_at = CURRENT_TIMESTAMP
        WHERE broker = 'FYERS'
          AND underlying_symbol = ?
          AND expiry_date = ?
        """

        with self._connect() as connection:

            connection.execute(
                sql,
                (
                    futures_count,
                    options_count,
                    total_count,
                    underlying_symbol,
                    expiry_date,
                )
            )

            connection.commit()

    def _mark_failed(
        self,
        underlying_symbol: str,
        expiry_date: str,
        error_message: str,
    ) -> None:

        sql = """
        UPDATE expired_contract_registry
        SET
            status = 'FAILED',
            error_message = ?,
            updated_at = CURRENT_TIMESTAMP
        WHERE broker = 'FYERS'
          AND underlying_symbol = ?
          AND expiry_date = ?
        """

        with self._connect() as connection:

            connection.execute(
                sql,
                (
                    error_message[:4000],
                    underlying_symbol,
                    expiry_date,
                )
            )

            connection.commit()

    # =========================================================
    # FETCH ONE EXPIRY
    # =========================================================

    def process_expiry(
        self,
        underlying_symbol: str,
        expiry_date: str,
        force: bool = False,
    ) -> dict:

        self.ensure_expiry_job(
            underlying_symbol,
            expiry_date,
        )

        if not force:

            existing = self._get_job(
                underlying_symbol,
                expiry_date,
            )

            if existing is not None:

                if existing["status"] == "COMPLETED":

                    return {
                        "underlying_symbol": (
                            underlying_symbol
                        ),
                        "expiry_date": expiry_date,
                        "status": "SKIPPED",
                        "reason": (
                            "Already completed"
                        ),
                    }

        self._mark_running(
            underlying_symbol,
            expiry_date,
        )

        last_error = None

        response = None

        for attempt in range(
            1,
            self.max_api_attempts + 1
        ):

            try:

                print(
                    f"\nFetching expired contracts:"
                    f" {underlying_symbol}"
                    f" | expiry={expiry_date}"
                    f" | attempt={attempt}"
                )

                response = (
                    self.fyers.expired_contracts(
                        underlying_symbol,
                        expiry_date,
                    )
                )

                break

            except Exception as exc:

                last_error = str(exc)

                print(
                    f"  API attempt {attempt} failed:"
                    f" {last_error}"
                )

                if attempt < self.max_api_attempts:

                    delay = (
                        self.retry_delay_seconds
                        * (2 ** (attempt - 1))
                    )

                    print(
                        f"  Retrying in {delay:.1f} seconds..."
                    )

                    time.sleep(
                        delay
                    )

        if response is None:

            self._mark_failed(
                underlying_symbol,
                expiry_date,
                last_error
                or "Unknown API error",
            )

            return {
                "underlying_symbol": (
                    underlying_symbol
                ),
                "expiry_date": expiry_date,
                "status": "FAILED",
                "error": (
                    last_error
                    or "Unknown API error"
                ),
            }

        # -----------------------------------------------------
        # RESPONSE
        # -----------------------------------------------------

        contracts_data = (
            response
            .get("data", {})
            .get("contracts", {})
        )

        futures = (
            contracts_data.get(
                "futures",
                []
            )
        )

        options = (
            contracts_data.get(
                "options",
                []
            )
        )

        normalized_underlying = (
            self._normalise_underlying(
                underlying_symbol
            )
        )

        records: list[dict] = []

        # -----------------------------------------------------
        # FUTURES
        # -----------------------------------------------------

        for contract in futures:

            symbol, token = (
                self._extract_contract_symbol(
                    contract
                )
            )

            records.append(
                self._build_instrument(
                    symbol=symbol,
                    underlying=normalized_underlying,
                    expiry_date=expiry_date,
                    broker_token=token,
                )
            )

        # -----------------------------------------------------
        # OPTIONS
        # -----------------------------------------------------

        for contract in options:

            symbol, token = (
                self._extract_contract_symbol(
                    contract
                )
            )

            records.append(
                self._build_instrument(
                    symbol=symbol,
                    underlying=normalized_underlying,
                    expiry_date=expiry_date,
                    broker_token=token,
                )
            )

        # -----------------------------------------------------
        # DATABASE
        # -----------------------------------------------------

        database_records = 0

        if records:

            database_records = (
                self.repository.upsert_instruments(
                    records
                )
            )

        total = (
            len(futures)
            + len(options)
        )

        self._mark_completed(
            underlying_symbol,
            expiry_date,
            futures_count=len(futures),
            options_count=len(options),
            total_count=total,
        )

        print(
            f"  Futures contracts : "
            f"{len(futures)}"
        )

        print(
            f"  Options contracts : "
            f"{len(options)}"
        )

        print(
            f"  Total contracts   : "
            f"{total}"
        )

        print(
            f"  Database processed : "
            f"{database_records}"
        )

        return {
            "underlying_symbol": (
                underlying_symbol
            ),
            "expiry_date": expiry_date,
            "status": "COMPLETED",
            "futures": len(futures),
            "options": len(options),
            "total": total,
            "database_records_processed": (
                database_records
            ),
        }

    # =========================================================
    # GET JOB
    # =========================================================

    def _get_job(
        self,
        underlying_symbol: str,
        expiry_date: str,
    ) -> dict | None:

        query = """
        SELECT *
        FROM expired_contract_registry
        WHERE broker = 'FYERS'
          AND underlying_symbol = ?
          AND expiry_date = ?
        """

        with self._connect() as connection:

            row = connection.execute(
                query,
                (
                    underlying_symbol,
                    expiry_date,
                )
            ).fetchone()

        if row is None:

            return None

        return dict(row)

    # =========================================================
    # PENDING PROCESSOR
    # =========================================================

    def process_pending(
        self,
        underlying_symbol: str,
        limit: int | None = None,
        retry_failed: bool = False,
    ) -> dict:

        statuses = ["PENDING"]

        if retry_failed:

            statuses.append(
                "FAILED"
            )

        placeholders = ",".join(
            "?"
            for _ in statuses
        )

        query = f"""
        SELECT expiry_date
        FROM expired_contract_registry
        WHERE broker = 'FYERS'
          AND underlying_symbol = ?
          AND status IN ({placeholders})
        ORDER BY expiry_date
        """

        parameters = [
            underlying_symbol,
            *statuses,
        ]

        if limit is not None:

            query += """
            LIMIT ?
            """

            parameters.append(
                max(
                    1,
                    int(limit)
                )
            )

        with self._connect() as connection:

            rows = connection.execute(
                query,
                parameters,
            ).fetchall()

        processed = 0
        completed = 0
        failed = 0
        skipped = 0

        for row in rows:

            result = self.process_expiry(
                underlying_symbol,
                row["expiry_date"],
            )

            processed += 1

            status = result.get(
                "status"
            )

            if status == "COMPLETED":

                completed += 1

            elif status == "FAILED":

                failed += 1

            elif status == "SKIPPED":

                skipped += 1

        return {
            "processed": processed,
            "completed": completed,
            "failed": failed,
            "skipped": skipped,
        }

    # =========================================================
    # RECOVERY
    # =========================================================

    def recover_running_jobs(self) -> int:

        sql = """
        UPDATE expired_contract_registry
        SET
            status = 'PENDING',
            updated_at = CURRENT_TIMESTAMP
        WHERE broker = 'FYERS'
          AND status = 'RUNNING'
        """

        with self._connect() as connection:

            cursor = connection.execute(
                sql
            )

            connection.commit()

            return max(
                cursor.rowcount,
                0
            )

    # =========================================================
    # SUMMARY
    # =========================================================

    def summary(
        self,
        underlying_symbol: str,
    ) -> dict:

        query = """
        SELECT
            COUNT(*) AS total,

            SUM(
                CASE
                    WHEN status = 'PENDING'
                    THEN 1 ELSE 0
                END
            ) AS pending,

            SUM(
                CASE
                    WHEN status = 'RUNNING'
                    THEN 1 ELSE 0
                END
            ) AS running,

            SUM(
                CASE
                    WHEN status = 'COMPLETED'
                    THEN 1 ELSE 0
                END
            ) AS completed,

            SUM(
                CASE
                    WHEN status = 'FAILED'
                    THEN 1 ELSE 0
                END
            ) AS failed,

            COALESCE(
                SUM(futures_count),
                0
            ) AS futures,

            COALESCE(
                SUM(options_count),
                0
            ) AS options,

            COALESCE(
                SUM(total_count),
                0
            ) AS contracts

        FROM expired_contract_registry

        WHERE broker = 'FYERS'
          AND underlying_symbol = ?
        """

        with self._connect() as connection:

            row = connection.execute(
                query,
                (underlying_symbol,),
            ).fetchone()

        return {
            "jobs": int(
                row["total"] or 0
            ),
            "pending": int(
                row["pending"] or 0
            ),
            "running": int(
                row["running"] or 0
            ),
            "completed": int(
                row["completed"] or 0
            ),
            "failed": int(
                row["failed"] or 0
            ),
            "futures": int(
                row["futures"] or 0
            ),
            "options": int(
                row["options"] or 0
            ),
            "contracts": int(
                row["contracts"] or 0
            ),
        }


# =============================================================
# CLI
# =============================================================

def main() -> None:

    parser = argparse.ArgumentParser(
        description=(
            "Kunal Quant - Expired Contract Registry"
        )
    )

    parser.add_argument(
        "--underlying",
        default="NSE:NIFTY50-INDEX",
        help="FYERS underlying symbol.",
    )

    parser.add_argument(
        "--seed",
        action="store_true",
        help=(
            "Create pending jobs from "
            "expiry_registry."
        ),
    )

    parser.add_argument(
        "--run",
        action="store_true",
        help=(
            "Process pending expired-contract jobs."
        ),
    )

    parser.add_argument(
        "--retry-failed",
        action="store_true",
        help=(
            "Retry previously failed jobs."
        ),
    )

    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help=(
            "Maximum number of expiry jobs "
            "to process."
        ),
    )

    parser.add_argument(
        "--expiry",
        type=str,
        default=None,
        help=(
            "Process one specific expiry "
            "YYYY-MM-DD."
        ),
    )

    parser.add_argument(
        "--force",
        action="store_true",
        help=(
            "Force re-fetch of a completed expiry."
        ),
    )

    parser.add_argument(
        "--status",
        action="store_true",
        help=(
            "Show current registry summary."
        ),
    )

    args = parser.parse_args()

    print("=" * 75)

    print(
        "KUNAL QUANT - EXPIRED CONTRACT REGISTRY"
    )

    print("=" * 75)

    registry = ExpiredContractRegistry()

    # ---------------------------------------------------------
    # SEED
    # ---------------------------------------------------------

    if args.seed:

        seeded = (
            registry.seed_expiry_jobs(
                args.underlying
            )
        )

        print(
            "\nExpiry jobs created:",
            seeded
        )

    # ---------------------------------------------------------
    # SINGLE EXPIRY
    # ---------------------------------------------------------

    if args.expiry:

        registry.ensure_expiry_job(
            args.underlying,
            args.expiry,
        )

        result = (
            registry.process_expiry(
                underlying_symbol=(
                    args.underlying
                ),
                expiry_date=args.expiry,
                force=args.force,
            )
        )

        print(
            "\nSingle-expiry result:"
        )

        print(
            json.dumps(
                result,
                indent=2,
            )
        )

    # ---------------------------------------------------------
    # BULK RUN
    # ---------------------------------------------------------

    elif args.run:

        registry.recover_running_jobs()

        result = (
            registry.process_pending(
                underlying_symbol=(
                    args.underlying
                ),
                limit=args.limit,
                retry_failed=args.retry_failed,
            )
        )

        print(
            "\nProcessing result:"
        )

        print(
            json.dumps(
                result,
                indent=2,
            )
        )

    # ---------------------------------------------------------
    # STATUS
    # ---------------------------------------------------------

    if args.status or (
        not args.seed
        and not args.run
        and args.expiry is None
    ):

        summary = registry.summary(
            args.underlying
        )

        print(
            "\nRegistry summary:"
        )

        print(
            json.dumps(
                summary,
                indent=2,
            )
        )

    print(
        "\n" + "=" * 75
    )

    print(
        "EXPIRED CONTRACT REGISTRY COMPLETE"
    )

    print(
        "=" * 75
    )


if __name__ == "__main__":

    main()