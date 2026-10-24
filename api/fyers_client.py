import os
from pathlib import Path
from typing import Any, Sequence

from dotenv import load_dotenv
from fyers_apiv3 import fyersModel
from fyers_apiv3.FyersWebsocket import data_ws


# ============================================================
# KUNAL QUANT
# FYERS API CLIENT
#
# Permanent reusable FYERS interface for:
#
#   Profile
#   Funds
#   Positions
#   Quotes
#   Historical candles
#   Futures chain
#   Expired F&O expiry dates
#   Expired F&O contracts
#   Expired F&O historical data
#   Market depth
#   WebSocket factory
#
# Secrets remain local in:
#
#   .env
#   fyers_access_token.txt
# ============================================================


class FyersClient:
    """Reusable FYERS API wrapper for Kunal Quant."""

    def __init__(
        self,
        project_root: Path | str | None = None,
    ) -> None:

        # ------------------------------------------------------
        # PROJECT ROOT
        # ------------------------------------------------------

        if project_root is None:
            self.project_root = (
                Path(__file__).resolve().parents[1]
            )
        else:
            self.project_root = Path(project_root).resolve()

        # ------------------------------------------------------
        # LOAD .ENV
        # ------------------------------------------------------

        load_dotenv(
            self.project_root / ".env"
        )

        self.client_id = os.getenv(
            "FYERS_CLIENT_ID",
            ""
        ).strip()

        self.token_file = (
            self.project_root /
            "fyers_access_token.txt"
        )

        # ------------------------------------------------------
        # VALIDATE CREDENTIALS
        # ------------------------------------------------------

        if not self.client_id:
            raise ValueError(
                "FYERS_CLIENT_ID is missing from .env"
            )

        if not self.token_file.exists():
            raise FileNotFoundError(
                "fyers_access_token.txt was not found."
            )

        self.access_token = (
            self.token_file.read_text(
                encoding="utf-8"
            ).strip()
        )

        if not self.access_token:
            raise ValueError(
                "fyers_access_token.txt is empty."
            )

        # ------------------------------------------------------
        # FYERS MODEL
        # ------------------------------------------------------

        self.model = fyersModel.FyersModel(
            client_id=self.client_id,
            token=self.access_token,
            is_async=False,
            log_path=""
        )

    # ========================================================
    # BASIC HELPERS
    # ========================================================

    @property
    def auth_token(self) -> str:
        """
        Authentication format required by FYERS WebSocket:

            CLIENT_ID:ACCESS_TOKEN
        """

        return (
            f"{self.client_id}:"
            f"{self.access_token}"
        )

    @staticmethod
    def _validate_response(
        response: Any,
        operation: str
    ) -> Any:
        """
        FYERS normally returns:
            {'s': 'ok', ...}

        Raise a useful exception for API errors.
        """

        if response is None:
            raise RuntimeError(
                f"FYERS returned no response "
                f"for {operation}."
            )

        if isinstance(response, dict):

            status = response.get("s")

            if status == "error":
                raise RuntimeError(
                    f"FYERS {operation} failed: "
                    f"{response}"
                )

        return response

    # ========================================================
    # ACCOUNT APIs
    # ========================================================

    def profile(self) -> dict:
        """Return FYERS profile information."""

        response = self.model.get_profile()

        return self._validate_response(
            response,
            "profile"
        )

    def funds(self) -> dict:
        """Return account funds."""

        response = self.model.funds()

        return self._validate_response(
            response,
            "funds"
        )

    def positions(self) -> dict:
        """Return current positions."""

        response = self.model.positions()

        return self._validate_response(
            response,
            "positions"
        )

    # ========================================================
    # MARKET QUOTES
    # ========================================================

    def quotes(
        self,
        symbols: str | Sequence[str]
    ) -> dict:
        """
        Get quote snapshots.

        FYERS supports up to 50 symbols per quote request.
        """

        if isinstance(symbols, str):
            symbol_list = [
                symbols
            ]
        else:
            symbol_list = list(symbols)

        symbol_list = [
            str(symbol).strip()
            for symbol in symbol_list
            if str(symbol).strip()
        ]

        if not symbol_list:
            raise ValueError(
                "At least one symbol is required."
            )

        if len(symbol_list) > 50:
            raise ValueError(
                "FYERS quote request supports "
                "a maximum of 50 symbols."
            )

        request = {
            "symbols": ",".join(symbol_list)
        }

        response = self.model.quotes(
            data=request
        )

        return self._validate_response(
            response,
            "quotes"
        )

    # ========================================================
    # STANDARD HISTORICAL DATA
    # ========================================================

    def history(
        self,
        symbol: str,
        resolution: str = "1",
        range_from: str | None = None,
        range_to: str | None = None,
        date_format: str = "1",
        cont_flag: str = "0",
        oi_flag: str | None = None,
    ) -> dict:
        """
        Get standard historical market data.

        Parameters
        ----------
        symbol:
            FYERS API symbol.

        resolution:
            "1", "3", "5", etc.

        range_from / range_to:
            YYYY-MM-DD when date_format="1".

        cont_flag:
            "1" for continuous futures when required.

        oi_flag:
            "1" to request OI where supported.
        """

        if not range_from or not range_to:
            raise ValueError(
                "range_from and range_to are required."
            )

        request = {
            "symbol": symbol,
            "resolution": resolution,
            "date_format": date_format,
            "range_from": range_from,
            "range_to": range_to,
            "cont_flag": cont_flag,
        }

        if oi_flag is not None:
            request["oi_flag"] = oi_flag

        response = self.model.history(
            data=request
        )

        return self._validate_response(
            response,
            "history"
        )

    # ========================================================
    # FUTURES CHAIN
    # ========================================================

    def futures_chain(
        self,
        symbol: str
    ) -> dict:
        """Return the futures chain for an underlying."""

        request = {
            "symbol": symbol
        }

        response = self.model.futures_chain(
            data=request
        )

        return self._validate_response(
            response,
            "futures_chain"
        )

    # ========================================================
    # EXPIRED F&O — EXPIRY DATES
    # ========================================================

    def expired_expiry_dates(
        self,
        symbol: str,
        range_from: str,
        range_to: str,
        date_format: str = "1",
    ) -> dict:
        """
        Return historical futures/options expiry dates.
        """

        request = {
            "symbol": symbol,
            "range_from": range_from,
            "range_to": range_to,
            "date_format": date_format,
        }

        response = self.model.expiry_dates(
            data=request
        )

        return self._validate_response(
            response,
            "expired_expiry_dates"
        )

    # ========================================================
    # EXPIRED F&O — CONTRACTS
    # ========================================================

    def expired_contracts(
        self,
        symbol: str,
        expiry_date: str,
    ) -> dict:
        """
        Return historical F&O contracts for an expiry date.
        """

        request = {
            "symbol": symbol,
            "expiry_date": expiry_date,
        }

        response = (
            self.model.history_underlying_symbols(
                data=request
            )
        )

        return self._validate_response(
            response,
            "expired_contracts"
        )

    # ========================================================
    # EXPIRED F&O — HISTORICAL DATA
    # ========================================================

    def expired_history(
        self,
        symbol: str,
        resolution: str = "1",
        range_from: str | None = None,
        range_to: str | None = None,
        include_oi: str = "1",
        include_greeks: str = "1",
        date_format: str = "1",
    ) -> dict:
        """
        Return historical data for an expired F&O contract.

        The response may contain:

            timestamp
            open
            high
            low
            close
            volume
            open_interest
            iv
            delta
            gamma
            theta
            vega
        """

        if not range_from or not range_to:
            raise ValueError(
                "range_from and range_to are required."
            )

        request = {
            "symbol": symbol,
            "resolution": resolution,
            "date_format": date_format,
            "range_from": range_from,
            "range_to": range_to,
            "include_oi": include_oi,
            "include_greeks": include_greeks,
        }

        response = self.model.fno_historical_data(
            request
        )

        return self._validate_response(
            response,
            "expired_history"
        )

    # ========================================================
    # MARKET DEPTH
    # ========================================================

    def depth(
        self,
        symbol: str,
        ohlcv_flag: str = "1",
    ) -> dict:
        """
        Return FYERS market depth snapshot.
        """

        request = {
            "symbol": symbol,
            "ohlcv_flag": ohlcv_flag,
        }

        response = self.model.depth(
            data=request
        )

        return self._validate_response(
            response,
            "depth"
        )

    # ========================================================
    # WEBSOCKET
    # ========================================================

    def create_data_socket(
        self,
        on_message,
        on_error=None,
        on_close=None,
        on_connect=None,
        reconnect: bool = True,
        lite_mode: bool = False,
        write_to_file: bool = False,
        log_path: str = "",
        reconnect_retry: int = 50,
    ):
        """
        Create a FYERS market-data WebSocket.

        This method creates the socket.
        The caller controls connect()/subscribe()/close().
        """

        socket = data_ws.FyersDataSocket(
            access_token=self.auth_token,
            log_path=log_path,
            litemode=lite_mode,
            write_to_file=write_to_file,
            reconnect=reconnect,
            reconnect_retry=reconnect_retry,   # SDK default 5 gives up within ~30 s; 50 is its maximum
            on_connect=on_connect,
            on_close=on_close,
            on_error=on_error,
            on_message=on_message,
        )

        return socket


# ============================================================
# COMMAND-LINE SANITY TEST
# ============================================================

if __name__ == "__main__":

    print("=" * 70)
    print("KUNAL QUANT - FYERS CLIENT SANITY TEST")
    print("=" * 70)

    client = FyersClient()

    print("\nFYERS client created successfully.")

    print("Client ID:")
    print(client.client_id)

    print("\nToken file:")
    print(client.token_file)

    print("\nAuthentication token available:")
    print(bool(client.auth_token))

    print("\n" + "=" * 70)
    print("CLIENT SANITY TEST COMPLETE")
    print("=" * 70)
    