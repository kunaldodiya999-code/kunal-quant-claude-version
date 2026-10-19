import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

from config.settings import RAW_DATA_DIR


# ============================================================
# KUNAL QUANT
# FYERS NSE F&O SYMBOL MASTER
# ============================================================

MASTER_NAME = "NSE_FO"

MASTER_URL = (
    "https://public.fyers.in/"
    "sym_details/NSE_FO_sym_master.json"
)

LOCAL_MASTER_DIR = RAW_DATA_DIR / "fyers"

LOCAL_MASTER_FILE = (
    LOCAL_MASTER_DIR /
    "NSE_FO_sym_master.json"
)


# ------------------------------------------------------------
# DOWNLOAD
# ------------------------------------------------------------

def download_symbol_master(
    force_refresh: bool = False,
) -> dict[str, Any]:

    LOCAL_MASTER_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    # Use local copy when available unless a refresh
    # was explicitly requested.
    if (
        LOCAL_MASTER_FILE.exists()
        and not force_refresh
    ):
        print(
            f"Loading cached symbol master:\n"
            f"{LOCAL_MASTER_FILE}"
        )

        with open(
            LOCAL_MASTER_FILE,
            "r",
            encoding="utf-8"
        ) as file:

            return json.load(file)

    print("Downloading FYERS NSE F&O symbol master...")

    response = requests.get(
        MASTER_URL,
        timeout=60,
        headers={
            "User-Agent": "KunalQuant/1.0"
        }
    )

    response.raise_for_status()

    data = response.json()

    if not isinstance(data, dict):
        raise RuntimeError(
            "Unexpected FYERS symbol master format."
        )

    with open(
        LOCAL_MASTER_FILE,
        "w",
        encoding="utf-8"
    ) as file:

        json.dump(
            data,
            file,
            ensure_ascii=False
        )

    print(
        f"Symbol master saved locally:\n"
        f"{LOCAL_MASTER_FILE}"
    )

    return data


# ------------------------------------------------------------
# EXPIRY CONVERSION
# ------------------------------------------------------------

def expiry_to_date(
    expiry_value: Any
) -> str | None:

    if expiry_value in (
        None,
        "",
        0,
        "0"
    ):
        return None

    try:

        timestamp = int(
            expiry_value
        )

        return datetime.fromtimestamp(
            timestamp,
            tz=timezone.utc
        ).strftime(
            "%Y-%m-%d"
        )

    except (
        ValueError,
        TypeError,
        OverflowError
    ):

        return str(expiry_value)


# ------------------------------------------------------------
# NORMALIZE ONE RECORD
# ------------------------------------------------------------

def normalize_record(
    symbol: str,
    record: dict[str, Any]
) -> dict[str, Any]:

    strike = record.get(
        "strikePrice"
    )

    # FYERS uses -1 for instruments where strike
    # does not apply.
    if strike is not None:
        try:

            strike = float(strike)

            if strike < 0:
                strike = None

        except (
            ValueError,
            TypeError
        ):
            strike = None

    lot_size = record.get(
        "minLotSize"
    )

    if lot_size is not None:
        try:
            lot_size = int(lot_size)
        except (
            ValueError,
            TypeError
        ):
            lot_size = None

    tick_size = record.get(
        "tickSize"
    )

    if tick_size is not None:
        try:
            tick_size = float(tick_size)
        except (
            ValueError,
            TypeError
        ):
            tick_size = None

    return {
        "broker": "FYERS",

        "exchange": record.get(
            "exchangeName"
        ) or "NSE",

        "segment": record.get(
            "exchange"
        ),

        "symbol": (
            record.get("symTicker")
            or symbol
        ),

        "broker_token": record.get(
            "fyToken"
        ),

        "security_id": None,

        "underlying": record.get(
            "underSym"
        ),

        "instrument_type": record.get(
            "exInstType"
        ),

        "expiry_date": expiry_to_date(
            record.get("expiryDate")
        ),

        "strike": strike,

        "option_type": record.get(
            "optType"
        ),

        "lot_size": lot_size,

        "tick_size": tick_size,

        "currency": record.get(
            "currencyCode"
        ) or "INR",

        "is_active": 1,
    }


# ------------------------------------------------------------
# NORMALIZE COMPLETE MASTER
# ------------------------------------------------------------

def normalize_master(
    raw_master: dict[str, Any]
) -> list[dict[str, Any]]:

    normalized = []

    for symbol, record in raw_master.items():

        if not isinstance(
            record,
            dict
        ):
            continue

        try:

            normalized.append(
                normalize_record(
                    symbol,
                    record
                )
            )

        except Exception as error:

            print(
                f"WARNING: Could not normalize "
                f"{symbol}: {error}"
            )

    return normalized


# ------------------------------------------------------------
# FILTER NIFTY
# ------------------------------------------------------------

def find_nifty_contracts(
    instruments: list[dict[str, Any]]
) -> list[dict[str, Any]]:

    results = []

    for instrument in instruments:

        underlying = (
            str(
                instrument.get(
                    "underlying"
                ) or ""
            )
            .upper()
        )

        symbol = (
            str(
                instrument.get(
                    "symbol"
                ) or ""
            )
            .upper()
        )

        # We want NIFTY index derivatives,
        # not BANKNIFTY / NIFTYFUTSTK etc.
        if (
            underlying == "NIFTY"
            or symbol.startswith("NSE:NIFTY")
        ):
            results.append(
                instrument
            )

    return results


# ------------------------------------------------------------
# FILTER OPTIONS
# ------------------------------------------------------------

def find_nifty_options(
    instruments: list[dict[str, Any]]
) -> list[dict[str, Any]]:

    return [
        instrument
        for instrument in find_nifty_contracts(
            instruments
        )
        if instrument.get(
            "option_type"
        ) in (
            "CE",
            "PE"
        )
    ]


# ------------------------------------------------------------
# FILTER FUTURES
# ------------------------------------------------------------

def find_nifty_futures(
    instruments: list[dict[str, Any]]
) -> list[dict[str, Any]]:

    return [
        instrument
        for instrument in find_nifty_contracts(
            instruments
        )
        if instrument.get(
            "instrument_type"
        ) == 11
    ]


# ------------------------------------------------------------
# FIND EXACT SYMBOL
# ------------------------------------------------------------

def get_instrument(
    instruments: list[dict[str, Any]],
    symbol: str
) -> dict[str, Any] | None:

    target = symbol.strip().upper()

    for instrument in instruments:

        if str(
            instrument.get("symbol")
        ).upper() == target:

            return instrument

    return None


# ------------------------------------------------------------
# MASTER SUMMARY
# ------------------------------------------------------------

def master_summary(
    instruments: list[dict[str, Any]]
) -> dict[str, int]:

    options = 0
    futures = 0

    for instrument in instruments:

        option_type = instrument.get(
            "option_type"
        )

        instrument_type = instrument.get(
            "instrument_type"
        )

        if option_type in (
            "CE",
            "PE"
        ):
            options += 1

        if instrument_type == 11:
            futures += 1

    return {
        "total": len(instruments),
        "options": options,
        "futures": futures,
    }


# ------------------------------------------------------------
# COMMAND-LINE TEST
# ------------------------------------------------------------

if __name__ == "__main__":

    print("=" * 75)
    print("KUNAL QUANT - FYERS NSE F&O SYMBOL MASTER")
    print("=" * 75)

    raw = download_symbol_master(
        force_refresh=True
    )

    print(
        "\nRaw instruments received:",
        len(raw)
    )

    instruments = normalize_master(
        raw
    )

    print(
        "Normalized instruments:",
        len(instruments)
    )

    summary = master_summary(
        instruments
    )

    print("\nMaster summary:")

    for key, value in summary.items():
        print(
            f"  {key:10s}: {value}"
        )

    # --------------------------------------------------------
    # NIFTY
    # --------------------------------------------------------

    nifty = find_nifty_contracts(
        instruments
    )

    nifty_options = find_nifty_options(
        instruments
    )

    nifty_futures = find_nifty_futures(
        instruments
    )

    print(
        "\nNIFTY-related instruments:",
        len(nifty)
    )

    print(
        "NIFTY options:",
        len(nifty_options)
    )

    print(
        "NIFTY futures:",
        len(nifty_futures)
    )

    # --------------------------------------------------------
    # FIND KNOWN CONTRACTS
    # --------------------------------------------------------

    known_symbols = [
        "NSE:NIFTY24NOV22500CE",
        "NSE:NIFTY24NOV22500PE",
        "NSE:NIFTY24NOVFUT",
    ]

    print("\nKnown-contract validation:")

    for symbol in known_symbols:

        instrument = get_instrument(
            instruments,
            symbol
        )

        if instrument:

            print(
                f"\n[FOUND] {symbol}"
            )

            print(
                json.dumps(
                    instrument,
                    indent=2
                )
            )

        else:

            print(
                f"\n[NOT FOUND] {symbol}"
            )

    print("\n" + "=" * 75)
    print("SYMBOL MASTER TEST COMPLETE")
    print("=" * 75)