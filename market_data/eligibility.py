from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class EligibleBar:
    timestamp: int
    open: float
    high: float
    low: float
    close: float
    volume: int | None
    open_interest: int | None
    resolution: str


def eligible_bars(bars: Iterable) -> list[EligibleBar]:
    """
    Return only complete derived bars.

    Incomplete derived bars remain in storage for audit/research but are
    never exposed through this signal-generation boundary.
    """
    result: list[EligibleBar] = []
    for bar in bars:
        if not bar.complete:
            continue
        result.append(
            EligibleBar(
                timestamp=bar.timestamp,
                open=bar.open,
                high=bar.high,
                low=bar.low,
                close=bar.close,
                volume=bar.volume,
                open_interest=bar.open_interest,
                resolution=bar.resolution,
            )
        )
    return result
