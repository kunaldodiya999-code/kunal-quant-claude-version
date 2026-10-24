from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import datetime, time
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from instruments.contract_specs import (
    ContractSpecRegistry,
)

from config.settings import DATABASE_PATH


class GEXEngine:
    """
    Kunal Quant - Gamma Exposure Engine V1.

    Calculates strike-level gamma exposure from stored:

    - option gamma
    - option open interest
    - option lot size
    - NIFTY spot price

    This is a derived analytical layer.

    IMPORTANT:
    The signed call/put convention used here is an explicit
    modelling convention. It does not establish the actual
    dealer position from OI alone.

    V1 convention:

        Call GEX = positive
        Put GEX  = negative

    Formula:

        GEX = Gamma
              × Open Interest
              × Lot Size
              × Spot^2
              × 0.01

    This expresses exposure associated with an approximately
    1% move in the underlying, using the gamma supplied by
    our Black-76 analytics engine.
    """

    UNDERLYING = "NIFTY"

    RESOLUTION = "1"

    GEX_CONVENTION = (
        "CALL_POSITIVE_PUT_NEGATIVE"
    )

    CALCULATION_VERSION = (
        "gex_v1_black76_ltp"
    )

    # ---------------------------------------------------------
    # GEX QUALITY
    # ---------------------------------------------------------

    TIMEZONE = ZoneInfo(
        "Asia/Kolkata"
    )

    NEAR_EXPIRY_MINUTES = 15.0

    EXTREME_GAMMA_1PCT_THRESHOLD = 1.0

    # ---------------------------------------------------------
    # Database
    # ---------------------------------------------------------

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

        self.contract_specs = (
            ContractSpecRegistry()
        )

    def _connect(self) -> sqlite3.Connection:

        connection = sqlite3.connect(
            self.database_path
        )

        connection.row_factory = sqlite3.Row

        connection.execute(
            "PRAGMA foreign_keys = ON"
        )

        return connection

    # ---------------------------------------------------------
    # GEX calculation
    # ---------------------------------------------------------

    @staticmethod
    def calculate_gex(
        gamma: float,
        open_interest: int,
        lot_size: int,
        spot_price: float,
        option_type: str,
    ) -> float:

        if (
            gamma is None
            or open_interest is None
            or lot_size is None
            or spot_price is None
        ):
            return 0.0

        if (
            gamma < 0
            or open_interest < 0
            or lot_size <= 0
            or spot_price <= 0
        ):
            return 0.0

        exposure = (
            float(gamma)
            * float(open_interest)
            * float(lot_size)
            * (
                float(spot_price)
                ** 2
            )
            * 0.01
        )

        option_type = (
            option_type.upper()
        )

        if option_type == "PE":

            return -exposure

        return exposure

    # ---------------------------------------------------------
    # Load option analytics
    # ---------------------------------------------------------

    def get_option_rows(
        self,
        expiry_date: str,
        start_timestamp: int | None = None,
        end_timestamp: int | None = None,
    ) -> list[dict]:

        query = """
        SELECT
            oa.timestamp,
            oa.instrument_id,
            oa.expiry_date,
            oa.strike,
            oa.option_type,
            oa.forward_price,
            oa.gamma,
            i.symbol,
            i.lot_size
        FROM option_analytics oa

        JOIN instruments i
          ON i.id = oa.instrument_id

        WHERE oa.resolution = ?
          AND oa.expiry_date = ?
          AND oa.option_type IN ('CE', 'PE')
          AND oa.gamma IS NOT NULL
          AND oa.calculation_version = ?
        """

        parameters: list[Any] = [
            self.RESOLUTION,
            expiry_date,
            "black76_iv_greeks_v1",
        ]

        if start_timestamp is not None:

            query += """
              AND oa.timestamp >= ?
            """

            parameters.append(
                start_timestamp
            )

        if end_timestamp is not None:

            query += """
              AND oa.timestamp <= ?
            """

            parameters.append(
                end_timestamp
            )

        query += """
        ORDER BY
            oa.timestamp,
            oa.strike,
            oa.option_type
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

    # ---------------------------------------------------------
    # Load OI
    # ---------------------------------------------------------

    def get_open_interest_map(
        self,
        instrument_ids: list[int],
        timestamps: list[int],
    ) -> dict[tuple[int, int], int]:

        if not instrument_ids:

            return {}

        if not timestamps:

            return {}

        # SQLite has a parameter limit, so use manageable
        # batches for safety.
        result: dict[
            tuple[int, int],
            int
        ] = {}

        unique_instruments = sorted(
            set(instrument_ids)
        )

        unique_timestamps = sorted(
            set(timestamps)
        )

        instrument_placeholders = (
            ",".join(
                "?"
                for _ in unique_instruments
            )
        )

        timestamp_placeholders = (
            ",".join(
                "?"
                for _ in unique_timestamps
            )
        )

        sql = f"""
        SELECT
            instrument_id,
            timestamp,
            open_interest
        FROM candles
        WHERE instrument_id IN (
            {instrument_placeholders}
        )
          AND timestamp IN (
            {timestamp_placeholders}
        )
          AND resolution = ?
          AND source = 'FYERS_FNO_HISTORY'
          AND open_interest IS NOT NULL
        """

        parameters = (
            unique_instruments
            + unique_timestamps
            + [self.RESOLUTION]
        )

        with self._connect() as connection:

            rows = connection.execute(
                sql,
                parameters,
            ).fetchall()

        for row in rows:

            result[
                (
                    int(row["instrument_id"]),
                    int(row["timestamp"]),
                )
            ] = int(
                row["open_interest"]
            )

        return result

    # ---------------------------------------------------------
    # Load spot
    # ---------------------------------------------------------

    def get_spot_map(
        self,
        timestamps: list[int],
    ) -> dict[int, float]:

        if not timestamps:

            return {}

        placeholders = ",".join(
            "?"
            for _ in timestamps
        )

        sql = f"""
        SELECT
            timestamp,
            close
        FROM candles
        WHERE instrument_id = (
            SELECT id
            FROM instruments
            WHERE broker = 'FYERS'
              AND symbol = 'NSE:NIFTY50-INDEX'
            LIMIT 1
        )
          AND resolution = ?
          AND source = 'FYERS_HISTORY'
          AND timestamp IN (
              {placeholders}
          )
        """

        parameters = (
            [self.RESOLUTION]
            + timestamps
        )

        with self._connect() as connection:

            rows = connection.execute(
                sql,
                parameters,
            ).fetchall()

        return {
            int(row["timestamp"]): float(
                row["close"]
            )
            for row in rows
            if row["close"] is not None
        }
    # ---------------------------------------------------------
    # GEX quality classification
    # ---------------------------------------------------------

    @classmethod
    def classify_gex_quality(
        cls,
        timestamp: int,
        expiry_date: str,
        spot_price: float,
        call_gamma: float | None,
        put_gamma: float | None,
    ) -> dict:

        expiry_datetime = datetime.combine(
            datetime.strptime(
                expiry_date,
                "%Y-%m-%d",
            ).date(),
            time(
                15,
                30,
            ),
            tzinfo=cls.TIMEZONE,
        )

        expiry_timestamp = int(
            expiry_datetime.timestamp()
        )

        seconds_remaining = (
            expiry_timestamp
            - int(timestamp)
        )

        dte_seconds = max(
            seconds_remaining,
            0,
        )

        dte_minutes = (
            dte_seconds
            / 60.0
        )

        gamma_values = [
            float(value)
            for value in (
                call_gamma,
                put_gamma,
            )
            if value is not None
            and value >= 0
        ]

        max_gamma = (
            max(gamma_values)
            if gamma_values
            else None
        )

        gamma_1pct = (
            max_gamma
            * float(spot_price)
            * 0.01
            if (
                max_gamma is not None
                and spot_price is not None
                and spot_price > 0
            )
            else None
        )

        expiry_day = (
            datetime.fromtimestamp(
                int(timestamp),
                tz=cls.TIMEZONE,
            ).date()
            == expiry_datetime.date()
        )

        near_expiry = (
            dte_seconds > 0
            and dte_minutes
            <= cls.NEAR_EXPIRY_MINUTES
        )

        extreme_gamma = (
            gamma_1pct is not None
            and gamma_1pct
            > cls.EXTREME_GAMMA_1PCT_THRESHOLD
        )

        flags = []

        if expiry_day:
            flags.append(
                "EXPIRY_DAY"
            )

        if near_expiry:
            flags.append(
                "NEAR_EXPIRY"
            )

        if extreme_gamma:
            flags.append(
                "EXTREME_GAMMA"
            )

        if (
            near_expiry
            and extreme_gamma
        ):
            quality = (
                "EXTREME_NEAR_EXPIRY"
            )

        elif extreme_gamma:
            quality = (
                "EXTREME_GAMMA"
            )

        elif near_expiry:
            quality = (
                "NEAR_EXPIRY"
            )

        elif expiry_day:
            quality = (
                "EXPIRY_DAY"
            )

        else:
            quality = "NORMAL"

        return {
            "dte_seconds": dte_seconds,
            "dte_minutes": dte_minutes,
            "expiry_state": (
                "NEAR_EXPIRY"
                if near_expiry
                else (
                    "EXPIRY_DAY"
                    if expiry_day
                    else "NORMAL"
                )
            ),
            "max_gamma": max_gamma,
            "gamma_1pct": gamma_1pct,
            "extreme_gamma": (
                extreme_gamma
            ),
            "quality_flags": flags,
            "gex_quality": quality,
        }
    # ---------------------------------------------------------
    # Build snapshots
    # ---------------------------------------------------------

    def build(
        self,
        expiry_date: str,
        start_timestamp: int | None = None,
        end_timestamp: int | None = None,
    ) -> dict:

        option_rows = self.get_option_rows(
            expiry_date=expiry_date,
            start_timestamp=start_timestamp,
            end_timestamp=end_timestamp,
        )

        if not option_rows:

            raise ValueError(
                "No option analytics rows found "
                f"for expiry {expiry_date}."
            )

        instrument_ids = [
            int(
                row["instrument_id"]
            )
            for row in option_rows
        ]

        timestamps = [
            int(
                row["timestamp"]
            )
            for row in option_rows
        ]

        oi_map = (
            self.get_open_interest_map(
                instrument_ids=instrument_ids,
                timestamps=timestamps,
            )
        )

        spot_map = (
            self.get_spot_map(
                timestamps=timestamps
            )
        )

        grouped: dict[
            tuple[int, float],
            dict
        ] = {}

        processed_rows = 0
        skipped_rows = 0

        for row in option_rows:

            instrument_id = int(
                row["instrument_id"]
            )

            timestamp = int(
                row["timestamp"]
            )

            strike = float(
                row["strike"]
            )

            option_type = str(
                row["option_type"]
            )

            gamma = float(
                row["gamma"]
            )

            lot_size = (
                int(
                    row["lot_size"]
                )
                if row["lot_size"] is not None
                else (
                    self.contract_specs.get_lot_size(
                        underlying=self.UNDERLYING,
                        expiry_date=expiry_date,
                    )
                    or 0
                )
            )

            open_interest = oi_map.get(
                (
                    instrument_id,
                    timestamp,
                )
            )

            spot_price = spot_map.get(
                timestamp
            )

            if (
                open_interest is None
                or lot_size <= 0
                or spot_price is None
            ):

                skipped_rows += 1

                continue

            gex = self.calculate_gex(
                gamma=gamma,
                open_interest=open_interest,
                lot_size=lot_size,
                spot_price=spot_price,
                option_type=option_type,
            )

            key = (
                timestamp,
                strike,
            )

            if key not in grouped:

                grouped[key] = {
                    "timestamp": timestamp,
                    "expiry_date": expiry_date,
                    "strike": strike,
                    "spot_price": spot_price,
                    "call_oi": 0,
                    "put_oi": 0,
                    "call_gamma": None,
                    "put_gamma": None,
                    "call_gex": 0.0,
                    "put_gex": 0.0,
                }

            snapshot = grouped[key]

            if option_type == "CE":

                snapshot[
                    "call_oi"
                ] = open_interest

                snapshot[
                    "call_gamma"
                ] = gamma

                snapshot[
                    "call_gex"
                ] = gex

            else:

                snapshot[
                    "put_oi"
                ] = open_interest

                snapshot[
                    "put_gamma"
                ] = gamma

                snapshot[
                    "put_gex"
                ] = gex

            processed_rows += 1

        snapshots = []

        for snapshot in grouped.values():

            call_gex = float(
                snapshot["call_gex"]
            )

            put_gex = float(
                snapshot["put_gex"]
            )

            gross_gex = (
                abs(call_gex)
                + abs(put_gex)
            )

            net_gex = (
                call_gex
                + put_gex
            )

            snapshot[
                "gross_gex"
            ] = gross_gex

            snapshot[
                "net_gex"
            ] = net_gex

            snapshot[
                "underlying"
            ] = self.UNDERLYING

            snapshot[
                "resolution"
            ] = self.RESOLUTION

            snapshot[
                "gex_convention"
            ] = self.GEX_CONVENTION

            snapshot[
                "calculation_version"
            ] = self.CALCULATION_VERSION

            quality = (
                self.classify_gex_quality(
                    timestamp=int(
                        snapshot["timestamp"]
                    ),
                    expiry_date=expiry_date,
                    spot_price=float(
                        snapshot["spot_price"]
                    ),
                    call_gamma=snapshot[
                        "call_gamma"
                    ],
                    put_gamma=snapshot[
                        "put_gamma"
                    ],
                )
            )

            snapshot["gex_quality"] = quality["gex_quality"]

            snapshot["expiry_state"] = quality["expiry_state"]

            snapshot["dte_seconds"] = quality["dte_seconds"]

            snapshot["dte_minutes"] = quality["dte_minutes"]

            snapshot["max_gamma"] = quality["max_gamma"]

            snapshot["gamma_1pct"] = quality["gamma_1pct"]

            snapshot["extreme_gamma"] = quality["extreme_gamma"]

            snapshot["quality_flags"] = quality["quality_flags"]

            snapshots.append(
                snapshot
            )


        snapshots.sort(
            key=lambda row: (
                row["timestamp"],
                row["strike"],
            )
        )

        stored = self.store_snapshots(
            snapshots
        )

        return {
            "underlying": self.UNDERLYING,
            "expiry_date": expiry_date,
            "resolution": self.RESOLUTION,
            "option_analytics_rows": len(
                option_rows
            ),
            "processed_option_rows": (
                processed_rows
            ),
            "skipped_option_rows": (
                skipped_rows
            ),
            "gex_snapshots": len(
                snapshots
            ),
            "stored_rows": stored,
            "gex_convention": (
                self.GEX_CONVENTION
            ),
            "calculation_version": (
                self.CALCULATION_VERSION
            ),
        }

        # ---------------------------------------------------------
    # Store snapshots
    # ---------------------------------------------------------

    def store_snapshots(
        self,
        snapshots: list[dict],
    ) -> int:

        if not snapshots:

            return 0

        sql = """
        INSERT OR REPLACE INTO gex_snapshots (
            timestamp,
            resolution,
            underlying,
            expiry_date,
            strike,
            spot_price,
            call_oi,
            put_oi,
            call_gamma,
            put_gamma,
            call_gex,
            put_gex,
            gross_gex,
            net_gex,
            gex_convention,
            calculation_version,
            gex_quality,
            expiry_state,
            dte_seconds,
            dte_minutes,
            max_gamma,
            gamma_1pct,
            extreme_gamma,
            quality_flags
        )
        VALUES (
            ?,
            ?,
            ?,
            ?,
            ?,
            ?,
            ?,
            ?,
            ?,
            ?,
            ?,
            ?,
            ?,
            ?,
            ?,
            ?,
            ?,
            ?,
            ?,
            ?,
            ?,
            ?,
            ?,
            ?
        )
        """

        records = [
            (
                row["timestamp"],
                row["resolution"],
                row["underlying"],
                row["expiry_date"],
                row["strike"],
                row["spot_price"],
                row["call_oi"],
                row["put_oi"],
                row["call_gamma"],
                row["put_gamma"],
                row["call_gex"],
                row["put_gex"],
                row["gross_gex"],
                row["net_gex"],
                row["gex_convention"],
                row["calculation_version"],
                row["gex_quality"],
                row["expiry_state"],
                row["dte_seconds"],
                row["dte_minutes"],
                row["max_gamma"],
                row["gamma_1pct"],
                int(row["extreme_gamma"]),
                json.dumps(
                    row["quality_flags"],
                    separators=(",", ":"),
                ),
            )
            for row in snapshots
        ]

        with self._connect() as connection:

            connection.executemany(
                sql,
                records
            )

            connection.commit()

        return len(records)
    
    # ---------------------------------------------------------
    # Summary
    # ---------------------------------------------------------

    def summary(
        self,
        expiry_date: str,
    ) -> dict:

        with self._connect() as connection:

            row = connection.execute(
                """
                SELECT
                    COUNT(*) AS rows_count,
                    MIN(timestamp) AS first_timestamp,
                    MAX(timestamp) AS last_timestamp,
                    MIN(net_gex) AS min_net_gex,
                    MAX(net_gex) AS max_net_gex,
                    AVG(net_gex) AS avg_net_gex
                FROM gex_snapshots
                WHERE underlying = ?
                  AND expiry_date = ?
                  AND resolution = ?
                  AND gex_convention = ?
                  AND calculation_version = ?
                """,
                (
                    self.UNDERLYING,
                    expiry_date,
                    self.RESOLUTION,
                    self.GEX_CONVENTION,
                    self.CALCULATION_VERSION,
                ),
            ).fetchone()

        return {
            "rows": int(
                row["rows_count"] or 0
            ),
            "first_timestamp": (
                row["first_timestamp"]
            ),
            "last_timestamp": (
                row["last_timestamp"]
            ),
            "min_net_gex": (
                float(row["min_net_gex"])
                if row["min_net_gex"] is not None
                else None
            ),
            "max_net_gex": (
                float(row["max_net_gex"])
                if row["max_net_gex"] is not None
                else None
            ),
            "avg_net_gex": (
                float(row["avg_net_gex"])
                if row["avg_net_gex"] is not None
                else None
            ),
        }

    # ---------------------------------------------------------
    # Sample
    # ---------------------------------------------------------

    def run_sample(self) -> dict:

        result = self.build(
            expiry_date="2024-11-28",
        )

        result[
            "summary"
        ] = self.summary(
            expiry_date="2024-11-28"
        )

        return result


# =============================================================
# CLI
# =============================================================

def main() -> None:

    parser = argparse.ArgumentParser(
        description=(
            "Kunal Quant - GEX Engine V1"
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

    args = parser.parse_args()

    engine = GEXEngine()

    if args.sample:

        result = engine.run_sample()

    else:

        if not args.expiry:

            raise SystemExit(
                "--expiry is required."
            )

        result = engine.build(
            expiry_date=args.expiry
        )

    print(
        "\n" + "=" * 75
    )

    print(
        "KUNAL QUANT - GEX ENGINE V1"
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