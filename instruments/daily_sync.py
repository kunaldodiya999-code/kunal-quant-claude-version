from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from config.settings import DATABASE_PATH

from database.repository import (
    DatabaseRepository,
)

from instruments.symbol_master import (
    download_symbol_master,
    normalize_master,
)

from instruments.expired_contract_registry import (
    ExpiredContractRegistry,
)


class DailyInstrumentSync:
    """
    Daily lifecycle synchronizer for Kunal Quant.

    Responsibilities:

    1. Refresh the current FYERS symbol master.
    2. Upsert current instruments into SQLite.
    3. Register current/upcoming expiry dates.
    4. Mark previously-active expired instruments inactive.
    5. Create expired-contract jobs for newly expired dates.
    6. Process newly expired contract jobs.
    7. Record daily synchronization history.

    Historical bulk backfill remains a separate process.
    """

    BROKER = "FYERS"
    UNDERLYING = "NIFTY"

    # FYERS underlying used by the expired-contract API.
    FYERS_UNDERLYING_SYMBOL = "NSE:NIFTY50-INDEX"

    MARKET_TIMEZONE = ZoneInfo(
        "Asia/Kolkata"
    )

    # We intentionally use a small lookback for the
    # automatic rollover process. Historical backfill
    # remains controlled separately.
    RECENT_EXPIRY_LOOKBACK_DAYS = 7

    def __init__(
        self,
        database_path: Path | str = DATABASE_PATH,
        process_expired: bool = True,
        force_refresh: bool = False,
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

        self.expired_registry = (
            ExpiredContractRegistry(
                self.database_path
            )
        )

        self.process_expired = (
            bool(process_expired)
        )

        self.force_refresh = (
            bool(force_refresh)
        )

        self.run_date = (
            datetime.now(
                self.MARKET_TIMEZONE
            ).date()
        )

        self._ensure_sync_table()

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
    # SYNC TABLE
    # =========================================================

    def _ensure_sync_table(self) -> None:

        sql = """
        CREATE TABLE IF NOT EXISTS daily_sync_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,

            broker TEXT NOT NULL,

            underlying TEXT NOT NULL,

            run_date TEXT NOT NULL,

            status TEXT NOT NULL,

            current_instruments INTEGER NOT NULL DEFAULT 0,

            current_expiries INTEGER NOT NULL DEFAULT 0,

            expired_expiries_detected INTEGER NOT NULL DEFAULT 0,

            expired_jobs_completed INTEGER NOT NULL DEFAULT 0,

            expired_jobs_failed INTEGER NOT NULL DEFAULT 0,

            error_message TEXT,

            started_at TEXT NOT NULL
                DEFAULT CURRENT_TIMESTAMP,

            completed_at TEXT,

            UNIQUE (
                broker,
                underlying,
                run_date
            )
        )
        """

        index_sql = """
        CREATE INDEX IF NOT EXISTS
        idx_daily_sync_runs_lookup
        ON daily_sync_runs (
            broker,
            underlying,
            run_date,
            status
        )
        """

        with self._connect() as connection:

            connection.execute(sql)

            connection.execute(index_sql)

            connection.commit()

    # =========================================================
    # SYNC RUN RECORD
    # =========================================================

    def _start_run(self) -> None:

        sql = """
        INSERT INTO daily_sync_runs (
            broker,
            underlying,
            run_date,
            status
        )
        VALUES (
            'FYERS',
            ?,
            ?,
            'RUNNING'
        )
        ON CONFLICT(
            broker,
            underlying,
            run_date
        )
        DO UPDATE SET
            status = 'RUNNING',
            error_message = NULL,
            started_at = CURRENT_TIMESTAMP,
            completed_at = NULL
        """

        with self._connect() as connection:

            connection.execute(
                sql,
                (
                    self.UNDERLYING,
                    self.run_date.isoformat(),
                )
            )

            connection.commit()

    def _complete_run(
        self,
        current_instruments: int,
        current_expiries: int,
        expired_expiries_detected: int,
        expired_jobs_completed: int,
        expired_jobs_failed: int,
    ) -> None:

        sql = """
        UPDATE daily_sync_runs

        SET
            status = 'COMPLETED',

            current_instruments = ?,

            current_expiries = ?,

            expired_expiries_detected = ?,

            expired_jobs_completed = ?,

            expired_jobs_failed = ?,

            completed_at = CURRENT_TIMESTAMP

        WHERE broker = 'FYERS'

          AND underlying = ?

          AND run_date = ?
        """

        with self._connect() as connection:

            connection.execute(
                sql,
                (
                    current_instruments,
                    current_expiries,
                    expired_expiries_detected,
                    expired_jobs_completed,
                    expired_jobs_failed,
                    self.UNDERLYING,
                    self.run_date.isoformat(),
                )
            )

            connection.commit()

    def _fail_run(
        self,
        error_message: str,
    ) -> None:

        sql = """
        UPDATE daily_sync_runs

        SET
            status = 'FAILED',
            error_message = ?,
            completed_at = CURRENT_TIMESTAMP

        WHERE broker = 'FYERS'

          AND underlying = ?

          AND run_date = ?
        """

        with self._connect() as connection:

            connection.execute(
                sql,
                (
                    str(
                        error_message
                    )[:4000],
                    self.UNDERLYING,
                    self.run_date.isoformat(),
                )
            )

            connection.commit()

    # =========================================================
    # CURRENT MASTER
    # =========================================================

    def refresh_current_master(self) -> list[dict]:

        print(
            "\nRefreshing current FYERS "
            "symbol master..."
        )

        raw_master = (
            download_symbol_master(
                force_refresh=self.force_refresh
            )
        )

        instruments = normalize_master(
            raw_master
        )

        if not instruments:

            raise RuntimeError(
                "FYERS symbol master returned "
                "zero normalized instruments."
            )

        print(
            f"Current master records: "
            f"{len(instruments)}"
        )

        return instruments

    # =========================================================
    # STORE CURRENT MASTER
    # =========================================================

    def store_current_master(
        self,
        instruments: list[dict],
    ) -> int:

        count = (
            self.repository.upsert_instruments(
                instruments
            )
        )

        return count

    # =========================================================
    # MARK EXPIRED CURRENT INSTRUMENTS
    # =========================================================

    def mark_expired_instruments_inactive(
        self,
    ) -> int:

        today = self.run_date.isoformat()

        sql = """
        UPDATE instruments

        SET
            is_active = 0,
            updated_at = CURRENT_TIMESTAMP

        WHERE broker = 'FYERS'

          AND is_active = 1

          AND expiry_date IS NOT NULL

          AND expiry_date < ?

          AND option_type IN ('CE', 'PE', 'XX')
        """

        with self._connect() as connection:

            cursor = connection.execute(
                sql,
                (today,)
            )

            connection.commit()

            return max(
                cursor.rowcount,
                0
            )

    # =========================================================
    # REGISTER CURRENT EXPIRIES
    # =========================================================

    def register_current_expiries(
        self,
        instruments: list[dict],
    ) -> int:

        expiry_records: set[tuple[str, str]] = set()

        for instrument in instruments:

            if (
                instrument.get("underlying")
                != self.UNDERLYING
            ):
                continue

            expiry_date = instrument.get(
                "expiry_date"
            )

            if not expiry_date:
                continue

            instrument_type = instrument.get(
                "instrument_type"
            )

            option_type = instrument.get(
                "option_type"
            )

            # -------------------------------------------------
            # FUTURES
            # -------------------------------------------------

            if (
                instrument_type == 11
                and option_type == "XX"
            ):

                expiry_records.add(
                    (
                        str(expiry_date),
                        "futures",
                    )
                )

            # -------------------------------------------------
            # OPTIONS
            # -------------------------------------------------

            elif (
                instrument_type == 14
                and option_type in ("CE", "PE")
            ):

                expiry_records.add(
                    (
                        str(expiry_date),
                        "options",
                    )
                )

        if not expiry_records:
            return 0

        sql = """
        INSERT OR IGNORE INTO expiry_registry (
            broker,
            underlying_symbol,
            expiry_date,
            contract_type,
            source
        )
        VALUES (
            'FYERS',
            'NSE:NIFTY50-INDEX',
            ?,
            ?,
            'FYERS_CURRENT_MASTER'
        )
        """

        records = sorted(
            expiry_records
        )

        with self._connect() as connection:

            cursor = connection.executemany(
                sql,
                records
            )

            connection.commit()

            return max(
                cursor.rowcount,
                0
            )

    # =========================================================
    # RECENT EXPIRED EXPIRIES
    # =========================================================

    def find_recent_expired_expiries(
        self,
    ) -> list[str]:

        oldest_date = (
            self.run_date
            - timedelta(
                days=self.RECENT_EXPIRY_LOOKBACK_DAYS
            )
        )

        query = """
        SELECT DISTINCT expiry_date

        FROM expiry_registry

        WHERE broker = 'FYERS'

          AND underlying_symbol = ?

          AND expiry_date >= ?

          AND expiry_date < ?

        ORDER BY expiry_date
        """

        with self._connect() as connection:

            rows = connection.execute(
                query,
                (
                    self.FYERS_UNDERLYING_SYMBOL,
                    oldest_date.isoformat(),
                    self.run_date.isoformat(),
                )
            ).fetchall()

        return [
            str(
                row["expiry_date"]
            )
            for row in rows
        ]

    # =========================================================
    # ENSURE EXPIRED JOBS
    # =========================================================

    def ensure_recent_expired_jobs(
        self,
        expiry_dates: list[str],
    ) -> int:

        created = 0

        for expiry_date in expiry_dates:

            before = (
                self._get_expired_job(
                    expiry_date
                )
            )

            self.expired_registry.ensure_expiry_job(
                self.FYERS_UNDERLYING_SYMBOL,
                expiry_date,
            )

            after = (
                self._get_expired_job(
                    expiry_date
                )
            )

            if before is None and after is not None:

                created += 1

        return created

    def _get_expired_job(
        self,
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
                    self.FYERS_UNDERLYING_SYMBOL,
                    expiry_date,
                )
            ).fetchone()

        if row is None:

            return None

        return dict(row)

    # =========================================================
    # PROCESS RECENT EXPIRED JOBS
    # =========================================================

    def process_recent_expired_jobs(
        self,
        expiry_dates: list[str],
    ) -> dict:

        completed = 0
        failed = 0
        skipped = 0

        for expiry_date in expiry_dates:

            job = self._get_expired_job(
                expiry_date
            )

            if job is None:

                continue

            if (
                job["status"]
                == "COMPLETED"
            ):

                skipped += 1

                continue

            result = (
                self.expired_registry.process_expiry(
                    underlying_symbol=(
                        self.FYERS_UNDERLYING_SYMBOL
                    ),
                    expiry_date=expiry_date,
                )
            )

            status = result.get(
                "status"
            )

            if status == "COMPLETED":

                completed += 1

            elif status == "FAILED":

                failed += 1

            else:

                skipped += 1

        return {
            "completed": completed,
            "failed": failed,
            "skipped": skipped,
        }

    # =========================================================
    # FULL DAILY SYNC
    # =========================================================

    def run(self) -> dict:

        print("=" * 75)

        print(
            "KUNAL QUANT - DAILY INSTRUMENT SYNC"
        )

        print("=" * 75)

        print(
            f"\nRun date: "
            f"{self.run_date.isoformat()}"
        )

        self._start_run()

        try:

            # -------------------------------------------------
            # 1. REFRESH CURRENT MASTER
            # -------------------------------------------------

            instruments = (
                self.refresh_current_master()
            )

            current_count = (
                self.store_current_master(
                    instruments
                )
            )

            print(
                f"Current instruments "
                f"processed: {current_count}"
            )

            # -------------------------------------------------
            # 2. CURRENT EXPIRY CALENDAR
            # -------------------------------------------------

            current_expiries = (
                self.register_current_expiries(
                    instruments
                )
            )

            print(
                f"Current expiry records "
                f"added: {current_expiries}"
            )

            # -------------------------------------------------
            # 3. MARK EXPIRED INSTRUMENTS
            # -------------------------------------------------

            inactive_count = (
                self.mark_expired_instruments_inactive()
            )

            print(
                f"Previously-active expired "
                f"instruments marked inactive: "
                f"{inactive_count}"
            )

            # -------------------------------------------------
            # 4. FIND RECENT EXPIRIES
            # -------------------------------------------------

            recent_expiries = (
                self.find_recent_expired_expiries()
            )

            print(
                "\nRecent expired dates:"
            )

            if recent_expiries:

                for expiry_date in recent_expiries:

                    print(
                        f"  {expiry_date}"
                    )

            else:

                print(
                    "  None"
                )

            # -------------------------------------------------
            # 5. ENSURE JOBS
            # -------------------------------------------------

            self.ensure_recent_expired_jobs(
                recent_expiries
            )

            # -------------------------------------------------
            # 6. PROCESS EXPIRED CONTRACTS
            # -------------------------------------------------

            expired_completed = 0
            expired_failed = 0

            if self.process_expired:

                result = (
                    self.process_recent_expired_jobs(
                        recent_expiries
                    )
                )

                expired_completed = (
                    result["completed"]
                )

                expired_failed = (
                    result["failed"]
                )

                print(
                    "\nExpired contract processing:"
                )

                print(
                    f"  Completed: "
                    f"{expired_completed}"
                )

                print(
                    f"  Failed: "
                    f"{expired_failed}"
                )

                print(
                    f"  Skipped: "
                    f"{result['skipped']}"
                )

            summary = {
                "run_date": (
                    self.run_date.isoformat()
                ),
                "current_instruments": (
                    current_count
                ),
                "current_expiries_added": (
                    current_expiries
                ),
                "expired_instruments_marked_inactive": (
                    inactive_count
                ),
                "recent_expired_dates": (
                    recent_expiries
                ),
                "expired_jobs_completed": (
                    expired_completed
                ),
                "expired_jobs_failed": (
                    expired_failed
                ),
            }

            self._complete_run(
                current_instruments=current_count,
                current_expiries=current_expiries,
                expired_expiries_detected=len(
                    recent_expiries
                ),
                expired_jobs_completed=(
                    expired_completed
                ),
                expired_jobs_failed=(
                    expired_failed
                ),
            )

            print(
                "\n" + "=" * 75
            )

            print(
                "DAILY INSTRUMENT SYNC COMPLETE"
            )

            print(
                "=" * 75
            )

            print(
                json.dumps(
                    summary,
                    indent=2,
                )
            )

            return summary

        except Exception as exc:

            self._fail_run(
                str(exc)
            )

            print(
                "\nDAILY SYNC FAILED:"
            )

            print(
                str(exc)
            )

            raise


# =============================================================
# CLI
# =============================================================

def main() -> None:

    parser = argparse.ArgumentParser(
        description=(
            "Kunal Quant - Daily Instrument Sync"
        )
    )

    parser.add_argument(
        "--force-refresh",
        action="store_true",
        help=(
            "Force download of the current "
            "FYERS symbol master."
        ),
    )

    parser.add_argument(
        "--no-expired-processing",
        action="store_true",
        help=(
            "Register recent expired jobs but "
            "do not call the expired-contract API."
        ),
    )

    args = parser.parse_args()

    sync = DailyInstrumentSync(
        process_expired=(
            not args.no_expired_processing
        ),
        force_refresh=args.force_refresh,
    )

    sync.run()


if __name__ == "__main__":

    main()