"""The three indexes Kunal Quant trades, with their FYERS details.

Verified 2026-10-24 against the FYERS public symbol masters:
    NIFTY      NSE:NIFTY50-INDEX    options NSE_FO  strike gap 50   lot 65  weekly (Tue)
    BANKNIFTY  NSE:NIFTYBANK-INDEX  options NSE_FO  strike gap 100  lot 30  monthly only
    SENSEX     BSE:SENSEX-INDEX     options BSE_FO  strike gap 100  lot 20  weekly (Thu)
Lot sizes and expiries are NOT hard-coded: they are read from FYERS every day.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class IndexProfile:
    key: str              # NIFTY / BANKNIFTY / SENSEX
    label: str
    spot_symbol: str      # FYERS index symbol for live prices and history
    underlying: str       # 'underSym' in the FYERS symbol master
    master: str           # FYERS symbol master holding its options
    strike_step: int


INDEX_PROFILES: dict[str, IndexProfile] = {
    "NIFTY": IndexProfile("NIFTY", "NIFTY 50", "NSE:NIFTY50-INDEX", "NIFTY", "NSE_FO", 50),
    "BANKNIFTY": IndexProfile("BANKNIFTY", "BANK NIFTY", "NSE:NIFTYBANK-INDEX", "BANKNIFTY", "NSE_FO", 100),
    "SENSEX": IndexProfile("SENSEX", "SENSEX", "BSE:SENSEX-INDEX", "SENSEX", "BSE_FO", 100),
}


def get_profile(key: str) -> IndexProfile:
    try:
        return INDEX_PROFILES[key.strip().upper()]
    except KeyError:
        raise ValueError(f"Unknown index '{key}'. Choose from {', '.join(INDEX_PROFILES)}.") from None


def parse_index_list(text: str) -> list[IndexProfile]:
    profiles = [get_profile(part) for part in text.split(",") if part.strip()]
    if not profiles:
        raise ValueError("Choose at least one index.")
    return list({p.key: p for p in profiles}.values())


__all__ = ["INDEX_PROFILES", "IndexProfile", "get_profile", "parse_index_list"]
