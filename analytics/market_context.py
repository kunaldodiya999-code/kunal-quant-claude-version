from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

from config.settings import (
    DATABASE_PATH,
)


class MarketContextBuilder:
    """
    Kunal Quant Market Context V1.

    Synchronizes:

        NIFTY spot
        India VIX
        NIFTY futures
        NIFTY option chain

    into the market_context table.

    The purpose of this layer is to give the
    backtester one timestamp-aligned market state.

    Raw broker data remains in candles.
    Calculated analytics remain in their
    respective analytical tables.
    """

    TIMEZONE = ZoneInfo(
        "Asia/Kolkata"
    )

    UNDERLYING = "NIFTY"

    SPOT_SYMBOL = "NSE:NIFTY50-INDEX"

    VIX_SYMBOL = "NSE:INDIAVIX-INDEX"

    DEFAULT_RESOLUTION = "1"

    SPOT_SOURCE = "FYERS_HISTORY"

    VIX_SOURCE = "FYERS_HISTORY"

    FUTURES_SOURCE = "FYERS_FNO_HISTORY"

    OPTIONS_SOURCE = "FYERS_FNO_HISTORY"

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
    # INSTRUMENT
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

    # =========================================================
    # DATE / TIMESTAMP HELPERS
    # =========================================================

    @classmethod
    def _date_timestamp_range(
        cls,
        range_from: str,
        range_to: str,
    ) -> tuple[int, int]:

        start_date = datetime.strptime(
            range_from,
            "%Y-%m-%d"
        ).date()

        end_date = datetime.strptime(
            range_to,
            "%Y-%m-%d"
        ).date()

        start_dt = datetime.combine(
            start_date,
            time(
                9,
                15
            ),
            tzinfo=cls.TIMEZONE,
        )

        end_dt = datetime.combine(
            end_date,
            time(
                15,
                29
            ),
            tzinfo=cls.TIMEZONE,
        )

        return (
            int(start_dt.timestamp()),
            int(end_dt.timestamp()),
        )

    # =========================================================
    # CORE SERIES
    # =========================================================

    def _get_series(
        self,
        symbol: str,
        resolution: str,
        source: str,
        start_timestamp: int,
        end_timestamp: int,
    ) -> dict[int, dict]:

        instrument = self._get_instrument(
            symbol
        )

        if instrument is None:

            raise ValueError(
                f"Instrument not found: {symbol}"
            )

        instrument_id = int(
            instrument["id"]
        )

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
          AND timestamp BETWEEN ? AND ?

        ORDER BY timestamp
        """

        with self._connect() as connection:

            rows = connection.execute(
                query,
                (
                    instrument_id,
                    resolution,
                    source,
                    start_timestamp,
                    end_timestamp,
                )
            ).fetchall()

        return {
            int(row["timestamp"]): {
                "timestamp": int(
                    row["timestamp"]
                ),
                "open": row["open"],
                "high": row["high"],
                "low": row["low"],
                "close": row["close"],
                "volume": row["volume"],
                "open_interest": row[
                    "open_interest"
                ],
            }
            for row in rows
        }

    # =========================================================
    # OPTION CHAIN
    # =========================================================

    def _get_option_chain(
        self,
        expiry_date: str,
        resolution: str,
        start_timestamp: int,
        end_timestamp: int,
    ) -> dict[str, dict[int, dict]]:

        query = """
        SELECT
            i.id AS instrument_id,
            i.symbol,
            i.strike,
            i.option_type,
            c.timestamp,
            c.close,
            c.volume,
            c.open_interest

        FROM instruments i

        INNER JOIN candles c
            ON c.instrument_id = i.id

        WHERE i.broker = 'FYERS'

          AND i.underlying = ?

          AND i.expiry_date = ?

          AND i.option_type IN ('CE', 'PE')

          AND c.resolution = ?

          AND c.source = ?

          AND c.timestamp BETWEEN ? AND ?

        ORDER BY
            c.timestamp,
            i.strike,
            i.option_type
        """

        with self._connect() as connection:

            rows = connection.execute(
                query,
                (
                    self.UNDERLYING,
                    expiry_date,
                    resolution,
                    self.OPTIONS_SOURCE,
                    start_timestamp,
                    end_timestamp,
                )
            ).fetchall()

        chain: dict[
            str,
            dict[int, dict]
        ] = {}

        for row in rows:

            symbol = row["symbol"]

            chain.setdefault(
                symbol,
                {}
            )

            chain[symbol][
                int(row["timestamp"])
            ] = {
                "instrument_id": int(
                    row["instrument_id"]
                ),
                "symbol": symbol,
                "strike": (
                    float(row["strike"])
                    if row["strike"] is not None
                    else None
                ),
                "option_type": row[
                    "option_type"
                ],
                "timestamp": int(
                    row["timestamp"]
                ),
                "close": row["close"],
                "volume": row["volume"],
                "open_interest": row[
                    "open_interest"
                ],
            }

        return chain

    # =========================================================
    # OPTION ANALYTICS LOOKUP
    # =========================================================

    def _get_option_iv_map(
        self,
        instrument_ids: list[int],
        resolution: str,
        start_timestamp: int,
        end_timestamp: int,
    ) -> dict[tuple[int, int], dict]:

        if not instrument_ids:

            return {}

        placeholders = ",".join(
            "?"
            for _ in instrument_ids
        )

        query = f"""
        SELECT
            instrument_id,
            timestamp,
            implied_volatility,
            delta,
            gamma,
            theta,
            vega,
            rho

        FROM option_analytics

        WHERE instrument_id IN (
            {placeholders}
        )

          AND resolution = ?

          AND timestamp BETWEEN ? AND ?
        """

        parameters = [
            *instrument_ids,
            resolution,
            start_timestamp,
            end_timestamp,
        ]

        with self._connect() as connection:

            rows = connection.execute(
                query,
                parameters,
            ).fetchall()

        return {
            (
                int(row["instrument_id"]),
                int(row["timestamp"]),
            ): dict(row)
            for row in rows
        }

    # =========================================================
    # OPTION SNAPSHOT
    # =========================================================

    @staticmethod
    def _option_snapshot(
        chain: dict[str, dict[int, dict]],
        timestamp: int,
        spot_price: float | None,
        option_iv_map: dict[
            tuple[int, int],
            dict,
        ],
    ) -> dict:

        call_total_oi = 0

        put_total_oi = 0

        call_total_oi_valid = True

        put_total_oi_valid = True

        strikes: dict[
            float,
            dict[str, dict | None]
        ] = {}

        for symbol, series in chain.items():

            candle = series.get(
                timestamp
            )

            if candle is None:

                continue

            strike = candle.get(
                "strike"
            )

            option_type = candle.get(
                "option_type"
            )

            if strike is None:

                continue

            if strike not in strikes:

                strikes[strike] = {
                    "CE": None,
                    "PE": None,
                }

            strikes[strike][
                option_type
            ] = candle

            oi = candle.get(
                "open_interest"
            )

            if option_type == "CE":

                if oi is None:

                    call_total_oi_valid = False

                else:

                    call_total_oi += int(
                        oi
                    )

            elif option_type == "PE":

                if oi is None:

                    put_total_oi_valid = False

                else:

                    put_total_oi += int(
                        oi
                    )

        # -----------------------------------------------------
        # Only regard OI totals as complete when every
        # available option record has OI.
        #
        # When the full chain is loaded, this provides a
        # cleaner quality signal.
        # -----------------------------------------------------

        total_call_oi = (
            call_total_oi
            if call_total_oi_valid
            else None
        )

        total_put_oi = (
            put_total_oi
            if put_total_oi_valid
            else None
        )

        pcr = None

        if (
            total_call_oi is not None
            and total_call_oi > 0
            and total_put_oi is not None
        ):

            pcr = (
                total_put_oi
                / total_call_oi
            )

        # -----------------------------------------------------
        # ATM
        #
        # Require both CE and PE at the strike so that the
        # ATM premium pair is genuinely synchronized.
        # -----------------------------------------------------

        atm_strike = None

        atm_call = None

        atm_put = None

        if spot_price is not None:

            candidate_strikes = []

            for strike, pair in strikes.items():

                if (
                    pair.get("CE") is not None
                    and pair.get("PE") is not None
                ):

                    candidate_strikes.append(
                        strike
                    )

            if candidate_strikes:

                atm_strike = min(
                    candidate_strikes,
                    key=lambda value: abs(
                        value
                        - spot_price
                    )
                )

                atm_call = strikes[
                    atm_strike
                ]["CE"]

                atm_put = strikes[
                    atm_strike
                ]["PE"]

        atm_call_iv = None

        atm_put_iv = None

        if atm_call is not None:

            analytics = option_iv_map.get(
                (
                    int(
                        atm_call[
                            "instrument_id"
                        ]
                    ),
                    timestamp,
                )
            )

            if analytics is not None:

                atm_call_iv = (
                    analytics[
                        "implied_volatility"
                    ]
                )

        if atm_put is not None:

            analytics = option_iv_map.get(
                (
                    int(
                        atm_put[
                            "instrument_id"
                        ]
                    ),
                    timestamp,
                )
            )

            if analytics is not None:

                atm_put_iv = (
                    analytics[
                        "implied_volatility"
                    ]
                )

        return {
            "total_call_oi": total_call_oi,
            "total_put_oi": total_put_oi,
            "pcr_oi": pcr,
            "atm_strike": atm_strike,
            "atm_call_price": (
                atm_call["close"]
                if atm_call is not None
                else None
            ),
            "atm_put_price": (
                atm_put["close"]
                if atm_put is not None
                else None
            ),
            "atm_call_iv": atm_call_iv,
            "atm_put_iv": atm_put_iv,
        }

    # =========================================================
    # BUILD
    # =========================================================

    def build(
        self,
        expiry_date: str,
        futures_symbol: str,
        range_from: str,
        range_to: str,
        resolution: str = "1",
        replace_existing: bool = True,
    ) -> dict:

        start_timestamp, end_timestamp = (
            self._date_timestamp_range(
                range_from,
                range_to,
            )
        )

        # -----------------------------------------------------
        # CORE SERIES
        # -----------------------------------------------------

        spot = self._get_series(
            symbol=self.SPOT_SYMBOL,
            resolution=resolution,
            source=self.SPOT_SOURCE,
            start_timestamp=start_timestamp,
            end_timestamp=end_timestamp,
        )

        vix = self._get_series(
            symbol=self.VIX_SYMBOL,
            resolution=resolution,
            source=self.VIX_SOURCE,
            start_timestamp=start_timestamp,
            end_timestamp=end_timestamp,
        )

        futures = self._get_series(
            symbol=futures_symbol,
            resolution=resolution,
            source=self.FUTURES_SOURCE,
            start_timestamp=start_timestamp,
            end_timestamp=end_timestamp,
        )

        if not spot:

            raise ValueError(
                "No NIFTY spot candles found."
            )

        if not vix:

            raise ValueError(
                "No India VIX candles found."
            )

        if not futures:

            raise ValueError(
                "No futures candles found."
            )

        # -----------------------------------------------------
        # OPTION CHAIN
        # -----------------------------------------------------

        chain = self._get_option_chain(
            expiry_date=expiry_date,
            resolution=resolution,
            start_timestamp=start_timestamp,
            end_timestamp=end_timestamp,
        )

        if not chain:

            raise ValueError(
                "No option-chain candles found "
                f"for expiry {expiry_date}."
            )

        # -----------------------------------------------------
        # OPTION ANALYTICS
        # -----------------------------------------------------

        option_instrument_ids = []

        for series in chain.values():

            for candle in series.values():

                option_instrument_ids.append(
                    int(
                        candle[
                            "instrument_id"
                        ]
                    )
                )

                break

        option_iv_map = (
            self._get_option_iv_map(
                instrument_ids=sorted(
                    set(
                        option_instrument_ids
                    )
                ),
                resolution=resolution,
                start_timestamp=start_timestamp,
                end_timestamp=end_timestamp,
            )
        )

        # -----------------------------------------------------
        # COMMON TIMESTAMPS
        #
        # We only create a market-context row when
        # NIFTY + VIX + futures all have a candle.
        # -----------------------------------------------------

        timestamps = sorted(
            set(spot)
            & set(vix)
            & set(futures)
        )

        if not timestamps:

            raise ValueError(
                "No common timestamps between "
                "NIFTY, VIX and futures."
            )

        rows = []

        previous_futures_oi = None

        previous_vix = None

        previous_call_oi = None

        previous_put_oi = None

        previous_spot = None

        for timestamp in timestamps:

            spot_candle = spot[
                timestamp
            ]

            vix_candle = vix[
                timestamp
            ]

            futures_candle = futures[
                timestamp
            ]

            spot_price = (
                float(
                    spot_candle["close"]
                )
                if spot_candle["close"]
                is not None
                else None
            )

            vix_price = (
                float(
                    vix_candle["close"]
                )
                if vix_candle["close"]
                is not None
                else None
            )

            futures_price = (
                float(
                    futures_candle["close"]
                )
                if futures_candle["close"]
                is not None
                else None
            )

            futures_oi = (
                int(
                    futures_candle[
                        "open_interest"
                    ]
                )
                if futures_candle[
                    "open_interest"
                ] is not None
                else None
            )

            options = self._option_snapshot(
                chain=chain,
                timestamp=timestamp,
                spot_price=spot_price,
                option_iv_map=option_iv_map,
            )

            futures_oi_change = None

            if (
                futures_oi is not None
                and previous_futures_oi
                is not None
            ):

                futures_oi_change = (
                    futures_oi
                    - previous_futures_oi
                )

            vix_change = None

            vix_change_pct = None

            if (
                vix_price is not None
                and previous_vix is not None
            ):

                vix_change = (
                    vix_price
                    - previous_vix
                )

                if previous_vix != 0:

                    vix_change_pct = (
                        vix_change
                        / abs(previous_vix)
                    ) * 100.0

            call_oi = options[
                "total_call_oi"
            ]

            put_oi = options[
                "total_put_oi"
            ]

            call_oi_change = None

            put_oi_change = None

            if (
                call_oi is not None
                and previous_call_oi
                is not None
            ):

                call_oi_change = (
                    call_oi
                    - previous_call_oi
                )

            if (
                put_oi is not None
                and previous_put_oi
                is not None
            ):

                put_oi_change = (
                    put_oi
                    - previous_put_oi
                )

            # -------------------------------------------------
            # Store row
            # -------------------------------------------------

            rows.append(
                {
                    "timestamp": timestamp,
                    "resolution": resolution,
                    "underlying": self.UNDERLYING,
                    "expiry_date": expiry_date,
                    "spot_price": spot_price,
                    "futures_price": futures_price,
                    "futures_oi": futures_oi,
                    "futures_oi_change": (
                        futures_oi_change
                    ),
                    "india_vix": vix_price,
                    "india_vix_change": (
                        vix_change
                    ),
                    "india_vix_change_pct": (
                        vix_change_pct
                    ),
                    "total_call_oi": call_oi,
                    "total_put_oi": put_oi,
                    "call_oi_change": (
                        call_oi_change
                    ),
                    "put_oi_change": (
                        put_oi_change
                    ),
                    "pcr_oi": options[
                        "pcr_oi"
                    ],
                    "pcr_oi_change": None,
                    "atm_strike": options[
                        "atm_strike"
                    ],
                    "atm_call_price": (
                        options[
                            "atm_call_price"
                        ]
                    ),
                    "atm_put_price": (
                        options[
                            "atm_put_price"
                        ]
                    ),
                    "atm_call_iv": (
                        options[
                            "atm_call_iv"
                        ]
                    ),
                    "atm_put_iv": (
                        options[
                            "atm_put_iv"
                        ]
                    ),
                    "net_gex": None,
                    "calculation_version": (
                        "market_context_v1"
                    ),
                }
            )

            if futures_oi is not None:

                previous_futures_oi = (
                    futures_oi
                )

            if vix_price is not None:

                previous_vix = vix_price

            if call_oi is not None:

                previous_call_oi = call_oi

            if put_oi is not None:

                previous_put_oi = put_oi

            if spot_price is not None:

                previous_spot = spot_price

        # -----------------------------------------------------
        # INSERT / REPLACE
        # -----------------------------------------------------

        if replace_existing:

            with self._connect() as connection:

                connection.execute(
                    """
                    DELETE FROM market_context
                    WHERE underlying = ?
                      AND resolution = ?
                      AND expiry_date = ?
                      AND timestamp BETWEEN ?
                      AND ?
                    """,
                    (
                        self.UNDERLYING,
                        resolution,
                        expiry_date,
                        start_timestamp,
                        end_timestamp,
                    )
                )

                connection.commit()

        sql = """
        INSERT OR REPLACE INTO market_context (
            timestamp,
            resolution,
            underlying,
            expiry_date,
            spot_price,
            futures_price,
            futures_oi,
            futures_oi_change,
            india_vix,
            india_vix_change,
            india_vix_change_pct,
            total_call_oi,
            total_put_oi,
            call_oi_change,
            put_oi_change,
            pcr_oi,
            pcr_oi_change,
            atm_strike,
            atm_call_price,
            atm_put_price,
            atm_call_iv,
            atm_put_iv,
            net_gex,
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
        
        )
        """

        database_records = [
            (
                row["timestamp"],
                row["resolution"],
                row["underlying"],
                row["expiry_date"],
                row["spot_price"],
                row["futures_price"],
                row["futures_oi"],
                row["futures_oi_change"],
                row["india_vix"],
                row["india_vix_change"],
                row["india_vix_change_pct"],
                row["total_call_oi"],
                row["total_put_oi"],
                row["call_oi_change"],
                row["put_oi_change"],
                row["pcr_oi"],
                row["pcr_oi_change"],
                row["atm_strike"],
                row["atm_call_price"],
                row["atm_put_price"],
                row["atm_call_iv"],
                row["atm_put_iv"],
                row["net_gex"],
                row["calculation_version"],
            )
            for row in rows
        ]

        with self._connect() as connection:

            connection.executemany(
                sql,
                database_records,
            )

            connection.commit()

        complete_atm_rows = sum(
            1
            for row in rows
            if (
                row["atm_strike"]
                is not None
                and row["atm_call_price"]
                is not None
                and row["atm_put_price"]
                is not None
            )
        )

        pcr_rows = sum(
            1
            for row in rows
            if row["pcr_oi"] is not None
        )

        return {
            "underlying": self.UNDERLYING,
            "expiry_date": expiry_date,
            "futures_symbol": futures_symbol,
            "resolution": resolution,
            "range_from": range_from,
            "range_to": range_to,
            "option_symbols_found": len(
                chain
            ),
            "common_timestamps": len(
                timestamps
            ),
            "market_context_rows_written": len(
                rows
            ),
            "complete_atm_rows": (
                complete_atm_rows
            ),
            "pcr_rows": pcr_rows,
            "option_analytics_rows_found": len(
                option_iv_map
            ),
        }

    # =========================================================
    # SAMPLE
    # =========================================================

    def run_sample(self) -> dict:

        return self.build(
            expiry_date="2024-11-28",
            futures_symbol="NSE:NIFTY24NOVFUT",
            range_from="2024-11-27",
            range_to="2024-11-28",
            resolution="1",
        )

    # =========================================================
    # DATABASE SUMMARY
    # =========================================================

    def summary(
        self,
        start_timestamp: int | None = None,
        end_timestamp: int | None = None,
    ) -> dict:

        query = """
        SELECT
            COUNT(*) AS rows_count,
            MIN(timestamp) AS first_timestamp,
            MAX(timestamp) AS last_timestamp
        FROM market_context
        WHERE underlying = 'NIFTY'
        """

        parameters: list = []

        if start_timestamp is not None:

            query += """
              AND timestamp >= ?
            """

            parameters.append(
                start_timestamp
            )

        if end_timestamp is not None:

            query += """
              AND timestamp <= ?
            """

            parameters.append(
                end_timestamp
            )

        with self._connect() as connection:

            row = connection.execute(
                query,
                parameters,
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
        }


# =============================================================
# CLI
# =============================================================

def main() -> None:

    parser = argparse.ArgumentParser(
        description=(
            "Kunal Quant - Market Context Builder V1"
        )
    )

    parser.add_argument(
        "--sample",
        action="store_true",
        help=(
            "Build the controlled "
            "2024-11-27/28 sample."
        ),
    )

    parser.add_argument(
        "--expiry",
        type=str,
        default=None,
        help="Option expiry YYYY-MM-DD.",
    )

    parser.add_argument(
        "--futures",
        type=str,
        default=None,
        help="Historical futures symbol.",
    )

    parser.add_argument(
        "--from",
        dest="range_from",
        type=str,
        default=None,
        help="Start date YYYY-MM-DD.",
    )

    parser.add_argument(
        "--to",
        dest="range_to",
        type=str,
        default=None,
        help="End date YYYY-MM-DD.",
    )

    args = parser.parse_args()

    print("=" * 75)

    print(
        "KUNAL QUANT - MARKET CONTEXT V1"
    )

    print("=" * 75)

    builder = MarketContextBuilder()

    if args.sample:

        result = builder.run_sample()

    else:

        if not args.expiry:

            raise SystemExit(
                "--expiry is required."
            )

        if not args.futures:

            raise SystemExit(
                "--futures is required."
            )

        if not args.range_from:

            raise SystemExit(
                "--from is required."
            )

        if not args.range_to:

            raise SystemExit(
                "--to is required."
            )

        result = builder.build(
            expiry_date=args.expiry,
            futures_symbol=args.futures,
            range_from=args.range_from,
            range_to=args.range_to,
            resolution="1",
        )

    print(
        "\n" + "=" * 75
    )

    print(
        "MARKET CONTEXT RESULT"
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
        "\n" + "=" * 75
    )

    print(
        "MARKET CONTEXT COMPLETE"
    )

    print(
        "=" * 75
    )


if __name__ == "__main__":

    main()