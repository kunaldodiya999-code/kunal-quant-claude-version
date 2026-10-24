from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path

from api.fyers_client import FyersClient

from config.settings import DATABASE_PATH


class ExpiryRegistry:
    """
    Discover and store historical FYERS F&O expiry dates.

    This is the calendar layer of the Kunal Quant
    historical-data pipeline.
    """

    def __init__(
        self,
        database_path: Path | str = DATABASE_PATH,
    ) -> None:

        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        self.fyers = FyersClient()

        self._ensure_table()

    # =========================================================
    # DATABASE
    # =========================================================

    def _connect(self) -> sqlite3.Connection:

        connection = sqlite3.connect(
            self.database_path
        )

        connection.row_factory = sqlite3.Row

        return connection

    def _ensure_table(self) -> None:

        sql = """
        CREATE TABLE IF NOT EXISTS expiry_registry (
            id INTEGER PRIMARY KEY AUTOINCREMENT,

            broker TEXT NOT NULL,

            underlying_symbol TEXT NOT NULL,

            expiry_date TEXT NOT NULL,

            contract_type TEXT NOT NULL,

            source TEXT NOT NULL DEFAULT 'FYERS',

            discovered_at TEXT NOT NULL
                DEFAULT CURRENT_TIMESTAMP,

            UNIQUE (
                broker,
                underlying_symbol,
                expiry_date,
                contract_type
            )
        )
        """

        index_sql = """
        CREATE INDEX IF NOT EXISTS
        idx_expiry_registry_lookup
        ON expiry_registry (
            broker,
            underlying_symbol,
            expiry_date,
            contract_type
        )
        """

        with self._connect() as connection:

            connection.execute(sql)

            connection.execute(index_sql)

            connection.commit()

    # =========================================================
    # DATE HELPERS
    # =========================================================

    @staticmethod
    def _parse_date(
        value: str,
    ) -> date:

        return datetime.strptime(
            value,
            "%Y-%m-%d",
        ).date()

    @staticmethod
    def _format_date(
        value: date,
    ) -> str:

        return value.strftime(
            "%Y-%m-%d"
        )

    # =========================================================
    # RESPONSE PARSING
    # =========================================================

    @staticmethod
    def _extract_expiry_date(
        value,
    ) -> str | None:

        if isinstance(value, str):

            value = value.strip()

            if not value:

                return None

            # Expected format.
            try:

                datetime.strptime(
                    value,
                    "%Y-%m-%d",
                )

                return value

            except ValueError:

                return value

        if isinstance(value, dict):

            possible_keys = (
                "expiry_date",
                "expiryDate",
                "expiry",
                "date",
            )

            for key in possible_keys:

                candidate = value.get(key)

                if candidate is None:

                    continue

                if isinstance(candidate, str):

                    return candidate.strip()

        return None

    @classmethod
    def _extract_expiry_list(
        cls,
        response: dict,
        contract_type: str,
    ) -> list[str]:

        data = response.get(
            "data",
            {}
        )

        expiry_dates = data.get(
            "expiry_dates",
            {}
        )

        values = expiry_dates.get(
            contract_type,
            []
        )

        results: list[str] = []

        for value in values:

            expiry_date = (
                cls._extract_expiry_date(
                    value
                )
            )

            if expiry_date:

                results.append(
                    expiry_date
                )

        return sorted(
            set(results)
        )

    # =========================================================
    # DATABASE INSERT
    # =========================================================

    def _store_expiries(
        self,
        underlying_symbol: str,
        contract_type: str,
        expiry_dates: list[str],
    ) -> int:

        if not expiry_dates:

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
            ?,
            ?,
            ?,
            'FYERS'
        )
        """

        records = [
            (
                underlying_symbol,
                expiry_date,
                contract_type,
            )
            for expiry_date in expiry_dates
        ]

        with self._connect() as connection:

            cursor = connection.executemany(
                sql,
                records,
            )

            connection.commit()

            return cursor.rowcount

    # =========================================================
    # ONE API CHUNK
    # =========================================================

    def _fetch_chunk(
        self,
        underlying_symbol: str,
        range_from: date,
        range_to: date,
    ) -> dict:

        from_date = self._format_date(
            range_from
        )

        to_date = self._format_date(
            range_to
        )

        print(
            f"\nFetching expiry dates:"
            f" {from_date} -> {to_date}"
        )

        response = (
            self.fyers.expired_expiry_dates(
                symbol=underlying_symbol,
                range_from=from_date,
                range_to=to_date,
            )
        )

        futures = (
            self._extract_expiry_list(
                response,
                "futures",
            )
        )

        options = (
            self._extract_expiry_list(
                response,
                "options",
            )
        )

        print(
            f"  Futures expiries : {len(futures)}"
        )

        print(
            f"  Options expiries : {len(options)}"
        )

        self._store_expiries(
            underlying_symbol,
            "futures",
            futures,
        )

        self._store_expiries(
            underlying_symbol,
            "options",
            options,
        )

        return {
            "range_from": from_date,
            "range_to": to_date,
            "futures": futures,
            "options": options,
        }

    # =========================================================
    # FULL RANGE DISCOVERY
    # =========================================================

    def discover(
        self,
        underlying_symbol: str,
        start_date: str,
        end_date: str,
    ) -> dict:

        start = self._parse_date(
            start_date
        )

        requested_end = self._parse_date(
            end_date
        )

        # FYERS does not allow the current date
        # or any future date for expired expiry
        # discovery.
        #
        # Therefore, automatically cap the
        # requested end date at yesterday.
        api_latest_date = (
            date.today()
            - timedelta(days=1)
        )

        end = min(
            requested_end,
            api_latest_date
        )

        if requested_end > api_latest_date:

            print(
                "\nRequested end date "
                f"{requested_end.isoformat()} "
                "is not allowed by FYERS."
            )

            print(
                "Automatically adjusting to "
                f"{end.isoformat()}."
            )

        if start > end:

            raise ValueError(
                "start_date cannot be later "
                "than the effective end date."
            )

        current = start

        total_futures: set[str] = set()
        total_options: set[str] = set()

        chunks = 0

        # FYERS allows approximately one year
        # of expiry-date range. Using 365 days
        # keeps each request safely within the
        # supported range.
        chunk_size = 365

        while current <= end:

            chunk_end = min(
                current
                + timedelta(
                    days=chunk_size
                ),
                end,
            )

            result = self._fetch_chunk(
                underlying_symbol,
                current,
                chunk_end,
            )

            total_futures.update(
                result["futures"]
            )

            total_options.update(
                result["options"]
            )

            chunks += 1

            current = (
                chunk_end
                + timedelta(days=1)
            )

        result = {
            "underlying_symbol": (
                underlying_symbol
            ),
            "start_date": start_date,
            "requested_end_date": end_date,
            "effective_end_date": (
                end.isoformat()
            ),
            "chunks": chunks,
            "unique_futures_expiries": sorted(
                total_futures
            ),
            "unique_options_expiries": sorted(
                total_options
            ),
            "future_count": len(
                total_futures
            ),
            "option_count": len(
                total_options
            ),
        }

        return result

    # =========================================================
    # READ DATABASE
    # =========================================================

    def get_expiries(
        self,
        underlying_symbol: str,
        contract_type: str | None = None,
    ) -> list[dict]:

        query = """
        SELECT *
        FROM expiry_registry
        WHERE broker = 'FYERS'
          AND underlying_symbol = ?
        """

        parameters: list[str] = [
            underlying_symbol
        ]

        if contract_type is not None:

            query += """
              AND contract_type = ?
            """

            parameters.append(
                contract_type
            )

        query += """
        ORDER BY expiry_date, contract_type
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

    def count(
        self,
        underlying_symbol: str,
        contract_type: str | None = None,
    ) -> int:

        query = """
        SELECT COUNT(*)
        FROM expiry_registry
        WHERE broker = 'FYERS'
          AND underlying_symbol = ?
        """

        parameters: list[str] = [
            underlying_symbol
        ]

        if contract_type is not None:

            query += """
              AND contract_type = ?
            """

            parameters.append(
                contract_type
            )

        with self._connect() as connection:

            value = connection.execute(
                query,
                parameters,
            ).fetchone()[0]

        return int(value)


# =============================================================
# CLI
# =============================================================

def main() -> None:

    parser = argparse.ArgumentParser(
        description=(
            "Kunal Quant - FYERS Expiry Registry"
        )
    )

    parser.add_argument(
        "--underlying",
        default="NSE:NIFTY50-INDEX",
        help="FYERS underlying symbol.",
    )

    parser.add_argument(
        "--start",
        required=True,
        help="Start date YYYY-MM-DD.",
    )

    parser.add_argument(
        "--end",
        required=True,
        help="End date YYYY-MM-DD.",
    )

    args = parser.parse_args()

    print("=" * 75)
    print("KUNAL QUANT - EXPIRY REGISTRY")
    print("=" * 75)

    registry = ExpiryRegistry()

    result = registry.discover(
        underlying_symbol=args.underlying,
        start_date=args.start,
        end_date=args.end,
    )

    print(
        "\n" + "=" * 75
    )

    print(
        "DISCOVERY RESULT"
    )

    print(
        "=" * 75
    )

    print(
        json.dumps(
            result,
            indent=2,
        )
    )

    print(
        "\nDatabase counts:"
    )

    print(
        "  Futures:",
        registry.count(
            args.underlying,
            "futures",
        )
    )

    print(
        "  Options:",
        registry.count(
            args.underlying,
            "options",
        )
    )

    print(
        "\n" + "=" * 75
    )

    print(
        "EXPIRY REGISTRY COMPLETE"
    )

    print(
        "=" * 75
    )


if __name__ == "__main__":

    main()