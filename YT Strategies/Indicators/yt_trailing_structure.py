"""Experimental YT-derived ATR structural trailing candidate.

Isolated research code. Not connected to production KunalQuant.
"""
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class TrailingUpdate:
    timestamp: object
    direction: str
    stop: float
    reference: float
    atr: float
    swing_index: int
    reason: str


class AtrStructureTrailing:
    """ATR-confirmed swing trailing stop.

    LONG: confirmed swing low minus ATR buffer.
    SHORT: confirmed swing high plus ATR buffer.

    A swing is confirmed only after a closed-bar reversal reaches
    swing_atr_mult * ATR. The stop only ratchets in the profitable direction.
    """

    def __init__(self, atr_period: int = 5, swing_atr_mult: float = 2.5,
                 stop_atr_buffer: float = 0.25):
        if atr_period < 2 or swing_atr_mult <= 0 or stop_atr_buffer < 0:
            raise ValueError("invalid trailing parameters")
        self.atr_period = atr_period
        self.swing_atr_mult = swing_atr_mult
        self.stop_atr_buffer = stop_atr_buffer
        self.reset()

    def reset(self) -> None:
        self._trs: list[float] = []
        self._prev_close: Optional[float] = None
        self._extreme: Optional[float] = None
        self._extreme_i: Optional[int] = None
        self._last_stop: Optional[float] = None
        self._n = 0

    def _atr(self) -> Optional[float]:
        if len(self._trs) < self.atr_period:
            return None
        return sum(self._trs[-self.atr_period:]) / self.atr_period

    def on_bar(self, timestamp, open_: float, high: float, low: float,
               close: float, direction: str) -> Optional[TrailingUpdate]:
        if direction not in {"LONG", "SHORT"}:
            raise ValueError("direction must be LONG or SHORT")

        tr = (high - low if self._prev_close is None else
              max(high - low, abs(high - self._prev_close),
                  abs(low - self._prev_close)))
        self._trs.append(float(tr))
        atr = self._atr()
        i = self._n
        self._n += 1
        self._prev_close = float(close)

        if atr is None:
            return None

        if direction == "LONG":
            if self._extreme is None or low < self._extreme:
                self._extreme, self._extreme_i = float(low), i

            if high - self._extreme >= self.swing_atr_mult * atr:
                candidate = self._extreme - self.stop_atr_buffer * atr
                if self._last_stop is not None and candidate <= self._last_stop:
                    update = None
                else:
                    self._last_stop = candidate
                    update = TrailingUpdate(
                        timestamp, direction, candidate, self._extreme,
                        atr, self._extreme_i, "confirmed_swing_low"
                    )
                self._extreme, self._extreme_i = float(high), i
                return update

        else:
            if self._extreme is None or high > self._extreme:
                self._extreme, self._extreme_i = float(high), i

            if self._extreme - low >= self.swing_atr_mult * atr:
                candidate = self._extreme + self.stop_atr_buffer * atr
                if self._last_stop is not None and candidate >= self._last_stop:
                    update = None
                else:
                    self._last_stop = candidate
                    update = TrailingUpdate(
                        timestamp, direction, candidate, self._extreme,
                        atr, self._extreme_i, "confirmed_swing_high"
                    )
                self._extreme, self._extreme_i = float(low), i
                return update

        return None
