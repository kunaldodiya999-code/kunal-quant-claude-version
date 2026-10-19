from __future__ import annotations

import argparse
import json
import re
from datetime import datetime
from pathlib import Path

from api.fyers_client import FyersClient

from config.settings import DATABASE_PATH

from database.repository import (
    DatabaseRepository,
)

from instruments.symbol_master import (
    download_symbol_master,
    normalize_master,
    get_instrument,
)


class InstrumentManager:
    """
    Central instrument-management layer.

    Responsibilities:

    - Load FYERS current symbol master
    - Normalize instruments
    - Import instruments into SQLite
    - Resolve current contracts
    - Register expired F&O contracts
    - Query stored instruments
    """

    def __init__(
        self,
        database_path: Path | str = DATABASE_PATH,
    ) -> None:

        self.repository = (
            DatabaseRepository(
                database_path
            )
        )

        self.fyers = FyersClient()

        self.instruments: list[dict] = []

    # =========================================================
    # CURRENT SYMBOL MASTER
    # =========================================================

    def load_current_master(
        self,
        force_refresh: bool = False,
    ) -> list[dict]:

        raw_master = (
            download_symbol_master(
                force_refresh=force_refresh
            )
        )

        self.instruments = (
            normalize_master(
                raw_master
            )
        )

        return self.instruments

    def import_current_master(
        self,
        force_refresh: bool = False,
    ) -> int:

        instruments = (
            self.load_current_master(
                force_refresh=force_refresh
            )
        )

        inserted = (
            self.repository.upsert_instruments(
                instruments
            )
        )

        return inserted

    # =========================================================
    # CURRENT CONTRACT RESOLUTION
    # =========================================================

    def resolve_current(
        self,
        symbol: str,
    ) -> dict | None:

        if self.instruments:

            result = get_instrument(
                self.instruments,
                symbol
            )

            if result:
                return result

        return (
            self.repository.get_instrument(
                "FYERS",
                symbol
            )
        )

    # =========================================================
    # OPTIONS
    # =========================================================

    def get_options(
        self,
        underlying: str = "NIFTY",
        expiry_date: str | None = None,
        option_type: str | None = None,
    ) -> list[dict]:

        return self.repository.find_options(
            underlying=underlying,
            expiry_date=expiry_date,
            option_type=option_type,
        )

    # =========================================================
    # EXPIRED CONTRACT PARSING
    # =========================================================

    @staticmethod
    def _extract_contract_symbol(
        contract: str | dict,
    ) -> tuple[str, str | None]:

        if isinstance(contract, str):

            return contract, None

        if isinstance(contract, dict):

            possible_symbol_keys = (
                "symbol",
                "symTicker",
                "fySymbol",
                "ticker",
            )

            possible_token_keys = (
                "fyToken",
                "fy_token",
                "token",
                "broker_token",
            )

            symbol = None

            for key in possible_symbol_keys:

                value = contract.get(key)

                if value:

                    symbol = str(value)

                    break

            if symbol is None:

                raise ValueError(
                    f"Could not find symbol in contract record: "
                    f"{contract}"
                )

            token = None

            for key in possible_token_keys:

                value = contract.get(key)

                if value is not None:

                    token = str(value)

                    break

            return symbol, token

        raise TypeError(
            "Unsupported expired contract type: "
            f"{type(contract).__name__}"
        )

    @staticmethod
    def _build_expired_instrument(
        symbol: str,
        underlying: str,
        expiry_date: str,
        broker_token: str | None = None,
    ) -> dict:

        clean_symbol = symbol.strip()

        exchange = "NSE"

        if ":" in clean_symbol:

            exchange, ticker = (
                clean_symbol.split(
                    ":",
                    1
                )
            )

        else:

            ticker = clean_symbol

        strike = None
        option_type = "XX"
        instrument_type = 11

                # -----------------------------------------------------
        # OPTION
        # -----------------------------------------------------

        option_match = re.match(
            r"^(.*?)(CE|PE)$",
            ticker,
            flags=re.IGNORECASE,
        )

        if option_match:

            option_type = (
                option_match.group(2).upper()
            )
            instrument_type = 14

            option_body = (
                option_match.group(1)
            )

            # -------------------------------------------------
            # Decode the known historical FYERS expiry token.
            #
            # Observed FYERS formats include:
            #
            # Weekly:
            #   NIFTY24N2118200CE
            #        ^^^^^  ^^^^^
            #        24N21  18200
            #
            # Monthly:
            #   NIFTY24NOV22500CE
            #        ^^^^^^ ^^^^^
            #        24NOV   22500
            #
            # The expiry date passed to this function is the
            # authoritative source for constructing the token.
            # -------------------------------------------------

            expiry_value = datetime.strptime(
                expiry_date,
                "%Y-%m-%d",
            )

            year_code = (
                expiry_value.strftime("%y")
            )

            month_number = (
                expiry_value.strftime("%m")
            )

            day_code = (
                expiry_value.strftime("%d")
            )

            month_letter = (
                expiry_value.strftime("%b")[0].upper()
            )

            month_short = (
                expiry_value.strftime("%b").upper()
            )

            # Historical FYERS symbols also use an unpadded
            # numeric month token, e.g.:
            #
            #   2021-01-07 -> NIFTY2110710600CE
            #                    21 + 1 + 07 + 10600
            #
            # Keep both padded and unpadded variants so the
            # expiry supplied by FYERS remains authoritative.
            month_number_unpadded = str(
                int(month_number)
            )

            expiry_candidates = [
                year_code
                + month_letter
                + day_code,

                year_code
                + month_short
                + day_code,

                year_code
                + month_short,

                year_code
                + month_number_unpadded
                + day_code,

                year_code
                + month_number
                + day_code,

                year_code
                + month_number_unpadded,

                year_code
                + month_number,
            ]

            expiry_candidates = sorted(
                set(expiry_candidates),
                key=len,
                reverse=True,
            )

            expiry_index = None
            expiry_prefix = None
            strike_text = None

            for candidate in expiry_candidates:

                index = option_body.find(
                    candidate
                )

                if index <= 0:

                    continue

                possible_strike = (
                    option_body[
                        index
                        + len(candidate):
                    ]
                )

                if not possible_strike:

                    continue

                # Monthly FYERS symbols can make a date-shaped
                # prefix appear to consume the first digits of the strike.
                # Example:
                #   NIFTY24NOV28000CE
                # must decode as 24NOV + 28000, not
                # 24NOV28 + 000.
                #
                # NIFTY option strikes in this historical dataset are
                # at least four digits. Reject shorter numeric suffixes
                # so the parser can fall through to the shorter, correct
                # expiry token.
                if (
                    not possible_strike.isdigit()
                    or len(possible_strike) < 4
                ):

                    continue

                expiry_index = index
                expiry_prefix = candidate
                strike_text = possible_strike

                break

            if (
                expiry_index is None
                or expiry_prefix is None
                or strike_text is None
            ):

                raise ValueError(
                    "Unable to decode expiry/strike "
                    f"from expired option symbol: "
                    f"{symbol} | expiry={expiry_date}"
                )

            strike = float(
                strike_text
            )

        # -----------------------------------------------------
        # FUTURE
        # -----------------------------------------------------

        elif ticker.endswith("FUT"):

            option_type = "XX"

        # -----------------------------------------------------
        # SAFETY
        # -----------------------------------------------------

        else:

            raise ValueError(
                f"Unable to classify expired contract: "
                f"{symbol}"
            )

        return {
            "broker": "FYERS",
            "exchange": exchange,
            "segment": 10,
            "symbol": clean_symbol,
            "broker_token": broker_token,
            "security_id": None,
            "underlying": underlying,
            "instrument_type": instrument_type,
            "expiry_date": expiry_date,
            "strike": strike,
            "option_type": option_type,
            "lot_size": None,
            "tick_size": None,
            "currency": "INR",
            "is_active": 0,
        }

    # =========================================================
    # EXPIRED CONTRACT REGISTRY
    # =========================================================

    def register_expired_contracts(
        self,
        underlying_symbol: str,
        expiry_date: str,
    ) -> dict:

        print(
            f"\nFetching expired contracts:"
            f" {underlying_symbol}"
            f" | expiry={expiry_date}"
        )

        response = (
            self.fyers.expired_contracts(
                underlying_symbol,
                expiry_date
            )
        )

        contracts_data = (
            response
            .get("data", {})
            .get("contracts", {})
        )

        futures = (
            contracts_data.get(
                "futures",
                []
            )
        )

        options = (
            contracts_data.get(
                "options",
                []
            )
        )

        records: list[dict] = []

        # -----------------------------------------------------
        # FUTURES
        # -----------------------------------------------------

        for contract in futures:

            symbol, token = (
                self._extract_contract_symbol(
                    contract
                )
            )

            record = (
                self._build_expired_instrument(
                    symbol=symbol,
                    underlying=underlying_symbol.split(":")[-1]
                    .replace("-INDEX", ""),
                    expiry_date=expiry_date,
                    broker_token=token,
                )
            )

            records.append(record)

        # -----------------------------------------------------
        # OPTIONS
        # -----------------------------------------------------

        for contract in options:

            symbol, token = (
                self._extract_contract_symbol(
                    contract
                )
            )

            record = (
                self._build_expired_instrument(
                    symbol=symbol,
                    underlying=underlying_symbol.split(":")[-1]
                    .replace("-INDEX", ""),
                    expiry_date=expiry_date,
                    broker_token=token,
                )
            )

            records.append(record)

        # -----------------------------------------------------
        # DATABASE
        # -----------------------------------------------------

        inserted = (
            self.repository.upsert_instruments(
                records
            )
        )

        result = {
            "underlying_symbol": underlying_symbol,
            "expiry_date": expiry_date,
            "futures": len(futures),
            "options": len(options),
            "total": len(records),
            "database_records_processed": inserted,
        }

        return result

    # =========================================================
    # SUMMARY
    # =========================================================

    def summary(self) -> dict:

        return (
            self.repository.instrument_summary()
        )


# =============================================================
# CLI
# =============================================================

def main() -> None:

    parser = argparse.ArgumentParser(
        description="Kunal Quant Instrument Manager"
    )

    parser.add_argument(
        "--force-refresh",
        action="store_true",
        help="Force refresh FYERS current symbol master.",
    )

    parser.add_argument(
        "--register-expiry",
        type=str,
        default=None,
        help="Register expired contracts for YYYY-MM-DD expiry.",
    )

    parser.add_argument(
        "--underlying",
        type=str,
        default="NSE:NIFTY50-INDEX",
        help="FYERS underlying symbol for expired contracts.",
    )

    args = parser.parse_args()

    print("=" * 75)
    print("KUNAL QUANT - INSTRUMENT MANAGER")
    print("=" * 75)

    manager = InstrumentManager()

    # ---------------------------------------------------------
    # CURRENT MASTER
    # ---------------------------------------------------------

    print(
        "\nImporting current FYERS symbol master..."
    )

    count = (
        manager.import_current_master(
            force_refresh=args.force_refresh
        )
    )

    print(
        "\nRecords processed:",
        count
    )

    # ---------------------------------------------------------
    # SUMMARY
    # ---------------------------------------------------------

    summary = manager.summary()

    print(
        "\nDatabase summary:"
    )

    for key, value in summary.items():

        print(
            f"  {key:10s}: {value}"
        )

    # ---------------------------------------------------------
    # CURRENT CONTRACT
    # ---------------------------------------------------------

    symbol = "NSE:NIFTY26SEPFUT"

    result = manager.resolve_current(
        symbol
    )

    print(
        "\nCurrent-contract resolution:",
        symbol
    )

    if result:

        print(
            json.dumps(
                result,
                indent=2
            )
        )

    else:

        print(
            "Contract not found."
        )

    # ---------------------------------------------------------
    # EXPIRED REGISTRY
    # ---------------------------------------------------------

    if args.register_expiry:

        result = (
            manager.register_expired_contracts(
                underlying_symbol=args.underlying,
                expiry_date=args.register_expiry,
            )
        )

        print(
            "\nExpired-contract registry result:"
        )

        print(
            json.dumps(
                result,
                indent=2
            )
        )

        print(
            "\nUpdated database summary:"
        )

        updated_summary = manager.summary()

        for key, value in updated_summary.items():

            print(
                f"  {key:10s}: {value}"
            )

    print(
        "\n" + "=" * 75
    )

    print(
        "INSTRUMENT MANAGER TEST COMPLETE"
    )

    print(
        "=" * 75
    )


if __name__ == "__main__":
    main()