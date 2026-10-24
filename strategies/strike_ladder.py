"""Strike ladder: 1 ITM, ATM and 3 OTM strikes for calls and puts.

Example, NIFTY spot 22000, step 50:
    CALL  ITM1 21950 | ATM 22000 | OTM1 22050 | OTM2 22100 | OTM3 22150
    PUT   ITM1 22050 | ATM 22000 | OTM1 21950 | OTM2 21900 | OTM3 21850

An *offset* counts strikes away from ATM in the out-of-the-money direction:
-1 = ITM1, 0 = ATM, +1 = OTM1 ... For a call +1 is the next strike up, for a
put the next strike down. "ATM+1" is offset +1 on either side.

``StrikeLadderResolver`` wraps the locked ``OptionContractResolver`` (same
expiry rule, same database) and only changes which strike is looked up.
"""

from __future__ import annotations

import sqlite3
from datetime import date

from strategies.option_contract_resolver import OptionContractResolver, ResolvedOptionContract

STRIKE_CHOICES: dict[str, int] = {"ITM1": -1, "ATM": 0, "OTM1": 1, "OTM2": 2, "OTM3": 3}


def atm_strike(spot: float, step: int = 50) -> int:
    if spot <= 0 or step <= 0:
        raise ValueError("spot and step must be positive")
    return int(round(spot / step) * step)


def option_type_for(direction: str) -> str:
    direction = direction.upper()
    if direction == "LONG":
        return "CE"
    if direction == "SHORT":
        return "PE"
    raise ValueError("direction must be LONG or SHORT")


def strike_for_offset(spot: float, option_type: str, offset: int, step: int = 50) -> int:
    """Strike ``offset`` steps out of the money from ATM (negative = in the money)."""
    sign = 1 if option_type.upper() == "CE" else -1
    return atm_strike(spot, step) + sign * offset * step


def strike_ladder(spot: float, option_type: str, step: int = 50) -> list[tuple[str, int]]:
    """The five choices shown in the order window, ITM1 first."""
    return [(name, strike_for_offset(spot, option_type, offset, step)) for name, offset in STRIKE_CHOICES.items()]


class StrikeLadderResolver:
    """Resolve the exact contract for a strike offset; offset 0 = the locked ATM rule."""

    def __init__(self, base: OptionContractResolver) -> None:
        self.base = base

    def __getattr__(self, name):  # calculate_atm_strike, find_nearest_expiry, ...
        return getattr(self.base, name)

    def resolve(
        self, *, underlying_price: float, entry_date: date, direction: str, strike_offset: int = 0,
    ) -> ResolvedOptionContract:
        if strike_offset == 0:
            return self.base.resolve(
                underlying_price=underlying_price, entry_date=entry_date, direction=direction
            )
        option_type = option_type_for(direction)
        step = self.base.config.strike_step
        strike = strike_for_offset(underlying_price, option_type, strike_offset, step)
        expiry = self.base.find_nearest_expiry(entry_date=entry_date, option_type=option_type)
        with sqlite3.connect(self.base.database_path) as connection:
            row = connection.execute(
                """
                SELECT id, symbol, underlying, expiry_date, strike, option_type
                FROM instruments
                WHERE broker = 'FYERS' AND underlying = 'NIFTY'
                  AND expiry_date = ? AND strike = ? AND option_type = ?
                ORDER BY symbol
                """,
                (expiry.isoformat(), strike, option_type),
            ).fetchone()
        if row is None:
            raise LookupError(f"Exact option contract not found: NIFTY {expiry} {strike} {option_type}")
        return ResolvedOptionContract(
            instrument_id=int(row[0]), symbol=str(row[1]), underlying=str(row[2]),
            expiry_date=date.fromisoformat(row[3]), strike=int(row[4]), option_type=str(row[5]),
        )


__all__ = [
    "STRIKE_CHOICES", "StrikeLadderResolver", "atm_strike", "option_type_for",
    "strike_for_offset", "strike_ladder",
]
