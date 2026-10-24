from __future__ import annotations

import argparse
import json
import math
import sqlite3
from pathlib import Path

from config.settings import (
    DATABASE_PATH,
)


class FlowAnalytics:
    """
    Kunal Quant OI + Price Flow Analytics V1.

    Converts raw derivative candles into a
    visual-friendly flow representation.

    Core inputs:

        Price
        Open Interest
        Volume

    Core outputs:

        Price Change
        OI Change
        Price/OI directions
        Flow state
        Flow strength

    No future candles are used in the calculation.
    """

    DERIVATIVE_TYPES = {
        "11",
        "14",
        11,
        14,
    }

    LOOKBACK = 20

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
    # CANDLE DATA
    # =========================================================

    def _get_instrument(
        self,
        symbol: str,
    ) -> dict | None:

        query = """
        SELECT *
        FROM instruments

        WHERE broker = 'FYERS'
          AND symbol = ?

        LIMIT 1
        """

        with self._connect() as connection:

            row = connection.execute(
                query,
                (symbol,)
            ).fetchone()

        if row is None:

            return None

        return dict(row)

    def _get_candles(
        self,
        instrument_id: int,
        resolution: str,
        source: str,
    ) -> list[dict]:

        query = """
        SELECT
            timestamp,
            open,
            high,
            low,
            close,
            volume,
            open_interest

        FROM candles

        WHERE instrument_id = ?
          AND resolution = ?
          AND source = ?

        ORDER BY timestamp
        """

        with self._connect() as connection:

            rows = connection.execute(
                query,
                (
                    instrument_id,
                    resolution,
                    source,
                )
            ).fetchall()

        return [
            dict(row)
            for row in rows
        ]

    # =========================================================
    # NUMERIC HELPERS
    # =========================================================

    @staticmethod
    def _safe_pct_change(
        current: float | None,
        previous: float | None,
    ) -> float | None:

        if current is None:
            return None

        if previous is None:
            return None

        if previous == 0:
            return None

        return (
            (
                current
                - previous
            )
            / abs(previous)
        ) * 100.0

    @staticmethod
    def _direction(
        change: float | None,
        tolerance: float = 0.0,
    ) -> int:

        if change is None:
            return 0

        if change > tolerance:
            return 1

        if change < -tolerance:
            return -1

        return 0

    @staticmethod
    def _median(
        values: list[float],
    ) -> float:

        if not values:
            return 0.0

        ordered = sorted(
            values
        )

        middle = len(
            ordered
        ) // 2

        if len(ordered) % 2:

            return ordered[middle]

        return (
            ordered[middle - 1]
            + ordered[middle]
        ) / 2.0

    @staticmethod
    def _clamp(
        value: float,
        low: float,
        high: float,
    ) -> float:

        return max(
            low,
            min(
                value,
                high
            )
        )

    # =========================================================
    # FLOW STATE
    # =========================================================

    @staticmethod
    def _flow_state(
        price_direction: int,
        oi_direction: int,
    ) -> str:

        if (
            price_direction > 0
            and oi_direction > 0
        ):

            return "PRICE_UP_OI_UP"

        if (
            price_direction < 0
            and oi_direction > 0
        ):

            return "PRICE_DOWN_OI_UP"

        if (
            price_direction > 0
            and oi_direction < 0
        ):

            return "PRICE_UP_OI_DOWN"

        if (
            price_direction < 0
            and oi_direction < 0
        ):

            return "PRICE_DOWN_OI_DOWN"

        return "NEUTRAL"

    # =========================================================
    # FLOW STRENGTH
    # =========================================================

    def _flow_strength(
        self,
        price_change_pct: float | None,
        oi_change_pct: float | None,
        previous_price_moves: list[float],
        previous_oi_moves: list[float],
    ) -> float | None:

        if (
            price_change_pct is None
            or oi_change_pct is None
        ):

            return None

        price_baseline = self._median(
            [
                abs(value)
                for value
                in previous_price_moves
                if value is not None
            ]
        )

        oi_baseline = self._median(
            [
                abs(value)
                for value
                in previous_oi_moves
                if value is not None
            ]
        )

        # Not enough historical context.
        if (
            price_baseline <= 0
            or oi_baseline <= 0
        ):

            return None

        price_ratio = (
            abs(price_change_pct)
            / price_baseline
        )

        oi_ratio = (
            abs(oi_change_pct)
            / oi_baseline
        )

        # Cap each component at 5x its
        # recent median move.
        price_normalized = (
            self._clamp(
                price_ratio / 5.0,
                0.0,
                1.0,
            )
        )

        oi_normalized = (
            self._clamp(
                oi_ratio / 5.0,
                0.0,
                1.0,
            )
        )

        strength = (
            math.sqrt(
                price_normalized
                * oi_normalized
            )
            * 100.0
        )

        return round(
            strength,
            4
        )

    # =========================================================
    # CALCULATE
    # =========================================================

    def calculate(
        self,
        symbol: str,
        resolution: str = "1",
        source: str = "FYERS_FNO_HISTORY",
        replace_existing: bool = True,
    ) -> dict:

        instrument = self._get_instrument(
            symbol
        )

        if instrument is None:

            raise ValueError(
                f"Instrument not found: {symbol}"
            )

        instrument_type = (
            instrument.get(
                "instrument_type"
            )
        )

        if instrument_type not in (
            self.DERIVATIVE_TYPES
        ):

            raise ValueError(
                f"Flow analytics requires a "
                f"derivative instrument: {symbol}"
            )

        instrument_id = int(
            instrument["id"]
        )

        candles = self._get_candles(
            instrument_id=instrument_id,
            resolution=resolution,
            source=source,
        )

        if not candles:

            raise ValueError(
                f"No candles found for {symbol}."
            )

        # -----------------------------------------------------
        # Existing derived rows
        # -----------------------------------------------------

        if replace_existing:

            with self._connect() as connection:

                connection.execute(
                    """
                    DELETE FROM flow_metrics
                    WHERE instrument_id = ?
                      AND resolution = ?
                    """,
                    (
                        instrument_id,
                        resolution,
                    )
                )

                connection.commit()

        previous_price = None
        previous_oi = None
        previous_volume = None

        previous_price_moves: list[
            float
        ] = []

        previous_oi_moves: list[
            float
        ] = []

        output: list[dict] = []

        for candle in candles:

            close = float(
                candle["close"]
            )

            volume = (
                int(
                    candle["volume"]
                )
                if candle["volume"] is not None
                else None
            )

            oi = (
                int(
                    candle["open_interest"]
                )
                if candle["open_interest"] is not None
                else None
            )

            # -------------------------------------------------
            # PRICE
            # -------------------------------------------------

            price_change = None

            price_change_pct = None

            if previous_price is not None:

                price_change = (
                    close
                    - previous_price
                )

                price_change_pct = (
                    self._safe_pct_change(
                        close,
                        previous_price,
                    )
                )

            # -------------------------------------------------
            # OI
            # -------------------------------------------------

            oi_change = None

            oi_change_pct = None

            if (
                oi is not None
                and previous_oi is not None
            ):

                oi_change = (
                    oi
                    - previous_oi
                )

                oi_change_pct = (
                    self._safe_pct_change(
                        float(oi),
                        float(previous_oi),
                    )
                )

            # -------------------------------------------------
            # VOLUME
            # -------------------------------------------------

            volume_change = None

            volume_change_pct = None

            if (
                volume is not None
                and previous_volume is not None
            ):

                volume_change = (
                    volume
                    - previous_volume
                )

                volume_change_pct = (
                    self._safe_pct_change(
                        float(volume),
                        float(previous_volume),
                    )
                )

            # -------------------------------------------------
            # DIRECTIONS
            # -------------------------------------------------

            price_direction = (
                self._direction(
                    price_change
                )
            )

            oi_direction = (
                self._direction(
                    oi_change
                )
            )

            flow_state = (
                self._flow_state(
                    price_direction,
                    oi_direction,
                )
            )

            # -------------------------------------------------
            # STRENGTH
            # -------------------------------------------------

            strength = (
                self._flow_strength(
                    price_change_pct,
                    oi_change_pct,
                    previous_price_moves,
                    previous_oi_moves,
                )
            )

            record = {
                "instrument_id": instrument_id,
                "timestamp": int(
                    candle["timestamp"]
                ),
                "resolution": resolution,
                "price_change": price_change,
                "price_change_pct": (
                    price_change_pct
                ),
                "oi_change": oi_change,
                "oi_change_pct": oi_change_pct,
                "volume_change": volume_change,
                "volume_change_pct": (
                    volume_change_pct
                ),
                "price_direction": (
                    price_direction
                ),
                "oi_direction": (
                    oi_direction
                ),
                "flow_state": flow_state,
                "flow_strength": strength,
                "calculation_version": "flow_v1",
            }

            output.append(
                record
            )

            # -------------------------------------------------
            # Update rolling history AFTER
            # calculation, preventing look-ahead.
            # -------------------------------------------------

            if price_change_pct is not None:

                previous_price_moves.append(
                    price_change_pct
                )

                if len(
                    previous_price_moves
                ) > self.LOOKBACK:

                    previous_price_moves.pop(
                        0
                    )

            if oi_change_pct is not None:

                previous_oi_moves.append(
                    oi_change_pct
                )

                if len(
                    previous_oi_moves
                ) > self.LOOKBACK:

                    previous_oi_moves.pop(
                        0
                    )

            previous_price = close

            previous_oi = oi

            previous_volume = volume

        # =====================================================
        # STORE
        # =====================================================

        sql = """
        INSERT OR REPLACE INTO flow_metrics (
            instrument_id,
            timestamp,
            resolution,
            price_change,
            price_change_pct,
            oi_change,
            oi_change_pct,
            volume_change,
            volume_change_pct,
            price_direction,
            oi_direction,
            flow_state,
            flow_strength,
            calculation_version
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
            ?
        )
        """

        records = [
            (
                row["instrument_id"],
                row["timestamp"],
                row["resolution"],
                row["price_change"],
                row["price_change_pct"],
                row["oi_change"],
                row["oi_change_pct"],
                row["volume_change"],
                row["volume_change_pct"],
                row["price_direction"],
                row["oi_direction"],
                row["flow_state"],
                row["flow_strength"],
                row["calculation_version"],
            )
            for row in output
        ]

        with self._connect() as connection:

            connection.executemany(
                sql,
                records
            )

            connection.commit()

        summary = {
            "symbol": symbol,
            "instrument_id": instrument_id,
            "resolution": resolution,
            "source": source,
            "candles_processed": len(
                candles
            ),
            "flow_rows_written": len(
                output
            ),
            "price_up_oi_up": sum(
                1
                for row in output
                if row["flow_state"]
                == "PRICE_UP_OI_UP"
            ),
            "price_down_oi_up": sum(
                1
                for row in output
                if row["flow_state"]
                == "PRICE_DOWN_OI_UP"
            ),
            "price_up_oi_down": sum(
                1
                for row in output
                if row["flow_state"]
                == "PRICE_UP_OI_DOWN"
            ),
            "price_down_oi_down": sum(
                1
                for row in output
                if row["flow_state"]
                == "PRICE_DOWN_OI_DOWN"
            ),
            "neutral": sum(
                1
                for row in output
                if row["flow_state"]
                == "NEUTRAL"
            ),
        }

        return summary

    # =========================================================
    # SAMPLE
    # =========================================================

    def run_sample(self) -> list[dict]:

        samples = [
            (
                "NSE:NIFTY24NOVFUT",
                "FYERS_FNO_HISTORY",
            ),
            (
                "NSE:NIFTY24NOV22500CE",
                "FYERS_FNO_HISTORY",
            ),
            (
                "NSE:NIFTY24NOV22500PE",
                "FYERS_FNO_HISTORY",
            ),
        ]

        results = []

        for symbol, source in samples:

            print(
                f"\nCalculating flow: {symbol}"
            )

            result = self.calculate(
                symbol=symbol,
                resolution="1",
                source=source,
            )

            results.append(
                result
            )

            print(
                f"  Rows written: "
                f"{result['flow_rows_written']}"
            )

            print(
                f"  Price ↑ / OI ↑: "
                f"{result['price_up_oi_up']}"
            )

            print(
                f"  Price ↓ / OI ↑: "
                f"{result['price_down_oi_up']}"
            )

            print(
                f"  Price ↑ / OI ↓: "
                f"{result['price_up_oi_down']}"
            )

            print(
                f"  Price ↓ / OI ↓: "
                f"{result['price_down_oi_down']}"
            )

            print(
                f"  Neutral: "
                f"{result['neutral']}"
            )

        return results


# =============================================================
# CLI
# =============================================================

def main() -> None:

    parser = argparse.ArgumentParser(
        description=(
            "Kunal Quant - OI + Price Flow Analytics"
        )
    )

    parser.add_argument(
        "--symbol",
        type=str,
        default=None,
        help="Derivative symbol.",
    )

    parser.add_argument(
        "--source",
        type=str,
        default="FYERS_FNO_HISTORY",
        help="Candle source.",
    )

    parser.add_argument(
        "--sample",
        action="store_true",
        help="Run the controlled derivative sample.",
    )

    args = parser.parse_args()

    print("=" * 75)

    print(
        "KUNAL QUANT - OI + PRICE FLOW ENGINE"
    )

    print("=" * 75)

    engine = FlowAnalytics()

    if args.sample:

        results = engine.run_sample()

    elif args.symbol:

        results = [
            engine.calculate(
                symbol=args.symbol,
                resolution="1",
                source=args.source,
            )
        ]

    else:

        raise SystemExit(
            "Use --sample or --symbol."
        )

    print(
        "\n" + "=" * 75
    )

    print(
        "FLOW ANALYTICS RESULT"
    )

    print(
        "=" * 75
    )

    print(
        json.dumps(
            results,
            indent=2,
        )
    )

    print(
        "\n" + "=" * 75
    )

    print(
        "FLOW ANALYTICS COMPLETE"
    )

    print(
        "=" * 75
    )


if __name__ == "__main__":

    main()