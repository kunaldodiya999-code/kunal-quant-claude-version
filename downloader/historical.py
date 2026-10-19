from __future__ import annotations

import argparse
import json
import sqlite3
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from api.fyers_client import FyersClient
from config.settings import (
    DATABASE_PATH,
    PRIMARY_RESOLUTION,
    RAW_DATA_DIR,
)


class HistoricalDownloader:
    """
    Kunal Quant Historical Data Downloader V1.

    Responsibilities:

    - Download standard historical data.
    - Download expired F&O historical data.
    - Split long ranges into safe API chunks.
    - Retry failed API requests.
    - Resume completed chunks without repeating them.
    - Store raw broker responses locally.
    - Store canonical OHLCV/OI records in SQLite.
    - Preserve broker timestamps exactly.
    """

    # We previously validated that FYERS historical
    # minute requests need bounded ranges. Using
    # 90-day chunks gives us a safety margin.
    MAX_REQUEST_DAYS = 90

    DEFAULT_MAX_ATTEMPTS = 3

    DEFAULT_RETRY_DELAY = 2.0

    STANDARD_SOURCE = "FYERS_HISTORY"

    EXPIRED_SOURCE = "FYERS_FNO_HISTORY"

    def __init__(
        self,
        database_path: Path | str = DATABASE_PATH,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
        retry_delay_seconds: float = DEFAULT_RETRY_DELAY,
    ) -> None:

        self.database_path = Path(
            database_path
        )

        self.database_path.parent.mkdir(
            parents=True,
            exist_ok=True
        )

        self.fyers = FyersClient()

        self.max_attempts = max(
            1,
            int(max_attempts)
        )

        self.retry_delay_seconds = max(
            0.0,
            float(retry_delay_seconds)
        )

        self.raw_directory = (
            RAW_DATA_DIR
            / "historical"
        )

        self.raw_directory.mkdir(
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
    # INSTRUMENT LOOKUP
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

        if row is not None:

            return dict(row)

        # -----------------------------------------------------
        # STANDARD MARKET INSTRUMENTS
        #
        # The FYERS NSE_FO symbol master contains F&O
        # instruments, but index/spot symbols such as NIFTY
        # and India VIX are not part of that F&O master.
        #
        # Register them locally the first time they are needed.
        # -----------------------------------------------------

        market_instruments = {
            "NSE:NIFTY50-INDEX": {
                "exchange": "NSE",
                "segment": "10",
                "instrument_type": "INDEX",
                "underlying": "NIFTY",
                "currency": "INR",
            },

            "NSE:INDIAVIX-INDEX": {
                "exchange": "NSE",
                "segment": "10",
                "instrument_type": "INDEX",
                "underlying": "INDIAVIX",
                "currency": "INR",
            },
        }

        metadata = market_instruments.get(
            symbol
        )

        if metadata is None:

            return None

        instrument = {
            "broker": "FYERS",
            "exchange": metadata["exchange"],
            "segment": metadata["segment"],
            "symbol": symbol,
            "broker_token": None,
            "security_id": None,
            "underlying": metadata["underlying"],
            "instrument_type": metadata[
                "instrument_type"
            ],
            "expiry_date": None,
            "strike": None,
            "option_type": None,
            "lot_size": None,
            "tick_size": None,
            "currency": metadata["currency"],
            "is_active": 1,
        }

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
            underlying = excluded.underlying,
            instrument_type = excluded.instrument_type,
            currency = excluded.currency,
            is_active = 1,
            updated_at = CURRENT_TIMESTAMP
        """

        with self._connect() as connection:

            connection.execute(
                sql,
                instrument
            )

            connection.commit()

            row = connection.execute(
                query,
                (symbol,)
            ).fetchone()

        if row is None:

            raise RuntimeError(
                f"Market instrument could not be "
                f"registered: {symbol}"
            )

        return dict(row)

    # =========================================================
    # JOB MANAGEMENT
    # =========================================================

    def _find_completed_job(
        self,
        symbol: str,
        resolution: str,
        range_from: str,
        range_to: str,
        source: str,
    ) -> dict | None:

        query = """
        SELECT *
        FROM download_jobs

        WHERE broker = 'FYERS'
          AND symbol = ?
          AND resolution = ?
          AND range_from = ?
          AND range_to = ?
          AND status IN ('COMPLETED', 'EMPTY')

        ORDER BY id DESC

        LIMIT 1
        """

        with self._connect() as connection:

            row = connection.execute(
                query,
                (
                    symbol,
                    resolution,
                    range_from,
                    range_to,
                )
            ).fetchone()

        return (
            dict(row)
            if row is not None
            else None
        )

    def _create_job(
        self,
        symbol: str,
        instrument_id: int | None,
        resolution: str,
        range_from: str,
        range_to: str,
    ) -> int:

        sql = """
        INSERT INTO download_jobs (
            broker,
            symbol,
            instrument_id,
            resolution,
            range_from,
            range_to,
            status,
            retry_count
        )
        VALUES (
            'FYERS',
            ?,
            ?,
            ?,
            ?,
            ?,
            'PENDING',
            0
        )
        """

        with self._connect() as connection:

            cursor = connection.execute(
                sql,
                (
                    symbol,
                    instrument_id,
                    resolution,
                    range_from,
                    range_to,
                )
            )

            connection.commit()

            return int(
                cursor.lastrowid
            )

    def _mark_running(
        self,
        job_id: int,
    ) -> None:

        sql = """
        UPDATE download_jobs

        SET
            status = 'RUNNING',
            started_at = CURRENT_TIMESTAMP

        WHERE id = ?
        """

        with self._connect() as connection:

            connection.execute(
                sql,
                (job_id,)
            )

            connection.commit()

    def _mark_empty(
        self,
        job_id: int,
    ) -> None:

        sql = """
        UPDATE download_jobs

        SET
            status = 'EMPTY',

            received_candles = 0,

            inserted_candles = 0,

            duplicate_candles = 0,

            completed_at = CURRENT_TIMESTAMP

        WHERE id = ?
        """

        with self._connect() as connection:

            connection.execute(
                sql,
                (job_id,)
            )

            connection.commit()

    def _mark_completed(
        self,
        job_id: int,
        received_candles: int,
        inserted_candles: int,
        duplicate_candles: int,
    ) -> None:

        sql = """
        UPDATE download_jobs

        SET
            status = 'COMPLETED',

            received_candles = ?,

            inserted_candles = ?,

            duplicate_candles = ?,

            completed_at = CURRENT_TIMESTAMP

        WHERE id = ?
        """

        with self._connect() as connection:

            connection.execute(
                sql,
                (
                    received_candles,
                    inserted_candles,
                    duplicate_candles,
                    job_id,
                )
            )

            connection.commit()

    def _mark_failed(
        self,
        job_id: int,
        error_message: str,
        retry_count: int,
    ) -> None:

        sql = """
        UPDATE download_jobs

        SET
            status = 'FAILED',

            retry_count = ?,

            error_message = ?

        WHERE id = ?
        """

        with self._connect() as connection:

            connection.execute(
                sql,
                (
                    retry_count,
                    error_message[:4000],
                    job_id,
                )
            )

            connection.commit()

    # =========================================================
    # DATE CHUNKING
    # =========================================================

    @staticmethod
    def _parse_date(
        value: str,
    ) -> datetime:

        return datetime.strptime(
            value,
            "%Y-%m-%d"
        )

    @staticmethod
    def _format_date(
        value: datetime,
    ) -> str:

        return value.strftime(
            "%Y-%m-%d"
        )

    def _build_chunks(
        self,
        range_from: str,
        range_to: str,
    ) -> list[tuple[str, str]]:

        start = self._parse_date(
            range_from
        )

        end = self._parse_date(
            range_to
        )

        if start > end:

            raise ValueError(
                "range_from cannot be after "
                "range_to."
            )

        chunks: list[tuple[str, str]] = []

        current = start

        while current <= end:

            chunk_end = min(
                current
                + timedelta(
                    days=self.MAX_REQUEST_DAYS - 1
                ),
                end,
            )

            chunks.append(
                (
                    self._format_date(
                        current
                    ),
                    self._format_date(
                        chunk_end
                    ),
                )
            )

            current = (
                chunk_end
                + timedelta(days=1)
            )

        return chunks

    # =========================================================
    # RAW RESPONSE STORAGE
    # =========================================================

    @staticmethod
    def _safe_filename(
        symbol: str,
    ) -> str:

        replacements = {
            ":": "_",
            "/": "_",
            "\\": "_",
            " ": "_",
        }

        result = symbol

        for old, new in replacements.items():

            result = result.replace(
                old,
                new
            )

        return result

    def _save_raw_response(
        self,
        symbol: str,
        resolution: str,
        range_from: str,
        range_to: str,
        response: dict,
        source: str,
    ) -> Path:

        symbol_name = (
            self._safe_filename(
                symbol
            )
        )

        directory = (
            self.raw_directory
            / symbol_name
        )

        directory.mkdir(
            parents=True,
            exist_ok=True
        )

        filename = (
            f"{range_from}_"
            f"{range_to}_"
            f"{resolution}_"
            f"{source}.json"
        )

        filepath = (
            directory
            / filename
        )

        filepath.write_text(
            json.dumps(
                response,
                indent=2,
                default=str,
            ),
            encoding="utf-8",
        )

        return filepath

    # =========================================================
    # RESPONSE CANDLES
    # =========================================================

    @staticmethod
    def _extract_candles(
        response: dict,
    ) -> list:

        candles = response.get(
            "candles"
        )

        if candles is None:

            return []

        if not isinstance(
            candles,
            list
        ):

            raise ValueError(
                "FYERS candles response is not "
                "a list."
            )

        return candles

    @staticmethod
    def _normalise_candle(
        candle: Any,
    ) -> tuple:

        if not isinstance(
            candle,
            (list, tuple)
        ):

            raise ValueError(
                "Invalid candle record."
            )

        if len(candle) < 6:

            raise ValueError(
                "Candle has fewer than "
                "6 fields."
            )

        timestamp = int(
            float(candle[0])
        )

        open_price = float(
            candle[1]
        )

        high_price = float(
            candle[2]
        )

        low_price = float(
            candle[3]
        )

        close_price = float(
            candle[4]
        )

        volume = (
            int(float(candle[5]))
            if candle[5] is not None
            else None
        )

        open_interest = None

        # FYERS F&O historical responses
        # put OI after OHLCV.
        if len(candle) >= 7:

            if candle[6] is not None:

                open_interest = int(
                    float(candle[6])
                )

        return (
            timestamp,
            open_price,
            high_price,
            low_price,
            close_price,
            volume,
            open_interest,
        )

    # =========================================================
    # CANDLE STORAGE
    # =========================================================

    def _store_candles(
        self,
        instrument_id: int,
        resolution: str,
        source: str,
        candles: list[tuple],
    ) -> tuple[int, int]:

        if not candles:

            return 0, 0

        sql = """
        INSERT OR IGNORE INTO candles (
            instrument_id,
            timestamp,
            open,
            high,
            low,
            close,
            volume,
            open_interest,
            resolution,
            source
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
            ?
        )
        """

        records = [
            (
                instrument_id,
                timestamp,
                open_price,
                high_price,
                low_price,
                close_price,
                volume,
                open_interest,
                resolution,
                source,
            )
            for (
                timestamp,
                open_price,
                high_price,
                low_price,
                close_price,
                volume,
                open_interest,
            ) in candles
        ]

        with self._connect() as connection:

            cursor = connection.executemany(
                sql,
                records
            )

            connection.commit()

            inserted = max(
                cursor.rowcount,
                0
            )

        duplicates = max(
            len(records) - inserted,
            0
        )

        return (
            inserted,
            duplicates
        )

    # =========================================================
    # API FETCH
    # =========================================================

    def _fetch(
        self,
        symbol: str,
        resolution: str,
        range_from: str,
        range_to: str,
        mode: str,
    ) -> dict:

        if mode == "standard":

            return self.fyers.history(
                symbol=symbol,
                resolution=resolution,
                range_from=range_from,
                range_to=range_to,
                date_format="1",
                cont_flag="0",
            )

        if mode == "expired":

            return self.fyers.expired_history(
                symbol=symbol,
                resolution=resolution,
                range_from=range_from,
                range_to=range_to,
                include_oi="1",
                include_greeks="1",
                date_format="1",
            )

        raise ValueError(
            "mode must be 'standard' "
            "or 'expired'."
        )

    # =========================================================
    # ONE CHUNK
    # =========================================================

    def download_chunk(
        self,
        symbol: str,
        range_from: str,
        range_to: str,
        resolution: str,
        mode: str,
    ) -> dict:

        instrument = self._get_instrument(
            symbol
        )

        if instrument is None:

            raise ValueError(
                f"Instrument not found in "
                f"database: {symbol}"
            )

        instrument_id = int(
            instrument["id"]
        )

        source = (
            self.STANDARD_SOURCE
            if mode == "standard"
            else self.EXPIRED_SOURCE
        )

        existing_job = (
            self._find_completed_job(
                symbol,
                resolution,
                range_from,
                range_to,
                source,
            )
        )

        if existing_job is not None:

            existing_status = str(
                existing_job["status"]
            )

            if existing_status == "EMPTY":

                print(
                    f"\nSKIP empty chunk:"
                    f" {range_from} -> {range_to}"
                )

                return {
                    "status": "EMPTY",
                    "symbol": symbol,
                    "range_from": range_from,
                    "range_to": range_to,
                    "received": 0,
                    "inserted": 0,
                    "duplicates": 0,
                }

            print(
                f"\nSKIP completed chunk:"
                f" {range_from} -> {range_to}"
            )

            return {
                "status": "SKIPPED",
                "symbol": symbol,
                "range_from": range_from,
                "range_to": range_to,
                "received": int(
                    existing_job[
                        "received_candles"
                    ]
                    or 0
                ),
                "inserted": int(
                    existing_job[
                        "inserted_candles"
                    ]
                    or 0
                ),
                "duplicates": int(
                    existing_job[
                        "duplicate_candles"
                    ]
                    or 0
                ),
            }

        job_id = self._create_job(
            symbol=symbol,
            instrument_id=instrument_id,
            resolution=resolution,
            range_from=range_from,
            range_to=range_to,
        )

        self._mark_running(
            job_id
        )

        last_error = None

        response = None

        for attempt in range(
            1,
            self.max_attempts + 1
        ):

            try:

                print(
                    f"\nDownloading:"
                    f" {symbol}"
                    f" | {range_from}"
                    f" -> {range_to}"
                    f" | mode={mode}"
                    f" | attempt={attempt}"
                )

                response = self._fetch(
                    symbol=symbol,
                    resolution=resolution,
                    range_from=range_from,
                    range_to=range_to,
                    mode=mode,
                )

                break

            except Exception as exc:

                last_error = str(
                    exc
                )

                print(
                    f"  Attempt {attempt} "
                    f"failed: {last_error}"
                )

                if attempt < self.max_attempts:

                    delay = (
                        self.retry_delay_seconds
                        * (
                            2 ** (
                                attempt - 1
                            )
                        )
                    )

                    print(
                        f"  Retrying in "
                        f"{delay:.1f}s..."
                    )

                    time.sleep(
                        delay
                    )

        if response is None:

            self._mark_failed(
                job_id,
                (
                    last_error
                    or "Unknown API error"
                ),
                self.max_attempts,
            )

            return {
                "status": "FAILED",
                "symbol": symbol,
                "range_from": range_from,
                "range_to": range_to,
                "error": (
                    last_error
                    or "Unknown API error"
                ),
            }

        candles_raw = (
            self._extract_candles(
                response
            )
        )

        normalized: list[tuple] = []

        for candle in candles_raw:

            normalized.append(
                self._normalise_candle(
                    candle
                )
            )

        # Preserve exact raw broker response.
        raw_path = (
            self._save_raw_response(
                symbol=symbol,
                resolution=resolution,
                range_from=range_from,
                range_to=range_to,
                response=response,
                source=source,
            )
        )

        if not normalized:

            self._mark_empty(
                job_id
            )

            print(
                "  Received candles : 0"
            )

            print(
                "  Status            : EMPTY"
            )

            print(
                f"  Raw response     : {raw_path}"
            )

            return {
                "status": "EMPTY",
                "symbol": symbol,
                "range_from": range_from,
                "range_to": range_to,
                "received": 0,
                "inserted": 0,
                "duplicates": 0,
                "raw_path": str(
                    raw_path
                ),
            }

        inserted, duplicates = (
            self._store_candles(
                instrument_id=instrument_id,
                resolution=resolution,
                source=source,
                candles=normalized,
            )
        )

        self._mark_completed(
            job_id=job_id,
            received_candles=len(
                normalized
            ),
            inserted_candles=inserted,
            duplicate_candles=duplicates,
        )

        print(
            f"  Received candles : "
            f"{len(normalized)}"
        )

        print(
            f"  Inserted candles : "
            f"{inserted}"
        )

        print(
            f"  Duplicates       : "
            f"{duplicates}"
        )

        print(
            f"  Raw response     : "
            f"{raw_path}"
        )

        return {
            "status": "COMPLETED",
            "symbol": symbol,
            "range_from": range_from,
            "range_to": range_to,
            "received": len(
                normalized
            ),
            "inserted": inserted,
            "duplicates": duplicates,
        }

    # =========================================================
    # FULL SYMBOL DOWNLOAD
    # =========================================================

    def download_symbol(
        self,
        symbol: str,
        range_from: str,
        range_to: str,
        resolution: str = PRIMARY_RESOLUTION,
        mode: str = "standard",
    ) -> dict:

        chunks = self._build_chunks(
            range_from,
            range_to,
        )

        results = []

        for chunk_from, chunk_to in chunks:

            result = (
                self.download_chunk(
                    symbol=symbol,
                    range_from=chunk_from,
                    range_to=chunk_to,
                    resolution=resolution,
                    mode=mode,
                )
            )

            results.append(
                result
            )

        return {
            "symbol": symbol,
            "range_from": range_from,
            "range_to": range_to,
            "resolution": resolution,
            "mode": mode,
            "chunks": results,
            "received": sum(
                int(
                    result.get(
                        "received",
                        0
                    )
                )
                for result in results
            ),
            "inserted": sum(
                int(
                    result.get(
                        "inserted",
                        0
                    )
                )
                for result in results
            ),
            "duplicates": sum(
                int(
                    result.get(
                        "duplicates",
                        0
                    )
                )
                for result in results
            ),
            "failed": sum(
                1
                for result in results
                if result.get(
                    "status"
                ) == "FAILED"
            ),
            "empty": sum(
                1
                for result in results
                if result.get(
                    "status"
                ) == "EMPTY"
            ),
        }

    # =========================================================
    # CONTROLLED SAMPLE
    # =========================================================

    def run_sample(
        self,
    ) -> list[dict]:

        samples = [
            {
                "symbol":
                    "NSE:NIFTY50-INDEX",
                "mode":
                    "standard",
            },
            {
                "symbol":
                    "NSE:INDIAVIX-INDEX",
                "mode":
                    "standard",
            },
            {
                "symbol":
                    "NSE:NIFTY24NOVFUT",
                "mode":
                    "expired",
            },
            {
                "symbol":
                    "NSE:NIFTY24NOV22500CE",
                "mode":
                    "expired",
            },
            {
                "symbol":
                    "NSE:NIFTY24NOV22500PE",
                "mode":
                    "expired",
            },
        ]

        results = []

        for item in samples:

            results.append(
                self.download_symbol(
                    symbol=item["symbol"],
                    range_from="2024-11-27",
                    range_to="2024-11-28",
                    resolution="1",
                    mode=item["mode"],
                )
            )

        return results


# =============================================================
# CLI
# =============================================================

def main() -> None:

    parser = argparse.ArgumentParser(
        description=(
            "Kunal Quant - Historical "
            "Data Downloader V1"
        )
    )

    parser.add_argument(
        "--symbol",
        type=str,
        default=None,
        help="FYERS symbol to download.",
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

    parser.add_argument(
        "--mode",
        type=str,
        choices=("standard", "expired"),
        default="standard",
        help="Historical API mode.",
    )

    parser.add_argument(
        "--resolution",
        type=str,
        default="1",
        help="Candle resolution.",
    )

    parser.add_argument(
        "--sample",
        action="store_true",
        help=(
            "Run the controlled NIFTY "
            "historical sample."
        ),
    )

    args = parser.parse_args()

    print("=" * 75)

    print(
        "KUNAL QUANT - HISTORICAL DOWNLOADER V1"
    )

    print("=" * 75)

    downloader = HistoricalDownloader()

    # ---------------------------------------------------------
    # CONTROLLED SAMPLE
    # ---------------------------------------------------------

    if args.sample:

        results = (
            downloader.run_sample()
        )

        print(
            "\n" + "=" * 75
        )

        print(
            "CONTROLLED SAMPLE RESULT"
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
            "HISTORICAL DOWNLOAD COMPLETE"
        )

        print(
            "=" * 75
        )

        return

    # ---------------------------------------------------------
    # INDIVIDUAL DOWNLOAD
    # ---------------------------------------------------------

    if not args.symbol:

        raise SystemExit(
            "Provide --symbol or use --sample."
        )

    if not args.range_from:

        raise SystemExit(
            "--from is required."
        )

    if not args.range_to:

        raise SystemExit(
            "--to is required."
        )

    result = (
        downloader.download_symbol(
            symbol=args.symbol,
            range_from=args.range_from,
            range_to=args.range_to,
            resolution=args.resolution,
            mode=args.mode,
        )
    )

    print(
        "\n" + "=" * 75
    )

    print(
        "DOWNLOAD RESULT"
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
        "HISTORICAL DOWNLOAD COMPLETE"
    )

    print(
        "=" * 75
    )


if __name__ == "__main__":

    main()