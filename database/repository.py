from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Iterable


class DatabaseRepository:
    """Database operations for Kunal Quant."""

    def __init__(
        self,
        database_path: Path | str,
    ) -> None:

        self.database_path = Path(database_path)

        self.database_path.parent.mkdir(
            parents=True,
            exist_ok=True
        )

    def connect(self) -> sqlite3.Connection:

        connection = sqlite3.connect(
            self.database_path
        )

        connection.row_factory = sqlite3.Row

        connection.execute(
            "PRAGMA foreign_keys = ON"
        )

        return connection

    # ---------------------------------------------------------
    # INSTRUMENT UPSERT
    # ---------------------------------------------------------

    def upsert_instrument(
        self,
        instrument: dict,
    ) -> int:

        sql = """
        INSERT INTO instruments (
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
        )
        VALUES (
            :broker,
            :exchange,
            :segment,
            :symbol,
            :broker_token,
            :security_id,
            :underlying,
            :instrument_type,
            :expiry_date,
            :strike,
            :option_type,
            :lot_size,
            :tick_size,
            :currency,
            :is_active
        )
        ON CONFLICT(broker, symbol)
        DO UPDATE SET
            exchange = excluded.exchange,
            segment = excluded.segment,
            broker_token = excluded.broker_token,
            security_id = excluded.security_id,
            underlying = excluded.underlying,
            instrument_type = excluded.instrument_type,
            expiry_date = excluded.expiry_date,
            strike = excluded.strike,
            option_type = excluded.option_type,
            lot_size = excluded.lot_size,
            tick_size = excluded.tick_size,
            currency = excluded.currency,
            is_active = excluded.is_active,
            updated_at = CURRENT_TIMESTAMP
        """

        with self.connect() as connection:

            connection.execute(
                sql,
                instrument
            )

            row = connection.execute(
                """
                SELECT id
                FROM instruments
                WHERE broker = ?
                  AND symbol = ?
                """,
                (
                    instrument["broker"],
                    instrument["symbol"],
                )
            ).fetchone()

            if row is None:
                raise RuntimeError(
                    "Instrument upsert succeeded "
                    "but instrument could not be read back."
                )

            return int(row["id"])

    def upsert_instruments(
        self,
        instruments: Iterable[dict],
    ) -> int:

        sql = """
        INSERT INTO instruments (
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
        )
        VALUES (
            :broker,
            :exchange,
            :segment,
            :symbol,
            :broker_token,
            :security_id,
            :underlying,
            :instrument_type,
            :expiry_date,
            :strike,
            :option_type,
            :lot_size,
            :tick_size,
            :currency,
            :is_active
        )
        ON CONFLICT(broker, symbol)
        DO UPDATE SET
            exchange = excluded.exchange,
            segment = excluded.segment,
            broker_token = excluded.broker_token,
            security_id = excluded.security_id,
            underlying = excluded.underlying,
            instrument_type = excluded.instrument_type,
            expiry_date = excluded.expiry_date,
            strike = excluded.strike,
            option_type = excluded.option_type,
            lot_size = excluded.lot_size,
            tick_size = excluded.tick_size,
            currency = excluded.currency,
            is_active = excluded.is_active,
            updated_at = CURRENT_TIMESTAMP
        """

        records = list(instruments)

        if not records:
            return 0

        with self.connect() as connection:

            connection.executemany(
                sql,
                records
            )

            connection.commit()

        return len(records)

    # ---------------------------------------------------------
    # LOOKUPS
    # ---------------------------------------------------------

    def get_instrument(
        self,
        broker: str,
        symbol: str,
    ) -> dict | None:

        with self.connect() as connection:

            row = connection.execute(
                """
                SELECT *
                FROM instruments
                WHERE broker = ?
                  AND symbol = ?
                """,
                (
                    broker,
                    symbol,
                )
            ).fetchone()

        if row is None:
            return None

        return dict(row)

    def find_options(
        self,
        underlying: str,
        expiry_date: str | None = None,
        option_type: str | None = None,
    ) -> list[dict]:

        query = """
        SELECT *
        FROM instruments
        WHERE broker = 'FYERS'
          AND underlying = ?
          AND option_type IN ('CE', 'PE')
        """

        parameters: list = [
            underlying
        ]

        if expiry_date is not None:

            query += """
              AND expiry_date = ?
            """

            parameters.append(
                expiry_date
            )

        if option_type is not None:

            query += """
              AND option_type = ?
            """

            parameters.append(
                option_type
            )

        query += """
        ORDER BY expiry_date, strike, option_type
        """

        with self.connect() as connection:

            rows = connection.execute(
                query,
                parameters
            ).fetchall()

        return [
            dict(row)
            for row in rows
        ]

    # ---------------------------------------------------------
    # COUNTS / SUMMARY
    # ---------------------------------------------------------

    def count_instruments(
        self,
        broker: str = "FYERS",
    ) -> int:

        with self.connect() as connection:

            row = connection.execute(
                """
                SELECT COUNT(*) AS count
                FROM instruments
                WHERE broker = ?
                """,
                (broker,)
            ).fetchone()

        return int(row["count"])

    def instrument_summary(
        self,
        broker: str = "FYERS",
    ) -> dict:

        with self.connect() as connection:

            total = connection.execute(
                """
                SELECT COUNT(*)
                FROM instruments
                WHERE broker = ?
                """,
                (broker,)
            ).fetchone()[0]

            options = connection.execute(
                """
                SELECT COUNT(*)
                FROM instruments
                WHERE broker = ?
                  AND option_type IN ('CE', 'PE')
                """,
                (broker,)
            ).fetchone()[0]

            # FYERS uses option_type = "XX"
            # for futures/non-option derivative contracts.
            futures = connection.execute(
                """
                SELECT COUNT(*)
                FROM instruments
                WHERE broker = ?
                  AND instrument_type = 11
                  AND option_type = 'XX'
                """,
                (broker,)
            ).fetchone()[0]

            expired = connection.execute(
                """
                SELECT COUNT(*)
                FROM instruments
                WHERE broker = ?
                  AND is_active = 0
                """,
                (broker,)
            ).fetchone()[0]

        return {
            "total": int(total),
            "options": int(options),
            "futures": int(futures),
            "expired": int(expired),
        }