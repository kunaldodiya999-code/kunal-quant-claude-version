"""KTMI Uni Lite: lock, compact-layout equivalence, Pine parity, paper wiring."""

import hashlib
import random
import re
from dataclasses import dataclass, replace
from pathlib import Path

import pytest

from indicators.ktmi.universal import OHLCData
from indicators.ktmi_uni_lite import (
    UNI_LITE_CORE,
    UNI_LITE_DEFAULTS,
    calculate_uni_lite,
    parse_trigger,
)
from indicators.ktmi_uni_lite.config import LOCKED_PINE_FILE, LOCKED_PINE_SHA256
from indicators.ktmi_uni_lite.signals import pine_crossover, pine_crossunder
from paper_trading.engine import PaperEngineConfig, PaperStrategyId
from paper_trading.session import SIGNAL_PROFILES, PaperSessionConfig
from paper_trading.uni_lite_signals import evaluate_uni_lite_paper_signals

FOLDER = Path(__file__).resolve().parents[1] / "indicators" / "ktmi_uni_lite"
ORIGINAL = FOLDER / LOCKED_PINE_FILE
COMPACT = FOLDER / "KTMI_Uni_Lite_Compact.pine"


# --------------------------------------------------------------------------- lock

def test_locked_pine_source_is_unchanged():
    data = ORIGINAL.read_bytes().replace(b"\r\n", b"\n")  # Windows checkouts
    assert hashlib.sha256(data).hexdigest() == LOCKED_PINE_SHA256, (
        "KTMI_Uni_Lite_FINAL.pine changed. It is locked: restore it, or get the "
        "owner's approval and update LOCKED_PINE_SHA256 in the same commit."
    )


# ------------------------------------------------------------- compact == original

def _flat(path: Path) -> str:
    text = re.sub(r"//[^\n]*", "", path.read_text(encoding="utf-8"))
    text = re.sub(r"\s+", " ", text)
    return re.sub(r"([(\[]) | ([)\]])", r"\1\2", text)


def _surface(path: Path) -> dict[str, list]:
    """Everything a TradingView user can see or set, in declaration order."""
    text = _flat(path)
    return {
        "indicator": re.findall(r'indicator\( ?("[^)]*)\)', text),
        "inputs": re.findall(r'input\.(\w+)\( ?(color\.rgb\([^)]*\)|[^,]+?) ?, ?"([^"]+)"', text),
        "options": re.findall(r'options ?= ?\[([^\]]*)\]', text),
        "plots": re.findall(r'plot\( ?[^,]+?, ?"([^"]+)"', text),
        "hlines": re.findall(r'hline\( ?\w+, ?"([^"]+)"', text),
        "fills": re.findall(r'fill\((\w+), ?(\w+), ?color ?= ?.*?title ?= ?"([^"]+)"', text),
        "shapes": re.findall(r'plotshape\( ?\w+, ?title ?= ?"([^"]+)", ?style ?= ?([\w.]+), ?location ?= ?([\w.]+), ?color ?= ?(color\.rgb\([^)]*\))', text),
        "alerts": re.findall(r'alertcondition\( ?\w+, ?title ?= ?"([^"]+)", ?message ?= ?"([^"]+)"', text),
    }




def test_compact_layout_exposes_identical_settings_plots_and_alerts():
    original, compact = _surface(ORIGINAL), _surface(COMPACT)
    for key in ("indicator", "inputs", "options", "plots", "hlines", "fills", "shapes", "alerts"):
        assert original[key] == compact[key], key
    assert len(original["inputs"]) == 32
    assert len(original["fills"]) == 9
    assert len(original["alerts"]) == 6


def test_compact_layout_is_much_shorter():
    assert len(COMPACT.read_text().splitlines()) < len(ORIGINAL.read_text().splitlines()) / 4


# ------------------------------------------------------------------- Pine parity

def _pine_ema(values, length):
    """ta.ema: SMA seed over the first `length` valid values, then alpha=2/(n+1)."""
    out, seed, prev = [], [], None
    alpha = 2.0 / (length + 1)
    for v in values:
        if v is None:
            out.append(None)
            continue
        if prev is None:
            seed.append(v)
            if len(seed) == length:
                prev = sum(seed) / length
            out.append(prev)
            continue
        prev = alpha * v + (1 - alpha) * prev
        out.append(prev)
    return out


def _pine_trix(src, length):
    e3 = _pine_ema(_pine_ema(_pine_ema(src, length), length), length)
    return [
        None if i == 0 or e3[i] is None or e3[i - 1] in (None, 0.0) else 100.0 * (e3[i] - e3[i - 1]) / e3[i - 1]
        for i in range(len(e3))
    ]


def _pine_source(bar, name):
    return {
        "Close": bar.close, "Open": bar.open, "High": bar.high, "Low": bar.low,
        "HL2": (bar.high + bar.low) / 2, "HLC3": (bar.high + bar.low + bar.close) / 3,
        "OHLC4": (bar.open + bar.high + bar.low + bar.close) / 4,
    }[name]


def _pine_module(bars, module, invert):
    raw = _pine_trix([_pine_source(b, module.source) for b in bars], module.speed_length)
    if invert:
        raw = [None if v is None else -v for v in raw]
    signal = _pine_ema(raw, module.signal_length)
    return (
        [None if v is None else v * 100 for v in raw],
        [None if v is None else v * 100 for v in signal],
    )


def _walk(count=600, seed=11, vol=6.0):
    rng = random.Random(seed)
    price, bars = 25000.0, []
    for _ in range(count):
        o = price
        c = o + rng.gauss(0, vol)
        bars.append(OHLCData(o, max(o, c) + abs(rng.gauss(0, 2)), min(o, c) - abs(rng.gauss(0, 2)), c))
        price = c
    return bars


def test_lines_match_a_direct_transcription_of_the_pine_script():
    bars = _walk()
    result = calculate_uni_lite(bars, UNI_LITE_DEFAULTS)
    cfg = UNI_LITE_DEFAULTS
    for name, module, invert in (
        ("momentum", cfg.momentum, False),
        ("long", cfg.long_momentum, False),
        ("short", cfg.short_momentum, True),
    ):
        speed, signal = _pine_module(bars, module, invert)
        for i, row in enumerate(result):
            got_speed, got_signal = getattr(row, f"{name}_speed"), getattr(row, f"{name}_signal")
            assert (got_speed is None) == (speed[i] is None), (name, i)
            assert (got_signal is None) == (signal[i] is None), (name, i)
            if speed[i] is not None:
                assert got_speed == pytest.approx(speed[i], rel=1e-12, abs=1e-12)
            if signal[i] is not None:
                assert got_signal == pytest.approx(signal[i], rel=1e-12, abs=1e-12)


def test_arrows_match_the_pine_signal_engine():
    bars = _walk(seed=5, vol=9.0)
    rows = calculate_uni_lite(bars, UNI_LITE_DEFAULTS)
    fired = {"long_buy": 0, "short_buy": 0, "momentum_buy": 0, "momentum_sell": 0}
    for prev, row in zip(rows, rows[1:]):
        for name, line, trig, buy in (
            ("long_buy", "long", 0.5, True),
            ("short_buy", "short", 0.5, True),
            ("momentum_buy", "momentum", 0.5, True),
            ("momentum_sell", "momentum", -0.5, False),
        ):
            p, s, g = getattr(prev, f"{line}_speed"), getattr(row, f"{line}_speed"), getattr(row, f"{line}_signal")
            if None in (p, s, g):
                expected = False
            elif buy:
                expected = s > trig and p <= trig and s > g and s > 0
            else:
                expected = s < trig and p >= trig and s < g and s < 0
            assert getattr(row, name) == expected, (name,)
            fired[name] += expected
        assert not row.long_sell and not row.short_sell  # empty triggers = off
    assert all(count > 0 for count in fired.values()), fired  # the test really exercised arrows


def test_long_line_uses_high_like_uni_lite_not_close():
    bars = _walk(200)
    uni = calculate_uni_lite(bars, UNI_LITE_DEFAULTS)
    close_based = calculate_uni_lite(
        bars, replace(UNI_LITE_DEFAULTS, long_momentum=replace(UNI_LITE_DEFAULTS.long_momentum, source="Close"))
    )
    assert any(a.long_speed != b.long_speed for a, b in zip(uni, close_based) if a.long_speed is not None)


def test_crossover_matches_tradingview_at_the_trigger_level():
    assert pine_crossover(0.5, 0.51, 0.5)        # previous equal to trigger counts
    assert not pine_crossover(0.49, 0.5, 0.5)    # landing exactly on it does not
    assert pine_crossunder(-0.5, -0.51, -0.5)
    assert not pine_crossunder(-0.49, -0.5, -0.5)
    assert not pine_crossover(None, 1.0, 0.5)


def test_parse_trigger_follows_str_tonumber():
    assert parse_trigger("0.5") == 0.5
    assert parse_trigger("") is None
    assert parse_trigger("  ") is None
    assert parse_trigger("abc") is None


# ---------------------------------------------------------------- core profile

def test_core_profile_only_long_buy_and_short_buy_can_fire():
    rows = calculate_uni_lite(_walk(seed=5, vol=9.0), UNI_LITE_CORE)
    assert not any(r.momentum_buy or r.momentum_sell or r.long_sell or r.short_sell for r in rows)
    assert any(r.long_buy for r in rows) and any(r.short_buy for r in rows)


@dataclass(frozen=True)
class Bar:
    timestamp: int
    open: float
    high: float
    low: float
    close: float


def _bars():
    return [Bar(1_790_000_000 + 60 * i, b.open, b.high, b.low, b.close) for i, b in enumerate(_walk(seed=5, vol=9.0))]


def test_paper_evaluator_buys_ce_on_long_buy_and_pe_on_short_buy():
    bars = _bars()
    rows = calculate_uni_lite([OHLCData(b.open, b.high, b.low, b.close) for b in bars], UNI_LITE_CORE)
    long_i = next(i for i, r in enumerate(rows) if r.long_buy)
    short_i = next(i for i, r in enumerate(rows) if r.short_buy)

    signals = evaluate_uni_lite_paper_signals(bars[: long_i + 1])
    assert [(s.strategy_id, s.direction) for s in signals] == [(PaperStrategyId.STRATEGY_A, "LONG")]
    assert signals[0].timestamp == bars[long_i].timestamp
    assert signals[0].reason == "UNI_LITE_LONG_BUY_0.5"

    signals = evaluate_uni_lite_paper_signals(bars[: short_i + 1])
    assert [(s.strategy_id, s.direction) for s in signals] == [(PaperStrategyId.STRATEGY_A, "SHORT")]

    off = PaperEngineConfig(strategy_a_enabled=False)
    assert evaluate_uni_lite_paper_signals(bars[: long_i + 1], paper_config=off) == []


def test_paper_evaluator_is_silent_on_bars_without_an_arrow():
    bars = _bars()
    rows = calculate_uni_lite([OHLCData(b.open, b.high, b.low, b.close) for b in bars], UNI_LITE_CORE)
    quiet = next(i for i, r in enumerate(rows) if i > 50 and not (r.long_buy or r.short_buy))
    assert evaluate_uni_lite_paper_signals(bars[: quiet + 1]) == []


def test_session_defaults_to_core_profile_and_rejects_unknown_profiles():
    assert PaperSessionConfig(lot_size=65).signal_profile == "UNI_LITE_CORE"
    assert set(SIGNAL_PROFILES) == {"UNI_LITE_CORE", "UNI_LITE_DEFAULTS", "LEGACY_UNIVERSAL"}
    with pytest.raises(ValueError):
        PaperSessionConfig(lot_size=65, signal_profile="MAGIC")


# ------------------------------------------------------- FYERS Smart Script copy (owner 27 Oct 2026)

FYERS = FOLDER / "KTMI_Uni_Lite_FYERS_SmartScript.pine"


def test_fyers_smart_script_has_the_same_maths_and_signals_as_the_compact():
    """Only two allowed differences: no 'switch' in getSource, and the owner's trigger defaults."""
    fyers, compact = _flat(FYERS), _flat(COMPACT)
    assert "switch" not in fyers
    for part in ("ktmiModule(string src, int speedLen, int signalLen, bool invert) =>",
                 "e3 = ta.ema(ta.ema(ta.ema(getSource(src), speedLen), speedLen), speedLen)",
                 "100.0 * (e3 - e3[1]) / e3[1]", "raw := invert ? -raw : raw",
                 "buyCond(bool on, float trig, float spd, float sig) => on and not na(trig) and ta.crossover(spd, trig) "
                 "and spd > sig and spd > 0",
                 "longBuy = buyCond(longEnable, longBuyTrigger, longSpeed, longSignal)",
                 "shortBuy = buyCond(shortEnable, shortBuyTrigger, shortSpeed, shortSignal)"):
        assert re.sub(r"\s+", " ", part) in fyers and re.sub(r"\s+", " ", part) in compact, part
    f, c = _surface(FYERS), _surface(COMPACT)
    for key in ("indicator", "options", "plots", "hlines", "fills"):
        assert f[key] == c[key], key
    assert f["shapes"] == c["shapes"]                     # the 6 pane arrows unchanged
    price_arrows = re.findall(r'plotshape\(showPriceArrows and \w+, ?title ?= ?"([^"]+)", ?style ?= ?([\w.]+), '
                              r'?location ?= ?([\w.]+), ?color ?= ?(color\.rgb\([^)]*\))', fyers)
    assert price_arrows == [("BUY CALL on price", "shape.triangleup", "location.belowbar", "color.rgb(0, 200, 83)"),
                               ("BUY PUT on price", "shape.triangledown", "location.abovebar", "color.rgb(255, 23, 68)")]
    fyers_text = FYERS.read_text(encoding="utf-8")
    assert "showPriceArrows and longBuy" in fyers_text and "showPriceArrows and shortBuy" in fyers_text
    assert fyers_text.count("force_overlay=true") == 2
    assert f["alerts"][:6] == c["alerts"] and [a[0] for a in f["alerts"][6:]] == ["KTMI BUY CALL", "KTMI BUY PUT"]
    triggers = {name: default for kind, default, name in f["inputs"] if name.endswith("Trigger")}
    assert triggers == {"Momentum Buy Trigger": '""', "Momentum Sell Trigger": '""', "Long Buy Trigger": '"0.5"',
                        "Long Sell Trigger": '""', "Short Buy Trigger": '"0.5"', "Short Sell Trigger": '""'}
    assert [i for i in f["inputs"] if not i[2].endswith("Trigger")] == \
        [i for i in c["inputs"] if not i[2].endswith("Trigger")] + [("bool", "true", "Arrows on the price chart")]


def test_fyers_arrows_backup_uses_the_same_maths():
    arrows, compact = _flat(FOLDER / "KTMI_Uni_Lite_FYERS_Arrows.pine"), _flat(COMPACT)
    for part in ("e3 = ta.ema(ta.ema(ta.ema(", "100.0 * (e3 - e3[1]) / e3[1]", "raw := invert ? -raw : raw",
                 "[raw * DISPLAY_MULTIPLIER, ta.ema(raw, signalLen) * DISPLAY_MULTIPLIER]"):
        assert part in arrows and part in compact, part
    assert "ktmiModule(high, speedLength, signalLength, false)" in arrows        # Long = High source
    assert "ktmiModule(low, speedLength, signalLength, true)" in arrows          # Short = Low source, flipped
    assert "ta.crossover(longSpeed, longBuyTrigger) and longSpeed > longSignal and longSpeed > 0" in arrows
    assert "ta.crossover(shortSpeed, shortBuyTrigger) and shortSpeed > shortSignal and shortSpeed > 0" in arrows
    assert "overlay=true" in arrows and "location.belowbar" in arrows and "location.abovebar" in arrows
