"""
Unresolved-event classifier for the Kunal Quant option pipeline.

Purpose
-------
`scripts/diagnose_option_data_coverage.py` (in the canonical repo) buckets
every resolver failure into one generic "unresolved" pile via a bare
`except LookupError`, and separately buckets "resolved but no candle
within 1h" as a single pile too. This module classifies both into the
categories the project brief specifies (section 40), by reading the
resolver's own exception message and by distinguishing *why* a resolved
contract has no entry candle -- Option Contract Resolver V2 itself is NOT
modified, and no new database writes happen anywhere in this module.

Five of the brief's nine categories are reachable from this call site:

  - EXPIRY_NOT_FOUND   <- OptionContractResolver.find_nearest_expiry()
  - CONTRACT_NOT_FOUND <- OptionContractResolver.resolve()
  - NO_OPTION_DATA     <- resolved, but the instrument has ZERO candles
                          at all (never downloaded / no data exists)
  - DATA_GAP           <- resolved, the instrument DOES have candles
                          elsewhere, just not within 1h of this signal
                          (a hole in otherwise-present data)
  - UNKNOWN            <- resolver raised a LookupError with a message
                          that matches neither known pattern

NO_OPTION_DATA vs DATA_GAP is a genuine distinction with different
implications (acquisition never happened at all, vs. a hole to
backfill) and is checked against the same `candles` table
`diagnose_option_data_coverage.py` already queries, just without the 1h
window restriction on the first pass.

INVALID_SYMBOL, INSUFFICIENT_HISTORY, and PARSER_FAILURE remain out of
reach from this call site -- they describe failures in the
acquisition/parsing layer (downloader/, instruments/expired_contract_
registry.py), which this classifier has no visibility into once a
contract has already been resolved and stored.

Verified against a synthetic, schema-correct database (built with the
canonical repo's own `database.schema.initialize_database`) -- see
`test_classifier.py` in this same directory. Not run against real data.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from datetime import date
from enum import Enum
from pathlib import Path


class EventClassification(str, Enum):
    RESOLVED_WITH_CANDLE = "RESOLVED_WITH_CANDLE"
    NO_OPTION_DATA = "NO_OPTION_DATA"
    DATA_GAP = "DATA_GAP"
    EXPIRY_NOT_FOUND = "EXPIRY_NOT_FOUND"
    CONTRACT_NOT_FOUND = "CONTRACT_NOT_FOUND"
    UNKNOWN = "UNKNOWN"


_MISSING_CONTRACT_RE = re.compile(
    r"NIFTY (\d{4}-\d{2}-\d{2}) (\d+) (CE|PE)"
)


@dataclass(frozen=True)
class ClassificationResult:
    classification: EventClassification
    detail: str
    # Structured fields, so reports can group by contract/expiry instead
    # of parsing `detail` text. None when not knowable for that outcome
    # (e.g. EXPIRY_NOT_FOUND has no expiry by definition).
    symbol: str | None = None
    expiry: date | None = None
    strike: int | None = None
    option_type: str | None = None


def classify_event(
    resolver,
    *,
    underlying_price: float,
    entry_date: date,
    direction: str,
    signal_timestamp: int,
    database_path: Path | str,
) -> ClassificationResult:
    """
    Resolve one KTMI event and classify the outcome.

    `resolver` is an existing `OptionContractResolver` instance -- passed
    in rather than constructed here, so this never diverges from whatever
    instance the real pipeline is using.
    """

    try:
        contract = resolver.resolve(
            underlying_price=underlying_price,
            entry_date=entry_date,
            direction=direction,
        )
    except LookupError as exc:
        message = str(exc)
        if message.startswith("No ") and "expiry found" in message:
            return ClassificationResult(
                EventClassification.EXPIRY_NOT_FOUND, message
            )
        if message.startswith("Exact option contract not found"):
            match = _MISSING_CONTRACT_RE.search(message)
            if match:
                return ClassificationResult(
                    EventClassification.CONTRACT_NOT_FOUND,
                    message,
                    expiry=date.fromisoformat(match.group(1)),
                    strike=int(match.group(2)),
                    option_type=match.group(3),
                )
            return ClassificationResult(
                EventClassification.CONTRACT_NOT_FOUND, message
            )
        return ClassificationResult(EventClassification.UNKNOWN, message)

    with sqlite3.connect(database_path) as db:
        candle_near_signal = db.execute(
            """
            SELECT COUNT(*)
            FROM candles
            WHERE instrument_id = ?
              AND resolution = '1'
              AND source = 'FYERS_FNO_HISTORY'
              AND timestamp > ?
              AND timestamp <= ?
            """,
            (contract.instrument_id, signal_timestamp, signal_timestamp + 3600),
        ).fetchone()[0]

        if candle_near_signal:
            return ClassificationResult(
                EventClassification.RESOLVED_WITH_CANDLE,
                f"{contract.symbol} ({candle_near_signal} candle(s) within 1h)",
                symbol=contract.symbol,
                expiry=contract.expiry_date,
                strike=contract.strike,
                option_type=contract.option_type,
            )

        candle_anywhere = db.execute(
            """
            SELECT COUNT(*)
            FROM candles
            WHERE instrument_id = ?
              AND resolution = '1'
              AND source = 'FYERS_FNO_HISTORY'
            """,
            (contract.instrument_id,),
        ).fetchone()[0]

    if candle_anywhere == 0:
        return ClassificationResult(
            EventClassification.NO_OPTION_DATA,
            f"{contract.symbol}: 0 candles exist for this instrument at all",
            symbol=contract.symbol,
            expiry=contract.expiry_date,
            strike=contract.strike,
            option_type=contract.option_type,
        )

    return ClassificationResult(
        EventClassification.DATA_GAP,
        f"{contract.symbol}: {candle_anywhere} candle(s) exist elsewhere, "
        "none within 1h of this signal",
        symbol=contract.symbol,
        expiry=contract.expiry_date,
        strike=contract.strike,
        option_type=contract.option_type,
    )
