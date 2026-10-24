"""KTMI Uni Lite signal evaluator for the paper engine.

Drop-in alternative to ``evaluate_latest_paper_signals`` (same call shape,
same ``PaperSignal`` output), driven by the locked Uni Lite indicator instead
of the KTMI Universal defaults.

Arrow -> paper strategy mapping (options buying only):
    Long Momentum Buy   -> STRATEGY_A LONG  -> BUY CE
    Short Momentum Buy  -> STRATEGY_A SHORT -> BUY PE
    Momentum Buy        -> STRATEGY_B LONG  -> BUY CE
    Momentum Sell       -> STRATEGY_B SHORT -> BUY PE
Long/Short Momentum Sell arrows have no trade meaning yet and never trade.

With ``UNI_LITE_CORE`` only the first two can fire.
"""

from __future__ import annotations

from typing import Callable, Sequence

from indicators.ktmi.universal import OHLCData
from indicators.ktmi_uni_lite import UNI_LITE_CORE, UniLiteBar, UniLiteConfig, calculate_uni_lite
from paper_trading.engine import PaperEngineConfig, PaperStrategyId
from paper_trading.signals import PaperSignal, _timestamp, _to_ohlc


def _fmt(value) -> str:
    return f"{value:g}"


def evaluate_uni_lite_paper_signals(
    bars: Sequence[object],
    *,
    paper_config: PaperEngineConfig | None = None,
    uni_lite_config: UniLiteConfig = UNI_LITE_CORE,
    bar_sink: Callable[[object, UniLiteBar], None] | None = None,
) -> list[PaperSignal]:
    """Signals on the latest completed bar only (full history keeps warm-up).

    ``bar_sink`` receives (latest bar, its Uni Lite values) for every closed bar,
    arrow or not, so the values can be journaled and compared with TradingView.
    """
    if len(bars) < 2:
        return []
    paper_config = paper_config or PaperEngineConfig()
    ohlc: list[OHLCData] = _to_ohlc(bars)
    latest = calculate_uni_lite(ohlc, uni_lite_config)[-1]
    if bar_sink is not None:
        bar_sink(bars[-1], latest)
    index = len(bars) - 1
    timestamp = _timestamp(bars[-1])
    c = uni_lite_config

    candidates = [
        (latest.long_buy, PaperStrategyId.STRATEGY_A, "LONG", f"UNI_LITE_LONG_BUY_{_fmt(c.long_buy_trigger or 0)}"),
        (latest.short_buy, PaperStrategyId.STRATEGY_A, "SHORT", f"UNI_LITE_SHORT_BUY_{_fmt(c.short_buy_trigger or 0)}"),
        (latest.momentum_buy, PaperStrategyId.STRATEGY_B, "LONG", f"UNI_LITE_MOMENTUM_BUY_{_fmt(c.momentum_buy_trigger or 0)}"),
        (latest.momentum_sell, PaperStrategyId.STRATEGY_B, "SHORT", f"UNI_LITE_MOMENTUM_SELL_{_fmt(c.momentum_sell_trigger or 0)}"),
    ]
    return [
        PaperSignal(strategy_id=sid, direction=direction, timestamp=timestamp, index=index, reason=reason)
        for fired, sid, direction, reason in candidates
        if fired and paper_config.is_enabled(sid)
    ]


__all__ = ["evaluate_uni_lite_paper_signals"]
