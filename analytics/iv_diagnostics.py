from __future__ import annotations

import argparse
import json
import math
import sqlite3
from pathlib import Path

from config.settings import DATABASE_PATH


class IVDiagnostics:
    """
    Kunal Quant - IV Diagnostic Engine V1.

    Explains why option observations did not produce a valid IV.

    This module does not modify option_analytics or candles.
    It only reads existing data and reports diagnostic reasons.
    """

    CALCULATION_VERSION = "black76_iv_greeks_v1"

    OPTION_SOURCE = "FYERS_FNO_HISTORY"

    IV_MIN = 0.0001

    IV_MAX = 5.0

    def __init__(
        self,
        database_path: Path | str = DATABASE_PATH,
    ) -> None:

        self.database_path = Path(
            database_path
        )

    # =========================================================
    # DATABASE
    # =========================================================

    def _connect(self) -> sqlite3.Connection:

        connection = sqlite3.connect(
            self.database_path
        )

        connection.row_factory = sqlite3.Row

        return connection

    # =========================================================
    # NORMAL DISTRIBUTION
    # =========================================================

    @staticmethod
    def normal_cdf(
        x: float,
    ) -> float:

        return (
            0.5
            * (
                1.0
                + math.erf(
                    x
                    / math.sqrt(2.0)
                )
            )
        )

    # =========================================================
    # BLACK-76 PRICE
    # =========================================================

    def black76_price(
        self,
        forward_price: float,
        strike: float,
        time_to_expiry: float,
        volatility: float,
        option_type: str,
    ) -> float | None:

        if (
            forward_price <= 0
            or strike <= 0
            or time_to_expiry <= 0
            or volatility <= 0
        ):

            return None

        sqrt_t = math.sqrt(
            time_to_expiry
        )

        d1 = (
            math.log(
                forward_price
                / strike
            )
            + 0.5
            * volatility
            * volatility
            * time_to_expiry
        ) / (
            volatility
            * sqrt_t
        )

        d2 = (
            d1
            - volatility
            * sqrt_t
        )

        nd1 = self.normal_cdf(
            d1
        )

        nd2 = self.normal_cdf(
            d2
        )

        if option_type == "CE":

            return (
                forward_price * nd1
                - strike * nd2
            )

        return (
            strike * self.normal_cdf(-d2)
            - forward_price
            * self.normal_cdf(-d1)
        )

    # =========================================================
    # DIAGNOSE ONE ROW
    # =========================================================

    def diagnose(
        self,
        option_price: float | None,
        forward_price: float | None,
        strike: float | None,
        dte: float | None,
        option_type: str,
    ) -> str:

        if (
            option_price is None
            or option_price <= 0
        ):

            return "NON_POSITIVE_OPTION_PRICE"

        if (
            forward_price is None
            or forward_price <= 0
        ):

            return "INVALID_FORWARD_PRICE"

        if (
            strike is None
            or strike <= 0
        ):

            return "INVALID_STRIKE"

        if (
            dte is None
            or dte <= 0
        ):

            return "NON_POSITIVE_DTE"

        time_to_expiry = (
            dte / 365.0
        )

        option_type = option_type.upper()

        if option_type == "CE":

            intrinsic = max(
                forward_price
                - strike,
                0.0
            )

            upper_bound = (
                forward_price
            )

        else:

            intrinsic = max(
                strike
                - forward_price,
                0.0
            )

            upper_bound = strike

        if (
            option_price
            < intrinsic - 1e-8
        ):

            return "BELOW_INTRINSIC_VALUE"

        if (
            option_price
            > upper_bound + 1e-8
        ):

            return "ABOVE_THEORETICAL_UPPER_BOUND"

        low_price = self.black76_price(
            forward_price=forward_price,
            strike=strike,
            time_to_expiry=time_to_expiry,
            volatility=self.IV_MIN,
            option_type=option_type,
        )

        high_price = self.black76_price(
            forward_price=forward_price,
            strike=strike,
            time_to_expiry=time_to_expiry,
            volatility=self.IV_MAX,
            option_type=option_type,
        )

        if low_price is None:

            return "LOW_IV_BOUND_FAILURE"

        if high_price is None:

            return "HIGH_IV_BOUND_FAILURE"

        if option_price < low_price - 1e-8:

            return "BELOW_IV_SOLVER_RANGE"

        if option_price > high_price + 1e-8:

            return "ABOVE_IV_SOLVER_RANGE"

        return "OTHER"

    # =========================================================
    # DIAGNOSE DATABASE
    # =========================================================

    def run(
        self,
        limit: int | None = None,
    ) -> dict:

        query = """
        SELECT
            oa.instrument_id,
            oa.timestamp,
            oa.forward_price,
            oa.expiry_date,
            oa.strike,
            oa.option_type,
            oa.dte,
            i.symbol,
            c.close AS option_price
        FROM option_analytics oa

        JOIN instruments i
          ON i.id = oa.instrument_id

        JOIN candles c
          ON c.instrument_id = oa.instrument_id
         AND c.timestamp = oa.timestamp
         AND c.resolution = oa.resolution
         AND c.source = ?

        WHERE oa.calculation_version = ?
          AND oa.implied_volatility IS NULL

        ORDER BY oa.timestamp, oa.instrument_id
        """

        parameters = [
            self.OPTION_SOURCE,
            self.CALCULATION_VERSION,
        ]

        if limit is not None:

            query += """
            LIMIT ?
            """

            parameters.append(
                int(limit)
            )

        with self._connect() as connection:

            rows = connection.execute(
                query,
                parameters,
            ).fetchall()

        counts: dict[str, int] = {}

        examples: dict[str, dict] = {}

        for row in rows:

            reason = self.diagnose(
                option_price=(
                    float(row["option_price"])
                    if row["option_price"] is not None
                    else None
                ),
                forward_price=(
                    float(row["forward_price"])
                    if row["forward_price"] is not None
                    else None
                ),
                strike=(
                    float(row["strike"])
                    if row["strike"] is not None
                    else None
                ),
                dte=(
                    float(row["dte"])
                    if row["dte"] is not None
                    else None
                ),
                option_type=str(
                    row["option_type"]
                ),
            )

            counts[reason] = (
                counts.get(
                    reason,
                    0
                )
                + 1
            )

            if reason not in examples:

                examples[reason] = {
                    "symbol": row["symbol"],
                    "timestamp": row["timestamp"],
                    "option_price": (
                        row["option_price"]
                    ),
                    "forward_price": (
                        row["forward_price"]
                    ),
                    "strike": row["strike"],
                    "option_type": (
                        row["option_type"]
                    ),
                    "dte": row["dte"],
                }

        total = len(rows)

        return {
            "calculation_version": (
                self.CALCULATION_VERSION
            ),
            "invalid_rows_analyzed": total,
            "reason_counts": counts,
            "examples": examples,
        }


# =============================================================
# CLI
# =============================================================

def main() -> None:

    parser = argparse.ArgumentParser(
        description=(
            "Kunal Quant - IV Diagnostic Engine"
        )
    )

    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Optional diagnostic row limit.",
    )

    args = parser.parse_args()

    engine = IVDiagnostics()

    result = engine.run(
        limit=args.limit
    )

    print(
        "\n" + "=" * 75
    )

    print(
        "KUNAL QUANT - IV DIAGNOSTICS"
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