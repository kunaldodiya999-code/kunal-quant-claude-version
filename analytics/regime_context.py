
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

from config.settings import DATABASE_PATH

from analytics.option_analytics import (
    OptionAnalyticsEngine,
)

from analytics.gex_profile import (
    GEXProfileEngine,
)


class MarketRegimeContext:
    """
    Kunal Quant - Market Regime Context V1.1.

    Combines existing market analytics into one synchronized,
    quality-aware descriptive market state.

    Sources:

        NIFTY spot
        NIFTY futures
        Futures-spot basis
        India VIX
        Option OI / PCR
        ATM option data
        GEX profile

    V1.1 adds:

        Option Chain Quality Guard

    IMPORTANT:

        This is NOT a trading signal engine.

        It does not recommend trades.

        It identifies whether the underlying data is sufficiently
        complete for downstream analytical use.

    No database writes are performed.
    """

    UNDERLYING = "NIFTY"
    RESOLUTION = "1"

    MARKET_CONTEXT_VERSION = "market_context_v1"

    GEX_CONVENTION = (
        "CALL_POSITIVE_PUT_NEGATIVE"
    )

    GEX_VERSION = "gex_v1_black76_ltp"

    # =========================================================
    # QUALITY THRESHOLDS
    # =========================================================

    # Maximum acceptable distance between the nearest observed
    # CE+PE pair and spot for the observed ATM to be considered
    # usable.
    ATM_MAX_DISTANCE_PCT = 1.0

    # Number of strikes around the expected ATM used to judge
    # whether PCR/OI information is sufficiently populated.
    PCR_ATM_WINDOW_RADIUS = 5

    # Minimum paired CE+PE coverage inside the ATM window.
    PCR_MIN_PAIRED_COVERAGE_PCT = 70.0

    # Minimum overall option-chain coverage required before
    # the full-chain PCR is considered usable.
    PCR_MIN_CHAIN_COVERAGE_PCT = 90.0

    # Minimum entire-expiry strike coverage required before
    # GEX can be treated as full-chain GEX.
    GEX_MIN_FULL_CHAIN_COVERAGE_PCT = 90.0

    # Number of strikes on each side of ATM used for local
    # GEX completeness.
    GEX_ATM_WINDOW_RADIUS = 2

    # Minimum paired CE+PE coverage inside the local GEX
    # window.
    GEX_MIN_ATM_PAIR_COVERAGE_PCT = 70.0

    # Minimum valid-IV contract coverage required before
    # the IV surface is considered usable as a full-expiry
    # analytical surface.
    IV_SURFACE_MIN_COVERAGE_PCT = 90.0

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

        self.gex_profile_engine = (
            GEXProfileEngine(
                database_path=self.database_path,
            )
        )

    def _connect(self) -> sqlite3.Connection:

        connection = sqlite3.connect(
            self.database_path
        )

        connection.row_factory = sqlite3.Row

        return connection

    # =========================================================
    # HELPERS
    # =========================================================

    @staticmethod
    def _direction(
        current: float | int | None,
        previous: float | int | None,
    ) -> str:

        if current is None or previous is None:
            return "UNAVAILABLE"

        if current > previous:
            return "RISING"

        if current < previous:
            return "FALLING"

        return "FLAT"

    @staticmethod
    def _safe_pct(
        numerator: float | None,
        denominator: float | None,
    ) -> float | None:

        if numerator is None or denominator in (
            None,
            0,
        ):
            return None

        return (
            float(numerator)
            / abs(float(denominator))
        ) * 100.0

    # =========================================================
    # MARKET STATE SUMMARY
    # =========================================================

    @staticmethod
    def _build_market_state_summary(
        spot_direction: str,
        basis: float | None,
        vix_direction: str,
        option_chain_status: str,
        atm_data_usable: bool,
        pcr_oi_usable: bool,
        iv_surface_usable: bool,
        gex_full_chain_usable: bool,
        gex_atm_window_usable: bool,
        market_context_available: bool,
        gex_available: bool,
        timestamps_aligned: bool,
    ) -> dict:
        """
        Build a descriptive market-data state summary.

        This function does NOT generate a trading signal.
        """

        if basis is None:
            basis_state = "UNAVAILABLE"

        elif basis > 0:
            basis_state = "PREMIUM"

        elif basis < 0:
            basis_state = "DISCOUNT"

        else:
            basis_state = "FLAT"

        if not market_context_available:
            overall_status = "UNAVAILABLE"

        elif (
            market_context_available
            and gex_available
            and option_chain_status == "COMPLETE"
            and pcr_oi_usable
            and iv_surface_usable
            and gex_full_chain_usable
            and timestamps_aligned
        ):
            overall_status = "COMPLETE"

        else:
            overall_status = "PARTIAL"

        return {
            "overall_data_status": overall_status,

            "price_direction": spot_direction,

            "futures_basis_state": basis_state,

            "india_vix_direction": vix_direction,

            "option_chain_status": (
                option_chain_status
            ),

            "atm_data_status": (
                "USABLE"
                if atm_data_usable
                else "NOT_USABLE"
            ),

            "pcr_status": (
                "USABLE"
                if pcr_oi_usable
                else "NOT_USABLE"
            ),

            "iv_surface_status": (
                "USABLE"
                if iv_surface_usable
                else "NOT_USABLE"
            ),

            "gex_full_chain_status": (
                "USABLE"
                if gex_full_chain_usable
                else "NOT_USABLE"
            ),

            "gex_atm_window_status": (
                "USABLE"
                if gex_atm_window_usable
                else "NOT_USABLE"
            ),

            "market_context_available": (
                market_context_available
            ),

            "gex_available": (
                gex_available
            ),

            "timestamps_aligned": (
                timestamps_aligned
            ),
        }

    # =========================================================
    # MARKET CONTEXT ROWS
    # =========================================================

    def _get_market_context_rows(
        self,
        expiry_date: str,
        limit: int = 2,
    ) -> list[dict]:

        query = """
        SELECT
            timestamp,
            resolution,
            underlying,

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

            calculation_version

        FROM market_context

        WHERE underlying = ?
          AND resolution = ?
          AND expiry_date = ?
          AND calculation_version = ?

        ORDER BY timestamp DESC

        LIMIT ?
        """

        with self._connect() as connection:

            rows = connection.execute(
                query,
                (
                    self.UNDERLYING,
                    self.RESOLUTION,
                    expiry_date,
                    self.MARKET_CONTEXT_VERSION,
                    max(1, int(limit)),
                ),
            ).fetchall()

        return [
            dict(row)
            for row in rows
        ]

    # =========================================================
    # EXPECTED OPTION UNIVERSE
    # =========================================================

    def _get_expected_option_universe(
        self,
        expiry_date: str,
    ) -> list[dict]:

        query = """
        SELECT
            id,
            symbol,
            strike,
            option_type

        FROM instruments

        WHERE broker = 'FYERS'
          AND underlying = ?
          AND expiry_date = ?
          AND option_type IN ('CE', 'PE')
        """

        with self._connect() as connection:

            rows = connection.execute(
                query,
                (
                    self.UNDERLYING,
                    expiry_date,
                ),
            ).fetchall()

        return [
            dict(row)
            for row in rows
        ]

    # =========================================================
    # EXPECTED STRIKE UNIVERSE
    # =========================================================

    def _get_expected_strikes(
        self,
        expiry_date: str,
    ) -> list[float]:

        query = """
        SELECT DISTINCT strike
        FROM instruments
        WHERE broker = 'FYERS'
          AND underlying = ?
          AND expiry_date = ?
          AND option_type IN ('CE', 'PE')
          AND strike IS NOT NULL
        ORDER BY strike
        """

        with self._connect() as connection:

            rows = connection.execute(
                query,
                (
                    self.UNDERLYING,
                    expiry_date,
                ),
            ).fetchall()

        return sorted(
            {
                float(row["strike"])
                for row in rows
                if row["strike"] is not None
            }
        )

    # =========================================================
    # IV SURFACE / SKEW
    # =========================================================

    def _build_iv_surface_context(
        self,
        expiry_date: str,
        timestamp: int,
    ) -> dict:

        engine = OptionAnalyticsEngine(
            database_path=self.database_path,
        )

        surface = (
            engine.build_iv_surface_snapshot(
                expiry_date=expiry_date,
                timestamp=timestamp,
            )
        )

        surface_timestamp = surface.get(
            "timestamp"
        )

        timestamp_aligned = (
            surface.get("available", False)
            and surface_timestamp is not None
            and int(surface_timestamp)
            == int(timestamp)
        )

        coverage_pct = (
            float(
                surface.get(
                    "valid_iv_coverage_pct",
                    0.0,
                )
            )
        )

        atm_pair_usable = bool(
            surface.get(
                "atm_pair_usable",
                False,
            )
        )

        iv_surface_usable = (
            surface.get("available", False)
            and timestamp_aligned
            and coverage_pct
            >= self.IV_SURFACE_MIN_COVERAGE_PCT
            and atm_pair_usable
        )

        surface_status = str(
            surface.get(
                "status",
                "UNAVAILABLE",
            )
        )

        return {
            "available": bool(
                surface.get(
                    "available",
                    False,
                )
            ),

            "status": surface_status,

            "usable": iv_surface_usable,

            "timestamp": (
                surface_timestamp
            ),

            "timestamp_aligned": (
                timestamp_aligned
            ),

            "version": (
                surface.get(
                    "version"
                )
            ),

            "expiry_date": (
                surface.get(
                    "expiry_date"
                )
            ),

            "expected_contracts": (
                surface.get(
                    "expected_contracts",
                    0,
                )
            ),

            "valid_iv_contracts": (
                surface.get(
                    "valid_iv_contracts",
                    0,
                )
            ),

            "valid_iv_coverage_pct": (
                coverage_pct
            ),

            "coverage_threshold_pct": (
                self.IV_SURFACE_MIN_COVERAGE_PCT
            ),

            "forward_price": (
                surface.get(
                    "forward_price"
                )
            ),

            "spot_price": (
                surface.get(
                    "spot_price"
                )
            ),

            "spot_atm_strike": (
                surface.get(
                    "spot_atm_strike"
                )
            ),

            "forward_atm_strike": (
                surface.get(
                    "forward_atm_strike"
                )
            ),

            "atm_strike": (
                surface.get(
                    "atm_strike"
                )
            ),

            "atm_reference": (
                surface.get(
                    "atm_reference"
                )
            ),

            "atm_call_iv": (
                surface.get(
                    "atm_call_iv"
                )
            ),

            "atm_put_iv": (
                surface.get(
                    "atm_put_iv"
                )
            ),

            "atm_iv": (
                surface.get(
                    "atm_iv"
                )
            ),

            "atm_pair_usable": (
                atm_pair_usable
            ),

            "delta_target": (
                surface.get(
                    "delta_target"
                )
            ),

            "call_25d_iv": (
                surface.get(
                    "call_25d_iv"
                )
            ),

            "put_25d_iv": (
                surface.get(
                    "put_25d_iv"
                )
            ),

            "call_25d_delta": (
                surface.get(
                    "call_25d_delta"
                )
            ),

            "put_25d_delta": (
                surface.get(
                    "put_25d_delta"
                )
            ),

            "call_25d_strike": (
                surface.get(
                    "call_25d_strike"
                )
            ),

            "put_25d_strike": (
                surface.get(
                    "put_25d_strike"
                )
            ),

            "call_25d_status": (
                surface.get(
                    "call_25d_status"
                )
            ),

            "put_25d_status": (
                surface.get(
                    "put_25d_status"
                )
            ),

            "call_skew_vs_atm": (
                surface.get(
                    "call_skew_vs_atm"
                )
            ),

            "put_skew_vs_atm": (
                surface.get(
                    "put_skew_vs_atm"
                )
            ),

            "put_call_iv_skew": (
                surface.get(
                    "put_call_iv_skew"
                )
            ),

            "iv_min": (
                surface.get(
                    "iv_min"
                )
            ),

            "iv_max": (
                surface.get(
                    "iv_max"
                )
            ),

            "iv_median": (
                surface.get(
                    "iv_median"
                )
            ),

            "surface_expected_strikes": (
                surface.get(
                    "surface_expected_strikes",
                    0,
                )
            ),

            "surface_observed_strikes": (
                surface.get(
                    "surface_observed_strikes",
                    0,
                )
            ),

            "surface_presence_pct": (
                surface.get(
                    "surface_presence_pct",
                    0.0,
                )
            ),

            "surface_complete_pairs": (
                surface.get(
                    "surface_complete_pairs",
                    0,
                )
            ),

            "surface_pair_coverage_pct": (
                surface.get(
                    "surface_pair_coverage_pct",
                    0.0,
                )
            ),

            "surface": (
                surface.get(
                    "surface",
                    [],
                )
            ),
        }

    # =========================================================
    # GEX QUALITY GUARD
    # =========================================================

    def _build_gex_quality(
        self,
        expiry_date: str,
        timestamp: int,
        spot_price: float | None,
        gex_rows: list[dict],
    ) -> dict:

        expected_strikes = (
            self._get_expected_strikes(
                expiry_date
            )
        )

        expected_count = len(
            expected_strikes
        )

        gex_strikes = sorted(
            {
                float(row["strike"])
                for row in gex_rows
                if row["strike"] is not None
            }
        )

        gex_strike_count = len(
            gex_strikes
        )

        full_chain_coverage_pct = (
            gex_strike_count
            / expected_count
            * 100.0
            if expected_count
            else 0.0
        )

        complete_pair_count = sum(
            1
            for row in gex_rows
            if (
                row["call_gamma"] is not None
                and row["put_gamma"] is not None
            )
        )

        pair_coverage_pct = (
            complete_pair_count
            / gex_strike_count
            * 100.0
            if gex_strike_count
            else 0.0
        )

        expected_atm_strike = None

        expected_atm_index = None

        if (
            spot_price is not None
            and expected_strikes
        ):

            expected_atm_index = min(
                range(
                    len(expected_strikes)
                ),
                key=lambda index: abs(
                    expected_strikes[index]
                    - spot_price
                ),
            )

            expected_atm_strike = (
                expected_strikes[
                    expected_atm_index
                ]
            )

        gex_atm_strike = None

        gex_atm_distance_points = None

        gex_atm_distance_pct = None

        if (
            spot_price is not None
            and gex_strikes
        ):

            gex_atm_strike = min(
                gex_strikes,
                key=lambda strike: abs(
                    strike
                    - spot_price
                ),
            )

            gex_atm_distance_points = (
                spot_price
                - gex_atm_strike
            )

            gex_atm_distance_pct = (
                abs(
                    gex_atm_distance_points
                )
                / abs(spot_price)
                * 100.0
                if spot_price != 0
                else None
            )

        # =====================================================
        # ATM GEX WINDOW
        # =====================================================

        expected_window = []

        gex_window = []

        if expected_atm_index is not None:

            start_index = max(
                0,
                expected_atm_index
                - self.GEX_ATM_WINDOW_RADIUS,
            )

            end_index = min(
                len(expected_strikes),
                expected_atm_index
                + self.GEX_ATM_WINDOW_RADIUS
                + 1,
            )

            expected_window = (
                expected_strikes[
                    start_index:end_index
                ]
            )

        gex_by_strike = {
            float(row["strike"]): row
            for row in gex_rows
        }

        for strike in expected_window:

            row = gex_by_strike.get(
                strike
            )

            if row is not None:

                gex_window.append(row)

        window_present_count = len(
            gex_window
        )

        window_complete_pair_count = sum(
            1
            for row in gex_window
            if (
                row["call_gamma"] is not None
                and row["put_gamma"] is not None
            )
        )

        window_presence_pct = (
            window_present_count
            / len(expected_window)
            * 100.0
            if expected_window
            else 0.0
        )

        window_pair_coverage_pct = (
            window_complete_pair_count
            / len(expected_window)
            * 100.0
            if expected_window
            else 0.0
        )

        full_chain_usable = (
            full_chain_coverage_pct
            >= self.GEX_MIN_FULL_CHAIN_COVERAGE_PCT
            and pair_coverage_pct
            >= self.GEX_MIN_FULL_CHAIN_COVERAGE_PCT
        )

        atm_window_usable = (
            window_presence_pct >= 100.0
            and window_pair_coverage_pct
            >= self.GEX_MIN_ATM_PAIR_COVERAGE_PCT
        )

        if expected_count == 0:

            status = "UNAVAILABLE"

        elif gex_strike_count == 0:

            status = "EMPTY"

        elif full_chain_usable:

            status = "COMPLETE"

        else:

            status = "PARTIAL"

        return {
            "expiry_date": expiry_date,
            "timestamp": timestamp,

            "status": status,

            "expected_strikes": (
                expected_count
            ),

            "gex_strikes": (
                gex_strike_count
            ),

            "full_chain_coverage_pct": (
                full_chain_coverage_pct
            ),

            "complete_ce_pe_gex_strikes": (
                complete_pair_count
            ),

            "gex_pair_coverage_pct": (
                pair_coverage_pct
            ),

            "expected_atm_strike": (
                expected_atm_strike
            ),

            "gex_atm_strike": (
                gex_atm_strike
            ),

            "gex_atm_distance_points": (
                gex_atm_distance_points
            ),

            "gex_atm_distance_pct": (
                gex_atm_distance_pct
            ),

            "atm_window_radius": (
                self.GEX_ATM_WINDOW_RADIUS
            ),

            "atm_window_expected_strikes": (
                len(expected_window)
            ),

            "atm_window_present_strikes": (
                window_present_count
            ),

            "atm_window_presence_pct": (
                window_presence_pct
            ),

            "atm_window_complete_pairs": (
                window_complete_pair_count
            ),

            "atm_window_pair_coverage_pct": (
                window_pair_coverage_pct
            ),

            "gex_min_full_chain_coverage_pct": (
                self.GEX_MIN_FULL_CHAIN_COVERAGE_PCT
            ),

            "gex_min_atm_pair_coverage_pct": (
                self.GEX_MIN_ATM_PAIR_COVERAGE_PCT
            ),

            "full_chain_usable": (
                full_chain_usable
            ),

            "atm_window_usable": (
                atm_window_usable
            ),
        }

    # =========================================================
    # OBSERVED OPTION SNAPSHOT
    # =========================================================

    def _get_observed_option_snapshot(
        self,
        expiry_date: str,
        timestamp: int,
    ) -> list[dict]:

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
          AND c.source = 'FYERS_FNO_HISTORY'
          AND c.timestamp = ?

        ORDER BY
            i.strike,
            i.option_type
        """

        with self._connect() as connection:

            rows = connection.execute(
                query,
                (
                    self.UNDERLYING,
                    expiry_date,
                    self.RESOLUTION,
                    timestamp,
                ),
            ).fetchall()

        return [
            dict(row)
            for row in rows
        ]

    # =========================================================
    # OPTION CHAIN QUALITY GUARD
    # =========================================================

    def _build_option_chain_quality(
        self,
        expiry_date: str,
        timestamp: int,
        spot_price: float | None,
    ) -> dict:

        expected = (
            self._get_expected_option_universe(
                expiry_date
            )
        )

        observed = (
            self._get_observed_option_snapshot(
                expiry_date=expiry_date,
                timestamp=timestamp,
            )
        )

        expected_count = len(expected)

        observed_symbols = {
            str(row["symbol"])
            for row in observed
        }

        observed_count = len(
            observed_symbols
        )

        coverage_pct = (
            observed_count
            / expected_count
            * 100.0
            if expected_count
            else 0.0
        )

        expected_ce = sum(
            1
            for row in expected
            if row["option_type"] == "CE"
        )

        expected_pe = sum(
            1
            for row in expected
            if row["option_type"] == "PE"
        )

        observed_ce = sum(
            1
            for symbol in observed_symbols
            if next(
                (
                    row["option_type"]
                    for row in observed
                    if row["symbol"] == symbol
                ),
                None,
            )
            == "CE"
        )

        observed_pe = sum(
            1
            for symbol in observed_symbols
            if next(
                (
                    row["option_type"]
                    for row in observed
                    if row["symbol"] == symbol
                ),
                None,
            )
            == "PE"
        )

        expected_strikes = sorted(
            {
                float(row["strike"])
                for row in expected
                if row["strike"] is not None
            }
        )

        observed_strikes = sorted(
            {
                float(row["strike"])
                for row in observed
                if row["strike"] is not None
            }
        )

        paired_observed = {}

        for row in observed:

            strike = row["strike"]

            option_type = row[
                "option_type"
            ]

            if strike is None:
                continue

            strike = float(strike)

            if strike not in paired_observed:

                paired_observed[strike] = {
                    "CE": None,
                    "PE": None,
                }

            paired_observed[strike][
                option_type
            ] = row

        paired_strikes = sorted(
            [
                strike
                for strike, pair
                in paired_observed.items()
                if (
                    pair["CE"] is not None
                    and pair["PE"] is not None
                )
            ]
        )

        # =====================================================
        # EXPECTED ATM
        # =====================================================

        expected_atm_strike = None

        expected_atm_index = None

        if (
            spot_price is not None
            and expected_strikes
        ):

            expected_atm_index = min(
                range(
                    len(
                        expected_strikes
                    )
                ),
                key=lambda index: abs(
                    expected_strikes[index]
                    - spot_price
                ),
            )

            expected_atm_strike = (
                expected_strikes[
                    expected_atm_index
                ]
            )

        # =====================================================
        # OBSERVED ATM
        # =====================================================

        observed_atm_strike = None

        observed_atm_distance_points = None

        observed_atm_distance_pct = None

        observed_atm_call_price = None

        observed_atm_put_price = None

        if (
            spot_price is not None
            and paired_strikes
        ):

            observed_atm_strike = min(
                paired_strikes,
                key=lambda strike: abs(
                    strike
                    - spot_price
                ),
            )

            observed_atm_distance_points = (
                spot_price
                - observed_atm_strike
            )

            observed_atm_distance_pct = (
                abs(
                    observed_atm_distance_points
                )
                / abs(spot_price)
                * 100.0
                if spot_price != 0
                else None
            )

            atm_pair = paired_observed[
                observed_atm_strike
            ]

            if atm_pair["CE"] is not None:

                observed_atm_call_price = (
                    atm_pair["CE"]["close"]
                )

            if atm_pair["PE"] is not None:

                observed_atm_put_price = (
                    atm_pair["PE"]["close"]
                )

        spot_inside_observed_range = False

        if (
            spot_price is not None
            and observed_strikes
        ):

            spot_inside_observed_range = (
                min(observed_strikes)
                <= spot_price
                <= max(observed_strikes)
            )

        atm_usable = (
            observed_atm_strike is not None
            and observed_atm_distance_pct
            is not None
            and observed_atm_distance_pct
            <= self.ATM_MAX_DISTANCE_PCT
        )

        # =====================================================
        # PCR / ATM WINDOW QUALITY
        # =====================================================

        expected_atm_window = []

        pcr_window_pair_count = 0

        pcr_window_oi_pair_count = 0

        if expected_atm_index is not None:

            start_index = max(
                0,
                expected_atm_index
                - self.PCR_ATM_WINDOW_RADIUS,
            )

            end_index = min(
                len(expected_strikes),
                expected_atm_index
                + self.PCR_ATM_WINDOW_RADIUS
                + 1,
            )

            expected_atm_window = (
                expected_strikes[
                    start_index:end_index
                ]
            )

            for strike in expected_atm_window:

                pair = paired_observed.get(
                    strike
                )

                if pair is None:
                    continue

                if (
                    pair["CE"] is not None
                    and pair["PE"] is not None
                ):

                    pcr_window_pair_count += 1

                    ce_oi = pair["CE"].get(
                        "open_interest"
                    )

                    pe_oi = pair["PE"].get(
                        "open_interest"
                    )

                    if (
                        ce_oi is not None
                        and pe_oi is not None
                    ):

                        pcr_window_oi_pair_count += 1

        pcr_window_pair_coverage_pct = (
            pcr_window_pair_count
            / len(expected_atm_window)
            * 100.0
            if expected_atm_window
            else 0.0
        )

        pcr_window_oi_coverage_pct = (
            pcr_window_oi_pair_count
            / len(expected_atm_window)
            * 100.0
            if expected_atm_window
            else 0.0
        )

        pcr_oi_usable = (
            coverage_pct
            >= self.PCR_MIN_CHAIN_COVERAGE_PCT
            and pcr_window_oi_coverage_pct
            >= self.PCR_MIN_PAIRED_COVERAGE_PCT
            and pcr_window_oi_coverage_pct
            == pcr_window_oi_coverage_pct
        )

        if (
            expected_count == 0
        ):

            status = "UNAVAILABLE"

        elif observed_count == 0:

            status = "EMPTY"

        elif observed_count < expected_count:

            status = "PARTIAL"

        else:

            status = "COMPLETE"

        return {
            "expiry_date": expiry_date,
            "timestamp": timestamp,

            "status": status,

            "expected_contracts": (
                expected_count
            ),

            "observed_contracts": (
                observed_count
            ),

            "coverage_pct": coverage_pct,

            "expected_ce_contracts": (
                expected_ce
            ),

            "expected_pe_contracts": (
                expected_pe
            ),

            "observed_ce_contracts": (
                observed_ce
            ),

            "observed_pe_contracts": (
                observed_pe
            ),

            "expected_strikes": (
                len(expected_strikes)
            ),

            "observed_strikes": (
                len(observed_strikes)
            ),

            "paired_observed_strikes": (
                len(paired_strikes)
            ),

            "expected_min_strike": (
                min(expected_strikes)
                if expected_strikes
                else None
            ),

            "expected_max_strike": (
                max(expected_strikes)
                if expected_strikes
                else None
            ),

            "observed_min_strike": (
                min(observed_strikes)
                if observed_strikes
                else None
            ),

            "observed_max_strike": (
                max(observed_strikes)
                if observed_strikes
                else None
            ),

            "spot_price": spot_price,

            "spot_inside_observed_range": (
                spot_inside_observed_range
            ),

            "expected_atm_strike": (
                expected_atm_strike
            ),

            "observed_atm_strike": (
                observed_atm_strike
            ),

            "observed_atm_distance_points": (
                observed_atm_distance_points
            ),

            "observed_atm_distance_pct": (
                observed_atm_distance_pct
            ),

            "observed_atm_call_price": (
                observed_atm_call_price
            ),

            "observed_atm_put_price": (
                observed_atm_put_price
            ),

            "atm_max_distance_pct": (
                self.ATM_MAX_DISTANCE_PCT
            ),

            "atm_usable": atm_usable,

            "pcr_window_radius": (
                self.PCR_ATM_WINDOW_RADIUS
            ),

            "pcr_window_expected_strikes": (
                len(expected_atm_window)
            ),

            "pcr_window_pair_count": (
                pcr_window_pair_count
            ),

            "pcr_window_oi_pair_count": (
                pcr_window_oi_pair_count
            ),

            "pcr_window_pair_coverage_pct": (
                pcr_window_pair_coverage_pct
            ),

            "pcr_window_oi_coverage_pct": (
                pcr_window_oi_coverage_pct
            ),

            "pcr_min_paired_coverage_pct": (
                self.PCR_MIN_PAIRED_COVERAGE_PCT
            ),

            "pcr_min_chain_coverage_pct": (
                self.PCR_MIN_CHAIN_COVERAGE_PCT
            ),

            "pcr_scope": "FULL_CHAIN",

            "pcr_oi_usable": pcr_oi_usable,
        }

    # =========================================================
    # GEX PROFILE CONTEXT
    # =========================================================

    def _build_gex_profile_context(
        self,
        expiry_date: str,
        timestamp: int,
    ) -> dict:

        try:

            profile_timestamp = (
                self.gex_profile_engine.get_latest_timestamp(
                    expiry_date=expiry_date
                )
            )

            if profile_timestamp is None:

                return {
                    "available": False,
                    "timestamp": None,
                    "timestamp_aligned": False,
                    "expected_timestamp": timestamp,
                    "error": (
                        "No GEX profile timestamp found."
                    ),
                }

            profile = (
                self.gex_profile_engine.build_profile(
                    expiry_date=expiry_date,
                    top_n=10,
                    atm_radius=self.GEX_ATM_WINDOW_RADIUS,
                )
            )

        except (
            ValueError,
            KeyError,
            TypeError,
        ) as error:

            return {
                "available": False,
                "timestamp": None,
                "timestamp_aligned": False,
                "error": str(error),
            }

        timestamp_aligned = (
            int(profile_timestamp)
            == int(timestamp)
        )

        if not timestamp_aligned:

            return {
                "available": False,
                "timestamp": int(profile_timestamp),
                "timestamp_aligned": False,
                "expected_timestamp": int(timestamp),
                "error": (
                    "GEX profile timestamp does not "
                    "match market context timestamp."
                ),
            }

        return {
            "available": True,

            "timestamp": int(
                profile_timestamp
            ),

            "timestamp_aligned": True,

            "spot_price": profile.get(
                "spot_price"
            ),

            "atm_strike": profile.get(
                "atm_strike"
            ),

            "atm_distance_points": profile.get(
                "atm_distance_points"
            ),

            "atm_radius": profile.get(
                "atm_radius"
            ),

            "atm_window_min_strike": profile.get(
                "atm_window_min_strike"
            ),

            "atm_window_max_strike": profile.get(
                "atm_window_max_strike"
            ),

            "atm_window_call_gex": profile.get(
                "atm_window_call_gex"
            ),

            "atm_window_put_gex": profile.get(
                "atm_window_put_gex"
            ),

            "atm_window_gross_gex": profile.get(
                "atm_window_gross_gex"
            ),

            "atm_window_net_gex": profile.get(
                "atm_window_net_gex"
            ),

            "quality_summary": profile.get(
                "quality_summary",
                {},
            ),

            "zero_crossings": profile.get(
                "zero_crossings",
                [],
            ),

            "top_positive_net_gex": profile.get(
                "top_positive_net_gex",
                [],
            ),

            "top_negative_net_gex": profile.get(
                "top_negative_net_gex",
                [],
            ),

            "profile": profile.get(
                "profile",
                [],
            ),

            "summary": profile.get(
                "summary",
                {},
            ),
        }

    # =========================================================
    # GEX DATA
    # =========================================================

    def _get_latest_gex_rows(
        self,
        expiry_date: str,
    ) -> list[dict]:

        with self._connect() as connection:

            latest = connection.execute(
                """
                SELECT MAX(timestamp) AS timestamp
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
                    self.GEX_VERSION,
                ),
            ).fetchone()

            if (
                latest is None
                or latest["timestamp"] is None
            ):
                return []

            timestamp = int(
                latest["timestamp"]
            )

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
                    net_gex

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
                    self.GEX_VERSION,
                    timestamp,
                ),
            ).fetchall()

        return [
            dict(row)
            for row in rows
        ]

    # =========================================================
    # PREVIOUS GEX SNAPSHOT
    # =========================================================

    def _get_previous_gex_rows(
        self,
        expiry_date: str,
        current_timestamp: int,
    ) -> list[dict]:

        with self._connect() as connection:

            current_session = connection.execute(
                """
                SELECT date(
                    ?,
                    'unixepoch',
                    '+5 hours',
                    '+30 minutes'
                ) AS session_date
                """,
                (current_timestamp,),
            ).fetchone()

            if (
                current_session is None
                or current_session["session_date"] is None
            ):
                return []

            session_date = str(
                current_session["session_date"]
            )

            previous = connection.execute(
                """
                SELECT timestamp
                FROM gex_snapshots

                WHERE underlying = ?
                  AND expiry_date = ?
                  AND resolution = ?
                  AND gex_convention = ?
                  AND calculation_version = ?
                  AND timestamp < ?

                  AND date(
                      timestamp,
                      'unixepoch',
                      '+5 hours',
                      '+30 minutes'
                  ) = ?

                ORDER BY timestamp DESC

                LIMIT 1
                """,
                (
                    self.UNDERLYING,
                    expiry_date,
                    self.RESOLUTION,
                    self.GEX_CONVENTION,
                    self.GEX_VERSION,
                    current_timestamp,
                    session_date,
                ),
            ).fetchone()

            if (
                previous is None
                or previous["timestamp"] is None
            ):
                return []

            previous_timestamp = int(
                previous["timestamp"]
            )

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
                    net_gex

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
                    self.GEX_VERSION,
                    previous_timestamp,
                ),
            ).fetchall()

        return [
            dict(row)
            for row in rows
        ]

    # =========================================================
    # GEX TIME EVOLUTION
    # =========================================================

    @staticmethod
    def _build_gex_evolution(
        current: dict,
        previous: dict | None,
    ) -> dict:

        if (
            not current.get("available")
            or previous is None
            or not previous.get("available")
        ):

            return {
                "available": False,
                "current_timestamp": (
                    current.get("timestamp")
                ),
                "previous_timestamp": (
                    previous.get("timestamp")
                    if previous is not None
                    else None
                ),
                "timestamp_gap_seconds": None,
                "net_gex_change": None,
                "net_gex_change_pct": None,
                "gross_gex_change": None,
                "gross_gex_change_pct": None,
                "call_gex_change": None,
                "call_gex_change_pct": None,
                "put_gex_change": None,
                "put_gex_change_pct": None,
                "net_gex_direction": "UNAVAILABLE",
            }

        current_timestamp = int(
            current["timestamp"]
        )

        previous_timestamp = int(
            previous["timestamp"]
        )

        timestamp_gap = (
            current_timestamp
            - previous_timestamp
        )

        current_net = float(
            current["total_net_gex"]
        )

        previous_net = float(
            previous["total_net_gex"]
        )

        current_gross = float(
            current["total_gross_gex"]
        )

        previous_gross = float(
            previous["total_gross_gex"]
        )

        current_call = float(
            current["total_call_gex"]
        )

        previous_call = float(
            previous["total_call_gex"]
        )

        current_put = float(
            current["total_put_gex"]
        )

        previous_put = float(
            previous["total_put_gex"]
        )

        net_change = (
            current_net
            - previous_net
        )

        gross_change = (
            current_gross
            - previous_gross
        )

        call_change = (
            current_call
            - previous_call
        )

        put_change = (
            current_put
            - previous_put
        )

        def pct_change(
            current_value: float,
            previous_value: float,
        ) -> float | None:

            if previous_value == 0:
                return None

            return (
                (
                    current_value
                    - previous_value
                )
                / abs(previous_value)
            ) * 100.0

        if net_change > 0:
            net_direction = "RISING"
        elif net_change < 0:
            net_direction = "FALLING"
        else:
            net_direction = "FLAT"

        return {
            "available": True,

            "current_timestamp": (
                current_timestamp
            ),

            "previous_timestamp": (
                previous_timestamp
            ),

            "timestamp_gap_seconds": (
                timestamp_gap
            ),

            "net_gex_change": (
                net_change
            ),

            "net_gex_change_pct": (
                pct_change(
                    current_net,
                    previous_net,
                )
            ),

            "gross_gex_change": (
                gross_change
            ),

            "gross_gex_change_pct": (
                pct_change(
                    current_gross,
                    previous_gross,
                )
            ),

            "call_gex_change": (
                call_change
            ),

            "call_gex_change_pct": (
                pct_change(
                    current_call,
                    previous_call,
                )
            ),

            "put_gex_change": (
                put_change
            ),

            "put_gex_change_pct": (
                pct_change(
                    current_put,
                    previous_put,
                )
            ),

            "current_net_gex": current_net,

            "previous_net_gex": previous_net,

            "current_gross_gex": (
                current_gross
            ),

            "previous_gross_gex": (
                previous_gross
            ),

            "net_gex_direction": (
                net_direction
            ),
        }

    # =========================================================
    # GEX SUMMARY
    # =========================================================

    def _build_gex_summary(
        self,
        rows: list[dict],
    ) -> dict:

        if not rows:

            return {
                "available": False,
                "timestamp": None,
                "strike_count": 0,
                "complete_ce_pe_strikes": 0,
                "partial_strikes": 0,
                "spot_price": None,
                "atm_strike": None,
                "total_call_gex": 0.0,
                "total_put_gex": 0.0,
                "total_gross_gex": 0.0,
                "total_net_gex": 0.0,
                "gex_dominance_pct": None,
                "net_gex_state": "UNAVAILABLE",
                "highest_positive_strike": None,
                "highest_positive_net_gex": None,
                "most_negative_strike": None,
                "most_negative_net_gex": None,
            }

        timestamp = int(
            rows[0]["timestamp"]
        )

        spot_price = (
            float(rows[0]["spot_price"])
            if rows[0]["spot_price"] is not None
            else None
        )

        total_call_gex = sum(
            float(row["call_gex"] or 0.0)
            for row in rows
        )

        total_put_gex = sum(
            float(row["put_gex"] or 0.0)
            for row in rows
        )

        total_gross_gex = sum(
            float(row["gross_gex"] or 0.0)
            for row in rows
        )

        total_net_gex = sum(
            float(row["net_gex"] or 0.0)
            for row in rows
        )

        complete_ce_pe = sum(
            1
            for row in rows
            if (
                row["call_gamma"] is not None
                and row["put_gamma"] is not None
            )
        )

        partial_strikes = (
            len(rows)
            - complete_ce_pe
        )

        atm_strike = None

        if spot_price is not None:

            atm_strike = float(
                min(
                    rows,
                    key=lambda row: abs(
                        float(row["strike"])
                        - spot_price
                    ),
                )["strike"]
            )

        positive_rows = [
            row
            for row in rows
            if float(row["net_gex"] or 0.0) > 0
        ]

        negative_rows = [
            row
            for row in rows
            if float(row["net_gex"] or 0.0) < 0
        ]

        highest_positive = (
            max(
                positive_rows,
                key=lambda row: float(
                    row["net_gex"]
                ),
            )
            if positive_rows
            else None
        )

        most_negative = (
            min(
                negative_rows,
                key=lambda row: float(
                    row["net_gex"]
                ),
            )
            if negative_rows
            else None
        )

        if total_net_gex > 0:

            net_state = "POSITIVE_NET_GEX"

        elif total_net_gex < 0:

            net_state = "NEGATIVE_NET_GEX"

        else:

            net_state = "ZERO_NET_GEX"

        dominance_pct = None

        if total_gross_gex > 0:

            dominance_pct = (
                abs(total_net_gex)
                / total_gross_gex
            ) * 100.0

        return {
            "available": True,
            "timestamp": timestamp,
            "strike_count": len(rows),
            "complete_ce_pe_strikes": (
                complete_ce_pe
            ),
            "partial_strikes": (
                partial_strikes
            ),
            "gex_pair_coverage_pct": (
                complete_ce_pe
                / len(rows)
                * 100.0
                if rows
                else 0.0
            ),
            "spot_price": spot_price,
            "atm_strike": atm_strike,
            "total_call_gex": total_call_gex,
            "total_put_gex": total_put_gex,
            "total_gross_gex": total_gross_gex,
            "total_net_gex": total_net_gex,
            "gex_dominance_pct": dominance_pct,
            "net_gex_state": net_state,
            "highest_positive_strike": (
                float(
                    highest_positive["strike"]
                )
                if highest_positive
                else None
            ),
            "highest_positive_net_gex": (
                float(
                    highest_positive["net_gex"]
                )
                if highest_positive
                else None
            ),
            "most_negative_strike": (
                float(
                    most_negative["strike"]
                )
                if most_negative
                else None
            ),
            "most_negative_net_gex": (
                float(
                    most_negative["net_gex"]
                )
                if most_negative
                else None
            ),
        }

    # =========================================================
    # OPTIONS INTELLIGENCE AGGREGATION
    # =========================================================

    @staticmethod
    def _build_options_intelligence(
        expiry_date: str,
        timestamp: int,
        spot: float | None,
        futures: dict,
        india_vix: dict,
        call_oi: int | None,
        put_oi: int | None,
        pcr_oi: float | None,
        option_chain_quality: dict,
        iv_surface: dict,
        gex: dict,
        gex_evolution: dict,
        gex_quality: dict,
        synchronized: bool,
    ) -> dict:
        """
        Consolidate existing option analytics into one
        quality-aware read-only object.

        This layer does not create a trading signal,
        ranking, score, or recommendation.
        """

        component_states = {
            "option_chain": (
                option_chain_quality.get(
                    "status",
                    "UNAVAILABLE",
                )
            ),

            "atm": (
                "USABLE"
                if option_chain_quality.get(
                    "atm_usable",
                    False,
                )
                else "NOT_USABLE"
            ),

            "pcr": (
                "USABLE"
                if option_chain_quality.get(
                    "pcr_oi_usable",
                    False,
                )
                else "NOT_USABLE"
            ),

            "iv_surface": (
                "USABLE"
                if iv_surface.get(
                    "usable",
                    False,
                )
                else iv_surface.get(
                    "status",
                    "UNAVAILABLE",
                )
            ),

            "gex": (
                "AVAILABLE"
                if gex.get(
                    "available",
                    False,
                )
                else "UNAVAILABLE"
            ),

            "gex_full_chain": (
                "USABLE"
                if gex_quality.get(
                    "full_chain_usable",
                    False,
                )
                else "NOT_USABLE"
            ),

            "gex_atm_window": (
                "USABLE"
                if gex_quality.get(
                    "atm_window_usable",
                    False,
                )
                else "NOT_USABLE"
            ),

            "gex_evolution": (
                "AVAILABLE"
                if gex_evolution.get(
                    "available",
                    False,
                )
                else "UNAVAILABLE"
            ),
        }

        available_components = sum(
            1
            for state in component_states.values()
            if state in (
                "USABLE",
                "AVAILABLE",
                "COMPLETE",
            )
        )

        total_components = len(
            component_states
        )

        overall_quality = (
            "COMPLETE"
            if (
                synchronized
                and option_chain_quality.get(
                    "status"
                ) == "COMPLETE"
                and option_chain_quality.get(
                    "pcr_oi_usable",
                    False,
                )
                and iv_surface.get(
                    "usable",
                    False,
                )
                and gex_quality.get(
                    "full_chain_usable",
                    False,
                )
            )
            else "PARTIAL"
        )

        return {
            "version": (
                "options_intelligence_v1"
            ),

            "underlying": "NIFTY",

            "expiry_date": expiry_date,

            "timestamp": timestamp,

            "synchronization": {
                "timestamp_aligned": synchronized,
            },

            "market_inputs": {
                "spot_price": spot,

                "futures_price": (
                    futures.get("price")
                ),

                "futures_basis_points": (
                    futures.get("basis_points")
                ),

                "futures_basis_pct": (
                    futures.get("basis_pct")
                ),

                "india_vix": (
                    india_vix.get("value")
                ),

                "india_vix_direction": (
                    india_vix.get("direction")
                ),
            },

            "option_chain": {
                "status": (
                    option_chain_quality.get(
                        "status"
                    )
                ),

                "expected_contracts": (
                    option_chain_quality.get(
                        "expected_contracts"
                    )
                ),

                "observed_contracts": (
                    option_chain_quality.get(
                        "observed_contracts"
                    )
                ),

                "coverage_pct": (
                    option_chain_quality.get(
                        "coverage_pct"
                    )
                ),

                "atm_usable": (
                    option_chain_quality.get(
                        "atm_usable"
                    )
                ),

                "observed_atm_strike": (
                    option_chain_quality.get(
                        "observed_atm_strike"
                    )
                ),

                "observed_atm_distance_pct": (
                    option_chain_quality.get(
                        "observed_atm_distance_pct"
                    )
                ),
            },

            "oi_pcr": {
                "call_oi": (
                    call_oi
                    if option_chain_quality.get(
                        "pcr_oi_usable",
                        False,
                    )
                    else None
                ),

                "put_oi": (
                    put_oi
                    if option_chain_quality.get(
                        "pcr_oi_usable",
                        False,
                    )
                    else None
                ),

                "pcr": (
                    pcr_oi
                    if option_chain_quality.get(
                        "pcr_oi_usable",
                        False,
                    )
                    else None
                ),

                "raw_call_oi": call_oi,

                "raw_put_oi": put_oi,

                "raw_pcr": pcr_oi,

                "usable": (
                    option_chain_quality.get(
                        "pcr_oi_usable"
                    )
                ),

                "scope": (
                    option_chain_quality.get(
                        "pcr_scope"
                    )
                ),
            },

            "atm": {
                "spot_atm_strike": (
                    option_chain_quality.get(
                        "expected_atm_strike"
                    )
                ),

                "observed_atm_strike": (
                    option_chain_quality.get(
                        "observed_atm_strike"
                    )
                ),

                "call_price": (
                    option_chain_quality.get(
                        "observed_atm_call_price"
                    )
                ),

                "put_price": (
                    option_chain_quality.get(
                        "observed_atm_put_price"
                    )
                ),

                "usable": (
                    option_chain_quality.get(
                        "atm_usable"
                    )
                ),
            },

            "iv_surface": {
                "status": (
                    iv_surface.get(
                        "status"
                    )
                ),

                "usable": (
                    iv_surface.get(
                        "usable"
                    )
                ),

                "timestamp_aligned": (
                    iv_surface.get(
                        "timestamp_aligned"
                    )
                ),

                "valid_iv_contracts": (
                    iv_surface.get(
                        "valid_iv_contracts"
                    )
                ),

                "valid_iv_coverage_pct": (
                    iv_surface.get(
                        "valid_iv_coverage_pct"
                    )
                ),

                "spot_atm_strike": (
                    iv_surface.get(
                        "spot_atm_strike"
                    )
                ),

                "forward_atm_strike": (
                    iv_surface.get(
                        "forward_atm_strike"
                    )
                ),

                "atm_iv": (
                    iv_surface.get(
                        "atm_iv"
                    )
                ),

                "atm_call_iv": (
                    iv_surface.get(
                        "atm_call_iv"
                    )
                ),

                "atm_put_iv": (
                    iv_surface.get(
                        "atm_put_iv"
                    )
                ),

                "call_25d_iv": (
                    iv_surface.get(
                        "call_25d_iv"
                    )
                ),

                "put_25d_iv": (
                    iv_surface.get(
                        "put_25d_iv"
                    )
                ),

                "call_25d_status": (
                    iv_surface.get(
                        "call_25d_status"
                    )
                ),

                "put_25d_status": (
                    iv_surface.get(
                        "put_25d_status"
                    )
                ),

                "call_skew_vs_atm": (
                    iv_surface.get(
                        "call_skew_vs_atm"
                    )
                ),

                "put_skew_vs_atm": (
                    iv_surface.get(
                        "put_skew_vs_atm"
                    )
                ),

                "put_call_iv_skew": (
                    iv_surface.get(
                        "put_call_iv_skew"
                    )
                ),

                "iv_min": (
                    iv_surface.get(
                        "iv_min"
                    )
                ),

                "iv_max": (
                    iv_surface.get(
                        "iv_max"
                    )
                ),

                "iv_median": (
                    iv_surface.get(
                        "iv_median"
                    )
                ),

                "surface": (
                    iv_surface.get(
                        "surface",
                        [],
                    )
                ),
            },

            "gex": {
                "available": (
                    gex.get("available")
                ),

                "timestamp": (
                    gex.get("timestamp")
                ),

                "strike_count": (
                    gex.get("strike_count")
                ),

                "complete_ce_pe_strikes": (
                    gex.get(
                        "complete_ce_pe_strikes"
                    )
                ),

                "gex_pair_coverage_pct": (
                    gex.get(
                        "gex_pair_coverage_pct"
                    )
                ),

                "total_call_gex": (
                    gex.get(
                        "total_call_gex"
                    )
                ),

                "total_put_gex": (
                    gex.get(
                        "total_put_gex"
                    )
                ),

                "total_gross_gex": (
                    gex.get(
                        "total_gross_gex"
                    )
                ),

                "total_net_gex": (
                    gex.get(
                        "total_net_gex"
                    )
                ),

                "gex_dominance_pct": (
                    gex.get(
                        "gex_dominance_pct"
                    )
                ),

                "net_gex_state": (
                    gex.get(
                        "net_gex_state"
                    )
                ),

                "highest_positive_strike": (
                    gex.get(
                        "highest_positive_strike"
                    )
                ),

                "highest_positive_net_gex": (
                    gex.get(
                        "highest_positive_net_gex"
                    )
                ),

                "most_negative_strike": (
                    gex.get(
                        "most_negative_strike"
                    )
                ),

                "most_negative_net_gex": (
                    gex.get(
                        "most_negative_net_gex"
                    )
                ),
            },

            "gex_evolution": {
                "available": (
                    gex_evolution.get(
                        "available"
                    )
                ),

                "timestamp_gap_seconds": (
                    gex_evolution.get(
                        "timestamp_gap_seconds"
                    )
                ),

                "net_gex_change": (
                    gex_evolution.get(
                        "net_gex_change"
                    )
                ),

                "net_gex_change_pct": (
                    gex_evolution.get(
                        "net_gex_change_pct"
                    )
                ),

                "gross_gex_change": (
                    gex_evolution.get(
                        "gross_gex_change"
                    )
                ),

                "call_gex_change": (
                    gex_evolution.get(
                        "call_gex_change"
                    )
                ),

                "put_gex_change": (
                    gex_evolution.get(
                        "put_gex_change"
                    )
                ),

                "net_gex_direction": (
                    gex_evolution.get(
                        "net_gex_direction"
                    )
                ),
            },

            "quality": {
                "overall_status": (
                    overall_quality
                ),

                "component_states": (
                    component_states
                ),

                "available_components": (
                    available_components
                ),

                "total_components": (
                    total_components
                ),

                "option_chain_status": (
                    option_chain_quality.get(
                        "status"
                    )
                ),

                "pcr_usable": (
                    option_chain_quality.get(
                        "pcr_oi_usable"
                    )
                ),

                "iv_surface_usable": (
                    iv_surface.get(
                        "usable"
                    )
                ),

                "gex_full_chain_usable": (
                    gex_quality.get(
                        "full_chain_usable"
                    )
                ),

                "gex_atm_window_usable": (
                    gex_quality.get(
                        "atm_window_usable"
                    )
                ),

                "timestamp_aligned": (
                    synchronized
                ),
            },
        }

    # =========================================================
    # =========================================================
    # BUILD
    # =========================================================

    def build(
        self,
        expiry_date: str,
    ) -> dict:

        context_rows = (
            self._get_market_context_rows(
                expiry_date=expiry_date,
                limit=2,
            )
        )

        if not context_rows:

            raise ValueError(
                "No market_context rows found."
            )

        current = context_rows[0]

        previous = (
            context_rows[1]
            if len(context_rows) > 1
            else None
        )

        current_timestamp = int(
            current["timestamp"]
        )

        spot = (
            float(current["spot_price"])
            if current["spot_price"] is not None
            else None
        )

        previous_spot = (
            float(previous["spot_price"])
            if previous is not None
            and previous["spot_price"] is not None
            else None
        )

        futures = (
            float(current["futures_price"])
            if current["futures_price"] is not None
            else None
        )

        basis = None
        basis_pct = None

        if (
            spot is not None
            and futures is not None
        ):

            basis = (
                futures
                - spot
            )

            basis_pct = self._safe_pct(
                basis,
                spot,
            )

        spot_change = None

        if (
            spot is not None
            and previous_spot is not None
        ):

            spot_change = (
                spot
                - previous_spot
            )

        vix = (
            float(current["india_vix"])
            if current["india_vix"] is not None
            else None
        )

        previous_vix = (
            float(previous["india_vix"])
            if previous is not None
            and previous["india_vix"] is not None
            else None
        )

        call_oi_raw = (
            int(current["total_call_oi"])
            if current["total_call_oi"] is not None
            else None
        )

        put_oi_raw = (
            int(current["total_put_oi"])
            if current["total_put_oi"] is not None
            else None
        )

        call_oi_change = (
            int(current["call_oi_change"])
            if current["call_oi_change"] is not None
            else None
        )

        put_oi_change = (
            int(current["put_oi_change"])
            if current["put_oi_change"] is not None
            else None
        )

        pcr_raw = (
            float(current["pcr_oi"])
            if current["pcr_oi"] is not None
            else None
        )

        atm_raw = (
            float(current["atm_strike"])
            if current["atm_strike"] is not None
            else None
        )

        atm_call_price_raw = (
            float(current["atm_call_price"])
            if current["atm_call_price"] is not None
            else None
        )

        atm_put_price_raw = (
            float(current["atm_put_price"])
            if current["atm_put_price"] is not None
            else None
        )

        atm_call_iv = (
            float(current["atm_call_iv"])
            if current["atm_call_iv"] is not None
            else None
        )

        atm_put_iv = (
            float(current["atm_put_iv"])
            if current["atm_put_iv"] is not None
            else None
        )

        # =====================================================
        # OPTION CHAIN QUALITY
        # =====================================================

        option_chain_quality = (
            self._build_option_chain_quality(
                expiry_date=expiry_date,
                timestamp=current_timestamp,
                spot_price=spot,
            )
        )

        atm_usable = option_chain_quality[
            "atm_usable"
        ]

        pcr_usable = option_chain_quality[
            "pcr_oi_usable"
        ]

        iv_surface = (
            self._build_iv_surface_context(
                expiry_date=expiry_date,
                timestamp=current_timestamp,
            )
        )

        iv_surface_usable = iv_surface[
            "usable"
        ]

        # =====================================================
        # GEX
        # =====================================================

        gex_rows = (
            self._get_latest_gex_rows(
                expiry_date
            )
        )

        gex = self._build_gex_summary(
            gex_rows
        )

        gex_quality = (
            self._build_gex_quality(
                expiry_date=expiry_date,
                timestamp=current_timestamp,
                spot_price=spot,
                gex_rows=gex_rows,
            )
        )

        previous_gex_rows = (
            self._get_previous_gex_rows(
                expiry_date=expiry_date,
                current_timestamp=(
                    current_timestamp
                ),
            )
        )

        previous_gex = (
            self._build_gex_summary(
                previous_gex_rows
            )
        )

        gex_evolution = (
            self._build_gex_evolution(
                current=gex,
                previous=previous_gex,
            )
        )

        gex_profile = (
            self._build_gex_profile_context(
                expiry_date=expiry_date,
                timestamp=current_timestamp,
            )
        )

        # =====================================================
        # OPTIONS INTELLIGENCE
        # =====================================================

        options_intelligence = (
            self._build_options_intelligence(
                expiry_date=expiry_date,
                timestamp=current_timestamp,
                spot=spot,
                futures={
                    "price": futures,
                    "basis_points": basis,
                    "basis_pct": basis_pct,
                },
                india_vix={
                    "value": vix,
                    "direction": self._direction(
                        vix,
                        previous_vix,
                    ),
                },
                call_oi=call_oi_raw,
                put_oi=put_oi_raw,
                pcr_oi=pcr_raw,
                option_chain_quality=(
                    option_chain_quality
                ),
                iv_surface=iv_surface,
                gex=gex,
                gex_evolution=gex_evolution,
                gex_quality=gex_quality,
                synchronized=True,
            )
        )

        gex_timestamp = (
            int(gex["timestamp"])
            if gex["timestamp"] is not None
            else None
        )

        timestamps_aligned = (
            gex_timestamp == current_timestamp
            if gex_timestamp is not None
            else False
        )

        # =====================================================
        # MARKET STATE SUMMARY
        # =====================================================

        market_state = (
            self._build_market_state_summary(
                spot_direction=self._direction(
                    spot,
                    previous_spot,
                ),
                basis=basis,
                vix_direction=self._direction(
                    vix,
                    previous_vix,
                ),
                option_chain_status=(
                    option_chain_quality[
                        "status"
                    ]
                ),
                atm_data_usable=atm_usable,
                pcr_oi_usable=pcr_usable,
                iv_surface_usable=(
                    iv_surface_usable
                ),
                gex_full_chain_usable=(
                    gex_quality[
                        "full_chain_usable"
                    ]
                ),
                gex_atm_window_usable=(
                    gex_quality[
                        "atm_window_usable"
                    ]
                ),
                market_context_available=True,
                gex_available=gex[
                    "available"
                ],
                timestamps_aligned=(
                    timestamps_aligned
                ),
            )
        )

        # =====================================================
        # RETURN CONTEXT
        # =====================================================

        return {
            "underlying": self.UNDERLYING,
            "expiry_date": expiry_date,
            "resolution": self.RESOLUTION,

            "timestamp": current_timestamp,

            "market_state": market_state,

            "spot": {
                "price": spot,
                "change": spot_change,
                "direction": self._direction(
                    spot,
                    previous_spot,
                ),
            },

            "futures": {
                "price": futures,
                "open_interest": (
                    current["futures_oi"]
                ),
                "open_interest_change": (
                    current[
                        "futures_oi_change"
                    ]
                ),
                "basis_points": basis,
                "basis_pct": basis_pct,
            },

            "india_vix": {
                "value": vix,
                "change": (
                    current[
                        "india_vix_change"
                    ]
                ),
                "change_pct": (
                    current[
                        "india_vix_change_pct"
                    ]
                ),
                "direction": self._direction(
                    vix,
                    previous_vix,
                ),
            },

            "options": {
                # Raw market_context values are retained
                # for auditing.
                "raw_call_oi": call_oi_raw,
                "raw_put_oi": put_oi_raw,
                "raw_pcr_oi": pcr_raw,
                "raw_atm_strike": atm_raw,
                "raw_atm_call_price": (
                    atm_call_price_raw
                ),
                "raw_atm_put_price": (
                    atm_put_price_raw
                ),

                # Only expose these as usable values when
                # the quality guard approves them.
                "call_oi": (
                    call_oi_raw
                    if pcr_usable
                    else None
                ),
                "put_oi": (
                    put_oi_raw
                    if pcr_usable
                    else None
                ),
                "call_oi_change": (
                    call_oi_change
                    if pcr_usable
                    else None
                ),
                "put_oi_change": (
                    put_oi_change
                    if pcr_usable
                    else None
                ),
                "pcr_oi": (
                    pcr_raw
                    if pcr_usable
                    else None
                ),
                "pcr_oi_change": (
                    current[
                        "pcr_oi_change"
                    ]
                    if pcr_usable
                    else None
                ),

                "atm_strike": (
                    option_chain_quality[
                        "observed_atm_strike"
                    ]
                    if atm_usable
                    else None
                ),
                "atm_call_price": (
                    option_chain_quality[
                        "observed_atm_call_price"
                    ]
                    if atm_usable
                    else None
                ),
                "atm_put_price": (
                    option_chain_quality[
                        "observed_atm_put_price"
                    ]
                    if atm_usable
                    else None
                ),
                "atm_call_iv": (
                    atm_call_iv
                    if (
                        atm_usable
                        and atm_raw
                        == option_chain_quality[
                            "observed_atm_strike"
                        ]
                    )
                    else None
                ),
                "atm_put_iv": (
                    atm_put_iv
                    if (
                        atm_usable
                        and atm_raw
                        == option_chain_quality[
                            "observed_atm_strike"
                        ]
                    )
                    else None
                ),

                "atm_data_usable": atm_usable,
                "pcr_oi_usable": pcr_usable,

                "iv_surface": (
                    iv_surface
                ),
            },

            "option_chain_quality": (
                option_chain_quality
            ),

            "iv_surface": (
                iv_surface
            ),

            "options_intelligence": (
                options_intelligence
            ),

            "gex": gex,

            "gex_profile": (
                gex_profile
            ),

            "gex_evolution": (
                gex_evolution
            ),

            "gex_quality": (
                gex_quality
            ),

            "synchronization": {
                "market_context_timestamp": (
                    current_timestamp
                ),
                "gex_timestamp": gex_timestamp,
                "timestamps_aligned": (
                    timestamps_aligned
                ),
                "gex_strike_count": (
                    gex["strike_count"]
                ),
                "gex_pair_coverage_pct": (
                    gex.get(
                        "gex_pair_coverage_pct"
                    )
                ),
            },

            "data_quality": {
                "market_context_available": True,
                "option_chain_status": (
                    option_chain_quality[
                        "status"
                    ]
                ),
                "atm_data_usable": atm_usable,
                "pcr_oi_usable": pcr_usable,

                "iv_surface_available": (
                    iv_surface[
                        "available"
                    ]
                ),

                "iv_surface_status": (
                    iv_surface[
                        "status"
                    ]
                ),

                "iv_surface_usable": (
                    iv_surface_usable
                ),

                "iv_surface_timestamp_aligned": (
                    iv_surface[
                        "timestamp_aligned"
                    ]
                ),

                "options_intelligence_status": (
                    options_intelligence[
                        "quality"
                    ][
                        "overall_status"
                    ]
                ),

                "gex_available": (
                    gex["available"]
                ),
                "gex_status": (
                    gex_quality["status"]
                ),
                "gex_full_chain_usable": (
                    gex_quality[
                        "full_chain_usable"
                    ]
                ),
                "gex_atm_window_usable": (
                    gex_quality[
                        "atm_window_usable"
                    ]
                ),
                "gex_evolution_available": (
                    gex_evolution[
                        "available"
                    ]
                ),
                "timestamps_aligned": (
                    timestamps_aligned
                ),
                "market_context_version": (
                    self.MARKET_CONTEXT_VERSION
                ),
                "gex_version": (
                    self.GEX_VERSION
                ),
            },
        }

    # =========================================================
    # SAMPLE
    # =========================================================

    def run_sample(self) -> dict:

        return self.build(
            expiry_date="2024-11-28"
        )


# =============================================================
# CLI
# =============================================================

def main() -> None:

    parser = argparse.ArgumentParser(
        description=(
            "Kunal Quant - "
            "Market Regime Context V1.1"
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

    engine = MarketRegimeContext()

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

    print()
    print("=" * 75)
    print(
        "KUNAL QUANT - "
        "MARKET REGIME CONTEXT V1.1"
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
