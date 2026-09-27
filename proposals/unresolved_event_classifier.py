"""
Unresolved-event classifier for the Kunal Quant option pipeline.

Purpose
-------
`scripts/diagnose_option_data_coverage.py` (in the canonical repo) buckets
every resolver failure into one generic "unresolved" pile via a bare
`except LookupError`. This module classifies that same LookupError into the
categories the project brief specifies (section 40), by reading the
resolver's own exception message — Option Contract Resolver V2 itself is
NOT modified.

Only two of the brief's nine categories can currently be distinguished this
way, because those are the only two distinct LookupError sites that exist
in `strategies/option_contract_resolver.py` today:

  - EXPIRY_NOT_FOUND   <- OptionContractResolver.find_nearest_expiry()
  - CONTRACT_NOT_FOUND <- OptionContractResolver.resolve()

A third category, NO_ENTRY_CANDLE, is added from the "candle within 1h"
check that diagnose_option_data_coverage.py already performs — it just
never labeled it. The remaining categories (NO_OPTION_DATA, DATA_GAP,
INVALID_SYMBOL, INSUFFICIENT_HISTORY, PARSER_FAILURE) are not detectable
from this call site at all; they'd need signal from the acquisition/parsing
layer, which this module does not have visibility into. Anything that
doesn't match the two known patterns falls into UNKNOWN rather than being
guessed at.

Verified against a synthetic, schema-correct database (built with the
canonical repo's own `database.schema.initialize_database`) — see
`test_classifier.py` in this same directory. Not run against real data.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date
from enum import Enum
from pathlib import Path


class EventClassification(str, Enum):
    RESOLVED_WITH_CANDLE = "RESOLVED_WITH_CANDLE"
    NO_ENTRY_CANDLE = "NO_ENTRY_CANDLE"
    EXPIRY_NOT_FOUND = "EXPIRY_NOT_FOUND"
    CONTRACT_NOT_FOUND = "CONTRACT_NOT_FOUND"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class ClassificationResult:
    classification: EventClassification
    detail: str


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

    `resolver` is an existing `OptionContractResolver` instance — passed in
    rather than constructed here, so this never diverges from whatever
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
            return ClassificationResult(
                EventClassification.CONTRACT_NOT_FOUND, message
            )
        return ClassificationResult(EventClassification.UNKNOWN, message)

    with sqlite3.connect(database_path) as db:
        row = db.execute(
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
        ).fetchone()

    if row[0]:
        return ClassificationResult(
            EventClassification.RESOLVED_WITH_CANDLE,
            f"{contract.symbol} ({row[0]} candle(s) within 1h)",
        )

    return ClassificationResult(
        EventClassification.NO_ENTRY_CANDLE,
        f"{contract.symbol} resolved, 0 candles within 1h",
    )
