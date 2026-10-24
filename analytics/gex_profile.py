
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
from typing import Any

from config.settings import DATABASE_PATH


class GEXProfileEngine:
    """
    Kunal Quant - GEX Profile Engine V1.2.

    Read-only analytical layer built on top of the validated
    gex_snapshots table.

    V1.2 adds:
        - spot-centered ATM detection
        - configurable ATM strike window
        - ATM-window GEX totals
        - positive / negative GEX filtering

    This engine does NOT recalculate GEX.
    """

    UNDERLYING = "NIFTY"
    RESOLUTION = "1"

    GEX_CONVENTION = (
        "CALL_POSITIVE_PUT_NEGATIVE"
    )

    CALCULATION_VERSION = (
        "gex_v1_black76_ltp"
    )

    # =========================================================
    # DATABASE
    # =========================================================

    def __init__(
        self,
        database_path: Path | str = DATABASE_PATH,
    ) -> None:

        self.database_path = Path(
            database_path
        )

    def _connect(self) -> sqlite3.Connection:

        connection = sqlite3.connect(
            self.database_path
        )

        connection.row_factory = sqlite3.Row

        return connection

    # =========================================================
    # LATEST TIMESTAMP
    # =========================================================

    def get_latest_timestamp(
        self,
        expiry_date: str,
    ) -> int | None:

        with self._connect() as connection:

            row = connection.execute(
                """
                SELECT MAX(timestamp) AS latest_timestamp
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

        if row is None:
            return None

        if row["latest_timestamp"] is None:
            return None

        return int(
            row["latest_timestamp"]
        )

    # =========================================================
    # LATEST PROFILE
    # =========================================================

    def get_latest_profile(
        self,
        expiry_date: str,
        top_n: int = 10,
        atm_radius: int = 2,
    ) -> dict:

        latest_timestamp = (
            self.get_latest_timestamp(
                expiry_date
            )
        )

        if latest_timestamp is None:

            raise ValueError(
                "No GEX snapshots found for "
                f"expiry {expiry_date}."
            )

        with self._connect() as connection:

            rows = connection.execute(
                """
                SELECT
                    timestamp,
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
                    gex_quality,
                    expiry_state,
                    dte_seconds,
                    dte_minutes,
                    max_gamma,
                    gamma_1pct,
                    extreme_gamma,
                    quality_flags
                FROM gex_snapshots
                WHERE underlying = ?
                  AND expiry_date = ?
                  AND resolution = ?
                  AND gex_convention = ?
                  AND calculation_version = ?
                  AND timestamp = ?
                ORDER BY strike
                """,
                (
                    self.UNDERLYING,
                    expiry_date,
                    self.RESOLUTION,
                    self.GEX_CONVENTION,
                    self.CALCULATION_VERSION,
                    latest_timestamp,
                ),
            ).fetchall()

        profile = [
            dict(row)
            for row in rows
        ]

        if not profile:
            raise ValueError(
                "Latest GEX timestamp contains "
                "no strike-level snapshots."
            )

        # =====================================================
        # SPOT / ATM
        # =====================================================

        spot_price = float(
            profile[0]["spot_price"]
        )

        atm_index = min(
            range(len(profile)),
            key=lambda index: abs(
                float(profile[index]["strike"])
                - spot_price
            ),
        )

        atm_row = profile[atm_index]

        atm_strike = float(
            atm_row["strike"]
        )

        atm_distance = (
            spot_price
            - atm_strike
        )

        # =====================================================
        # ATM WINDOW
        # =====================================================

        radius = max(
            0,
            int(atm_radius),
        )

        window_start = max(
            0,
            atm_index - radius,
        )

        window_end = min(
            len(profile),
            atm_index + radius + 1,
        )

        atm_window = profile[
            window_start:window_end
        ]

        # =====================================================
        # POSITIVE / NEGATIVE RANKING
        # =====================================================

        positive = sorted(
            [
                row
                for row in profile
                if float(row["net_gex"]) > 0
            ],
            key=lambda row: float(
                row["net_gex"]
            ),
            reverse=True,
        )

        negative = sorted(
            [
                row
                for row in profile
                if float(row["net_gex"]) < 0
            ],
            key=lambda row: float(
                row["net_gex"]
            ),
        )

        # =====================================================
        # ATM WINDOW SUMMARY
        # =====================================================

        atm_call_gex = sum(
            float(row["call_gex"] or 0.0)
            for row in atm_window
        )

        atm_put_gex = sum(
            float(row["put_gex"] or 0.0)
            for row in atm_window
        )

        atm_gross_gex = sum(
            float(row["gross_gex"] or 0.0)
            for row in atm_window
        )

        atm_net_gex = sum(
            float(row["net_gex"] or 0.0)
            for row in atm_window
        )

        quality_summary = (
            self._build_quality_summary(
                profile
            )
        )

        zero_crossings = (
            self._find_zero_crossings(
                profile
            )
        )

        return {
            "expiry_date": expiry_date,
            "timestamp": latest_timestamp,
            "strike_count": len(profile),

            "spot_price": spot_price,
            "atm_strike": atm_strike,
            "atm_distance_points": atm_distance,

            "atm_radius": radius,

            "atm_window_min_strike": float(
                atm_window[0]["strike"]
            ),
            "atm_window_max_strike": float(
                atm_window[-1]["strike"]
            ),

            "atm_window": atm_window,

            "atm_window_call_gex": (
                atm_call_gex
            ),
            "atm_window_put_gex": (
                atm_put_gex
            ),
            "atm_window_gross_gex": (
                atm_gross_gex
            ),
            "atm_window_net_gex": (
                atm_net_gex
            ),

            "profile": profile,

            "quality_summary": (
                quality_summary
            ),

            "zero_crossings": (
                zero_crossings
            ),

            "top_positive_net_gex": [
                {
                    "strike": row["strike"],
                    "net_gex": row["net_gex"],
                }
                for row in positive[:top_n]
            ],

            "top_negative_net_gex": [
                {
                    "strike": row["strike"],
                    "net_gex": row["net_gex"],
                }
                for row in negative[:top_n]
            ],
        }

    # =========================================================
    # GEX QUALITY SUMMARY
    # =========================================================

    @staticmethod
    def _build_quality_summary(
        profile: list[dict],
    ) -> dict:

        quality_counts: dict[str, int] = {}

        extreme_gamma_count = 0
        near_expiry_count = 0
        expiry_day_count = 0

        for row in profile:

            quality = str(
                row.get(
                    "gex_quality",
                    "UNKNOWN",
                )
            )

            quality_counts[quality] = (
                quality_counts.get(
                    quality,
                    0,
                )
                + 1
            )

            if int(
                row.get(
                    "extreme_gamma",
                    0,
                )
                or 0
            ) == 1:

                extreme_gamma_count += 1

            if (
                row.get("expiry_state")
                == "NEAR_EXPIRY"
            ):

                near_expiry_count += 1

            flags = row.get(
                "quality_flags",
                [],
            )

            if isinstance(
                flags,
                str,
            ):

                try:
                    flags = json.loads(
                        flags
                    )
                except (
                    TypeError,
                    ValueError,
                ):

                    flags = []

            if (
                "EXPIRY_DAY"
                in flags
            ):

                expiry_day_count += 1

        return {
            "quality_counts": quality_counts,

            "extreme_gamma_count": (
                extreme_gamma_count
            ),

            "near_expiry_count": (
                near_expiry_count
            ),

            "expiry_day_count": (
                expiry_day_count
            ),

            "quality_aware": True,
        }

    # =========================================================
    # GEX ZERO CROSSINGS
    # =========================================================

    @staticmethod
    def _find_zero_crossings(
        profile: list[dict],
    ) -> list[dict]:

        crossings = []

        ordered = sorted(
            profile,
            key=lambda row: float(
                row["strike"]
            ),
        )

        for index in range(
            len(ordered) - 1
        ):

            left = ordered[index]

            right = ordered[index + 1]

            left_gex = float(
                left["net_gex"]
            )

            right_gex = float(
                right["net_gex"]
            )

            if left_gex == 0.0:

                crossings.append(
                    {
                        "type": "EXACT_ZERO",
                        "strike": float(
                            left["strike"]
                        ),
                        "net_gex": 0.0,
                    }
                )

                continue

            if right_gex == 0.0:

                crossings.append(
                    {
                        "type": "EXACT_ZERO",
                        "strike": float(
                            right["strike"]
                        ),
                        "net_gex": 0.0,
                    }
                )

                continue

            if (
                left_gex > 0
                and right_gex < 0
            ) or (
                left_gex < 0
                and right_gex > 0
            ):

                left_strike = float(
                    left["strike"]
                )

                right_strike = float(
                    right["strike"]
                )

                zero_strike = (
                    left_strike
                    + (
                        -left_gex
                        / (
                            right_gex
                            - left_gex
                        )
                    )
                    * (
                        right_strike
                        - left_strike
                    )
                )

                crossings.append(
                    {
                        "type": "SIGN_CHANGE",

                        "lower_strike": float(
                            left["strike"]
                        ),

                        "upper_strike": float(
                            right["strike"]
                        ),

                        "estimated_zero_strike": (
                            zero_strike
                        ),

                        "lower_net_gex": (
                            left_gex
                        ),

                        "upper_net_gex": (
                            right_gex
                        ),

                        "lower_quality": (
                            left.get(
                                "gex_quality"
                            )
                        ),

                        "upper_quality": (
                            right.get(
                                "gex_quality"
                            )
                        ),
                    }
                )

        return crossings

    # =========================================================
    # LATEST SUMMARY
    # =========================================================

    def get_latest_summary(
        self,
        expiry_date: str,
    ) -> dict:

        latest_timestamp = (
            self.get_latest_timestamp(
                expiry_date
            )
        )

        if latest_timestamp is None:

            raise ValueError(
                "No GEX snapshots found for "
                f"expiry {expiry_date}."
            )

        with self._connect() as connection:

            row = connection.execute(
                """
                SELECT
                    COUNT(*) AS strike_count,

                    SUM(call_gex)
                        AS total_call_gex,

                    SUM(put_gex)
                        AS total_put_gex,

                    SUM(gross_gex)
                        AS total_gross_gex,

                    SUM(net_gex)
                        AS total_net_gex,

                    AVG(spot_price)
                        AS average_spot

                FROM gex_snapshots
                WHERE underlying = ?
                  AND expiry_date = ?
                  AND resolution = ?
                  AND gex_convention = ?
                  AND calculation_version = ?
                  AND timestamp = ?
                """,
                (
                    self.UNDERLYING,
                    expiry_date,
                    self.RESOLUTION,
                    self.GEX_CONVENTION,
                    self.CALCULATION_VERSION,
                    latest_timestamp,
                ),
            ).fetchone()

            max_positive = connection.execute(
                """
                SELECT
                    strike,
                    net_gex
                FROM gex_snapshots
                WHERE underlying = ?
                  AND expiry_date = ?
                  AND resolution = ?
                  AND gex_convention = ?
                  AND calculation_version = ?
                  AND timestamp = ?
                  AND net_gex > 0
                ORDER BY net_gex DESC
                LIMIT 1
                """,
                (
                    self.UNDERLYING,
                    expiry_date,
                    self.RESOLUTION,
                    self.GEX_CONVENTION,
                    self.CALCULATION_VERSION,
                    latest_timestamp,
                ),
            ).fetchone()

            max_negative = connection.execute(
                """
                SELECT
                    strike,
                    net_gex
                FROM gex_snapshots
                WHERE underlying = ?
                  AND expiry_date = ?
                  AND resolution = ?
                  AND gex_convention = ?
                  AND calculation_version = ?
                  AND timestamp = ?
                  AND net_gex < 0
                ORDER BY net_gex ASC
                LIMIT 1
                """,
                (
                    self.UNDERLYING,
                    expiry_date,
                    self.RESOLUTION,
                    self.GEX_CONVENTION,
                    self.CALCULATION_VERSION,
                    latest_timestamp,
                ),
            ).fetchone()

        return {
            "timestamp": latest_timestamp,

            "strike_count": int(
                row["strike_count"] or 0
            ),

            "average_spot": (
                float(row["average_spot"])
                if row["average_spot"] is not None
                else None
            ),

            "total_call_gex": float(
                row["total_call_gex"] or 0.0
            ),

            "total_put_gex": float(
                row["total_put_gex"] or 0.0
            ),

            "total_gross_gex": float(
                row["total_gross_gex"] or 0.0
            ),

            "total_net_gex": float(
                row["total_net_gex"] or 0.0
            ),

            "highest_positive_strike": (
                float(max_positive["strike"])
                if max_positive is not None
                else None
            ),

            "highest_positive_net_gex": (
                float(max_positive["net_gex"])
                if max_positive is not None
                else None
            ),

            "most_negative_strike": (
                float(max_negative["strike"])
                if max_negative is not None
                else None
            ),

            "most_negative_net_gex": (
                float(max_negative["net_gex"])
                if max_negative is not None
                else None
            ),
        }

    # =========================================================
    # BUILD PROFILE
    # =========================================================

    def build_profile(
        self,
        expiry_date: str,
        top_n: int = 10,
        atm_radius: int = 2,
    ) -> dict:

        profile = self.get_latest_profile(
            expiry_date=expiry_date,
            top_n=top_n,
            atm_radius=atm_radius,
        )

        summary = self.get_latest_summary(
            expiry_date=expiry_date
        )

        summary.update(
            {
                "atm_strike": (
                    profile["atm_strike"]
                ),
                "atm_distance_points": (
                    profile[
                        "atm_distance_points"
                    ]
                ),
                "atm_window_min_strike": (
                    profile[
                        "atm_window_min_strike"
                    ]
                ),
                "atm_window_max_strike": (
                    profile[
                        "atm_window_max_strike"
                    ]
                ),
                "atm_window_call_gex": (
                    profile[
                        "atm_window_call_gex"
                    ]
                ),
                "atm_window_put_gex": (
                    profile[
                        "atm_window_put_gex"
                    ]
                ),
                "atm_window_gross_gex": (
                    profile[
                        "atm_window_gross_gex"
                    ]
                ),
                "atm_window_net_gex": (
                    profile[
                        "atm_window_net_gex"
                    ]
                ),
            }
        )

        return {
            "underlying": self.UNDERLYING,
            "expiry_date": expiry_date,
            "resolution": self.RESOLUTION,

            "gex_convention": (
                self.GEX_CONVENTION
            ),

            "calculation_version": (
                self.CALCULATION_VERSION
            ),

            "quality_summary": (
                profile[
                    "quality_summary"
                ]
            ),

            "zero_crossings": (
                profile[
                    "zero_crossings"
                ]
            ),

            "spot_price": profile["spot_price"],
            "atm_strike": profile["atm_strike"],
            "atm_distance_points": (
                profile["atm_distance_points"]
            ),

            "atm_radius": profile["atm_radius"],

            "atm_window_min_strike": (
                profile[
                    "atm_window_min_strike"
                ]
            ),

            "atm_window_max_strike": (
                profile[
                    "atm_window_max_strike"
                ]
            ),

            "atm_window": profile[
                "atm_window"
            ],

            "atm_window_call_gex": (
                profile[
                    "atm_window_call_gex"
                ]
            ),

            "atm_window_put_gex": (
                profile[
                    "atm_window_put_gex"
                ]
            ),

            "atm_window_gross_gex": (
                profile[
                    "atm_window_gross_gex"
                ]
            ),

            "atm_window_net_gex": (
                profile[
                    "atm_window_net_gex"
                ]
            ),

            "summary": summary,

            "profile": profile[
                "profile"
            ],

            "top_positive_net_gex": (
                profile[
                    "top_positive_net_gex"
                ]
            ),

            "top_negative_net_gex": (
                profile[
                    "top_negative_net_gex"
                ]
            ),
        }

    # =========================================================
    # SAMPLE
    # =========================================================

    def run_sample(self) -> dict:

        return self.build_profile(
            expiry_date="2024-11-28",
            top_n=5,
            atm_radius=2,
        )


# =============================================================
# CLI
# =============================================================

def main() -> None:

    parser = argparse.ArgumentParser(
        description=(
            "Kunal Quant - "
            "GEX Profile Engine V1.2"
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
        help="Expiry date YYYY-MM-DD.",
    )

    parser.add_argument(
        "--top-n",
        type=int,
        default=10,
        help="Number of top positive/negative strikes.",
    )

    parser.add_argument(
        "--atm-radius",
        type=int,
        default=2,
        help=(
            "Number of strikes on each side "
            "of ATM. Default: 2."
        ),
    )

    args = parser.parse_args()

    engine = GEXProfileEngine()

    if args.sample:

        result = engine.run_sample()

    else:

        if not args.expiry:

            raise SystemExit(
                "--expiry is required."
            )

        result = engine.build_profile(
            expiry_date=args.expiry,
            top_n=max(
                1,
                args.top_n,
            ),
            atm_radius=max(
                0,
                args.atm_radius,
            ),
        )

    print()
    print("=" * 75)
    print(
        "KUNAL QUANT - "
        "GEX PROFILE ENGINE V1.2"
    )
    print("=" * 75)

    print(
        json.dumps(
            result,
            indent=2,
            default=str,
        )
    )

    print()
    print("=" * 75)


if __name__ == "__main__":
    main()
