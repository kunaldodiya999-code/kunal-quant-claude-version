"""
KUNAL QUANT
Option Contract Resolver V2

Purpose
-------
Resolve an actual NIFTY option contract from the existing
instrument database.

Flow:

NIFTY price
    ↓
ATM strike
    ↓
LONG  -> CE
SHORT -> PE
    ↓
nearest eligible expiry
    ↓
actual FYERS instrument
    ↓
actual FYERS symbol

IMPORTANT
---------
This module does NOT download data.

It only resolves contracts already present in the
'instruments' table.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from config.settings import DATABASE_PATH


# =====================================================================
# DATA MODELS
# =====================================================================


@dataclass(frozen=True)
class ResolvedOptionContract:
    instrument_id: int
    symbol: str
    underlying: str
    expiry_date: date
    strike: int
    option_type: str


@dataclass(frozen=True)
class OptionResolverConfig:
    strike_step: int = 50


DEFAULT_OPTION_RESOLVER_CONFIG = OptionResolverConfig()


# =====================================================================
# RESOLVER
# =====================================================================


class OptionContractResolver:
    """
    Resolve actual NIFTY option contracts from the local database.
    """

    def __init__(
        self,
        database_path: Path | str = DATABASE_PATH,
        config: OptionResolverConfig = (
            DEFAULT_OPTION_RESOLVER_CONFIG
        ),
    ) -> None:

        self.database_path = Path(database_path)
        self.config = config

    # -----------------------------------------------------------------
    # DATABASE
    # -----------------------------------------------------------------

    def _connect(self) -> sqlite3.Connection:

        connection = sqlite3.connect(
            self.database_path
        )

        connection.row_factory = sqlite3.Row

        return connection

    # -----------------------------------------------------------------
    # ATM STRIKE
    # -----------------------------------------------------------------

    def calculate_atm_strike(
        self,
        underlying_price: float,
    ) -> int:

        if underlying_price <= 0:
            raise ValueError(
                "Underlying price must be positive."
            )

        step = self.config.strike_step

        if step <= 0:
            raise ValueError(
                "Strike step must be positive."
            )

        return int(
            round(
                underlying_price / step
            ) * step
        )

    # -----------------------------------------------------------------
    # FIND NEAREST EXPIRY
    # -----------------------------------------------------------------

    def find_nearest_expiry(
        self,
        entry_date: date,
        option_type: str,
    ) -> date:

        option_type = option_type.upper()

        if option_type not in ("CE", "PE"):
            raise ValueError(
                "option_type must be CE or PE."
            )

        with self._connect() as connection:

            row = connection.execute(
                """
                SELECT MIN(expiry_date) AS expiry_date
                FROM instruments
                WHERE broker = 'FYERS'
                  AND underlying = 'NIFTY'
                  AND option_type = ?
                  AND expiry_date >= ?
                """,
                (
                    option_type,
                    entry_date.isoformat(),
                ),
            ).fetchone()

        if row is None or row["expiry_date"] is None:

            raise LookupError(
                f"No {option_type} expiry found "
                f"on/after {entry_date}."
            )

        return date.fromisoformat(
            row["expiry_date"]
        )

    # -----------------------------------------------------------------
    # RESOLVE EXACT CONTRACT
    # -----------------------------------------------------------------

    def resolve(
        self,
        *,
        underlying_price: float,
        entry_date: date,
        direction: str,
    ) -> ResolvedOptionContract:

        direction = direction.upper()

        if direction == "LONG":
            option_type = "CE"

        elif direction == "SHORT":
            option_type = "PE"

        else:
            raise ValueError(
                "direction must be LONG or SHORT."
            )

        strike = self.calculate_atm_strike(
            underlying_price
        )

        expiry = self.find_nearest_expiry(
            entry_date=entry_date,
            option_type=option_type,
        )

        with self._connect() as connection:

            rows = connection.execute(
                """
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
                  AND strike = ?
                  AND option_type = ?
                ORDER BY symbol
                """,
                (
                    expiry.isoformat(),
                    strike,
                    option_type,
                ),
            ).fetchall()

        if not rows:

            raise LookupError(
                "Exact option contract not found: "
                f"NIFTY {expiry} {strike} {option_type}"
            )

        row = rows[0]

        return ResolvedOptionContract(
            instrument_id=int(row["id"]),
            symbol=str(row["symbol"]),
            underlying=str(row["underlying"]),
            expiry_date=date.fromisoformat(
                row["expiry_date"]
            ),
            strike=int(row["strike"]),
            option_type=str(row["option_type"]),
        )


# =====================================================================
# SIMPLE HELPERS
# =====================================================================


def resolve_nifty_option(
    *,
    underlying_price: float,
    entry_date: date,
    direction: str,
    database_path: Path | str = DATABASE_PATH,
) -> ResolvedOptionContract:

    resolver = OptionContractResolver(
        database_path=database_path
    )

    return resolver.resolve(
        underlying_price=underlying_price,
        entry_date=entry_date,
        direction=direction,
    )