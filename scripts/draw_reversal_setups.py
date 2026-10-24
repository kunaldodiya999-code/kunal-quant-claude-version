"""Draw the reversal setups sheet (docs/reversal_setups.png) for the Gap Reversal strategy.

Run from C:\\Users\\USER\\Desktop\\Kunal\\kunal-quant-claude-version :
    python scripts\\draw_reversal_setups.py          (writes docs\\reversal_setups.html; open it in a browser)

Each small chart: trend candles (grey), the setup candles (coloured), volume, the stop at the day's
extreme (red dashed) and the entry line (blue dashed, break of the reversal candle).
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

# (name, rule, setup candle indexes, candles [o, h, l, c, volume]) for SHORT setups at the top.
SHORT = [
    ("1. Shooting star / pin bar", "Upper wick >= 2x body, closes in lower third, at the day high",
     [5], [(100, 104, 99, 103, 40), (103, 108, 102, 107, 55), (107, 111, 106, 110, 60), (110, 114, 109, 113, 70),
           (113, 116, 112, 115, 65), (115, 124, 114, 116, 140), (116, 117, 111, 112, 90)]),
    ("2. Gravestone / doji at the top", "Body <= 10% of range at the high, next candle confirms down",
     [5, 6], [(100, 103, 99, 102, 40), (102, 106, 101, 105, 50), (105, 110, 104, 109, 65), (109, 113, 108, 112, 70),
              (112, 116, 111, 115, 80), (115, 121, 114, 115.3, 150), (115, 116, 109, 110, 100)]),
    ("3. Bearish engulfing", "Red body swallows the previous green body",
     [4, 5], [(100, 103, 99, 102, 40), (102, 106, 101, 105, 50), (105, 109, 104, 108, 55), (108, 112, 107, 111, 60),
              (111, 115, 110, 114, 70), (115, 116, 107, 108, 130), (108, 109, 104, 105, 80)]),
    ("4. Evening star", "Big green, small body at the top, big red closing below the middle",
     [3, 4, 5], [(100, 103, 99, 102, 40), (102, 106, 101, 105, 50), (105, 108, 104, 107, 55), (107, 115, 106, 114, 90),
                 (115, 118, 114, 115.5, 110), (115, 116, 107, 108, 120), (108, 109, 104, 105, 70)]),
    ("5. Dark cloud cover", "Opens above the green's high, closes below its middle",
     [4, 5], [(100, 103, 99, 102, 40), (102, 106, 101, 105, 50), (105, 109, 104, 108, 55), (108, 111, 107, 110, 60),
              (110, 116, 109, 115, 80), (117, 118, 111, 111.5, 120), (111, 112, 107, 108, 70)]),
    ("6. Tweezer top", "Two candles with the same high, the second red",
     [4, 5], [(100, 103, 99, 102, 40), (102, 106, 101, 105, 50), (105, 109, 104, 108, 55), (108, 112, 107, 111, 60),
              (111, 116, 110, 115, 85), (115, 116, 110, 111, 110), (111, 112, 107, 108, 70)]),
    ("7. Bearish harami (weaker)", "Small red inside the previous big green body",
     [4, 5], [(100, 103, 99, 102, 40), (102, 106, 101, 105, 50), (105, 109, 104, 108, 55), (108, 111, 107, 110, 60),
              (110, 118, 109, 117, 100), (116, 116.5, 113, 114, 70), (114, 115, 109, 110, 80)]),
    ("8. Failed breakout (bull trap)", "Makes a new day high, closes back below the old high",
     [5], [(100, 103, 99, 102, 40), (102, 109, 101, 108, 70), (108, 112, 107, 111, 75), (111, 113, 108, 109, 60),
           (109, 112, 108, 110.5, 55), (110.5, 117, 109, 110, 130), (110, 110.5, 105, 106, 90)]),
    ("9. Volume climax / absorption", "Biggest volume of the day, small progress up: buyers absorbed",
     [4, 5], [(100, 104, 99, 103, 50), (103, 108, 102, 107, 60), (107, 112, 106, 111, 70), (111, 115, 110, 114, 80),
              (114, 119, 113, 118, 120), (118, 120, 116, 117.5, 260), (117.5, 118, 112, 113, 110)]),
    ("10. Double top / lower high", "Second push fails below the first high, breaks the middle low",
     [3, 6], [(100, 104, 99, 103, 50), (103, 108, 102, 107, 60), (107, 113, 106, 112, 80), (112, 115, 111, 112.5, 90),
              (112, 113, 108, 109, 70), (109, 114, 108.5, 113, 65), (113, 114.5, 110, 110.5, 90), (110.5, 111, 106, 107, 80)]),
]


def mirror(candles):
    """Bullish version of a bearish setup: flip prices around 110."""
    return [(220 - o, 220 - l, 220 - h, 220 - c, v) for o, h, l, c, v in candles]


LONG_NAMES = {
    "1. Shooting star / pin bar": ("1. Hammer / pin bar", "Lower wick >= 2x body, closes in upper third, at the day low"),
    "2. Gravestone / doji at the top": ("2. Dragonfly / doji at the bottom", "Body <= 10% of range at the low, next candle confirms up"),
    "3. Bearish engulfing": ("3. Bullish engulfing", "Green body swallows the previous red body"),
    "4. Evening star": ("4. Morning star", "Big red, small body at the bottom, big green closing above the middle"),
    "5. Dark cloud cover": ("5. Piercing line", "Opens below the red's low, closes above its middle"),
    "6. Tweezer top": ("6. Tweezer bottom", "Two candles with the same low, the second green"),
    "7. Bearish harami (weaker)": ("7. Bullish harami (weaker)", "Small green inside the previous big red body"),
    "8. Failed breakout (bull trap)": ("8. Failed breakdown (bear trap)", "Makes a new day low, closes back above the old low"),
    "9. Volume climax / absorption": ("9. Selling climax / absorption", "Biggest volume of the day, small progress down: sellers absorbed"),
    "10. Double top / lower high": ("10. Double bottom / higher low", "Second push fails above the first low, breaks the middle high"),
}


def mini_chart(name, rule, setup, candles, short: bool) -> str:
    w, h, vol_h = 300, 210, 40
    pad_top, pad_bottom = 30, 22
    lows = [c[2] for c in candles]
    highs = [c[1] for c in candles]
    lo, hi = min(lows) - 1, max(highs) + 1
    plot_h = h - pad_top - pad_bottom - vol_h

    def y(p):
        return pad_top + (hi - p) / (hi - lo) * plot_h

    step = (w - 40) / len(candles)
    parts = [f'<rect x="0" y="0" width="{w}" height="{h}" rx="8" fill="#131722"/>',
             f'<text x="10" y="18" fill="#d1d4dc" font-size="13" font-weight="600">{name}</text>']
    vmax = max(c[4] for c in candles)
    # stop at the day's extreme and entry at the break of the reversal candle
    rev = candles[setup[-1]]
    stop = max(highs) if short else min(lows)
    entry = rev[2] if short else rev[1]
    for level, color, text, x_text, anchor in ((stop, "#ef5350", "SL: day high" if short else "SL: day low", w - 12, "end"),
                                               (entry, "#5b8cff", "entry: break", 12, "start")):
        parts.append(f'<line x1="10" x2="{w - 10}" y1="{y(level):.1f}" y2="{y(level):.1f}" stroke="{color}" '
                     f'stroke-width="1.2" stroke-dasharray="5 3"/>')
        dy = -3 if (level == stop) == short else 11
        parts.append(f'<text x="{x_text}" y="{y(level) + dy:.1f}" fill="{color}" font-size="10" '
                     f'text-anchor="{anchor}">{text}</text>')
    for i, (o, hh, ll, c, v) in enumerate(candles):
        x = 20 + i * step + step / 2
        in_setup = i in setup
        up = c >= o
        color = ("#26a69a" if up else "#ef5350") if in_setup else ("#4a5161" if up else "#3a3f4b")
        wick = "#e0e3eb" if in_setup else "#5d606b"
        parts.append(f'<line x1="{x:.1f}" x2="{x:.1f}" y1="{y(hh):.1f}" y2="{y(ll):.1f}" stroke="{wick}" stroke-width="1.4"/>')
        top, bot = y(max(o, c)), y(min(o, c))
        parts.append(f'<rect x="{x - step * 0.3:.1f}" y="{top:.1f}" width="{step * 0.6:.1f}" height="{max(1.5, bot - top):.1f}" '
                     f'fill="{color}" stroke="{"#ffffff" if in_setup else "none"}" stroke-width="0.6"/>')
        vh = v / vmax * (vol_h - 4)
        parts.append(f'<rect x="{x - step * 0.3:.1f}" y="{h - pad_bottom - vh:.1f}" width="{step * 0.6:.1f}" height="{vh:.1f}" '
                     f'fill="{"#f7c948" if in_setup else "#3a3f4b"}"/>')
    parts.append(f'<text x="10" y="{h - 7}" fill="#9598a1" font-size="10.5">{rule}</text>')
    return f'<svg width="{w}" height="{h}" xmlns="http://www.w3.org/2000/svg" font-family="Arial">{"".join(parts)}</svg>'


def build_html() -> str:
    shorts = "".join(mini_chart(n, r, s, c, True) for n, r, s, c in SHORT)
    longs = "".join(mini_chart(*LONG_NAMES[n], s, mirror(c), False) for n, r, s, c in SHORT)
    strength = ("Reversal strength % = rejection wick (25) + buyer absorption: volume vs. the day's average with little "
                "progress (30) + location: at the day's extreme and stretched from VWAP (20) + confirmation: next candle "
                "breaks the reversal candle (25). Gap >= 3% (setting). Window: first 10 candles of 5 min / 16 of 3 min.")
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>
body {{ margin: 0; background: #0b0e14; color: #d1d4dc; font-family: Arial; padding: 18px; width: 1600px; }}
h1 {{ font-size: 22px; margin: 4px 0 2px; }} h2 {{ font-size: 17px; margin: 18px 0 8px; }}
.grid {{ display: grid; grid-template-columns: repeat(5, 300px); gap: 14px; }}
.note {{ color: #9598a1; font-size: 13px; max-width: 1560px; line-height: 1.5; }}
.short {{ color: #ef5350; }} .long {{ color: #26a69a; }}
</style></head><body>
<h1>Kunal Quant - Gap Reversal: reversal setups (draft for your check)</h1>
<div class="note">{strength}<br>Grey = trend candles, coloured = the setup, yellow volume = setup volume.
Red dashed = stop at the day's high (short) / low (long). Blue dashed = entry when price breaks the reversal candle's
low (short) / high (long). Targets 1:1.5, 1:2, 1:2.5, 1:3 of that risk.</div>
<h2 class="short">SHORT setups (after a gap UP): buyers exhausted at the top</h2><div class="grid">{shorts}</div>
<h2 class="long">LONG setups (after a gap DOWN): sellers exhausted at the bottom</h2><div class="grid">{longs}</div>
<div class="note" style="margin-top:14px">Your examples: HCLTECH = volume climax + small doji at the top, then a bearish
engulfing (9 + 3). ADANIENT (1st) = shooting stars with long upper wicks at the high (1). ADANIENT (2nd) = small-body top
followed by big red candles (4, evening star type). SWIGGY = opening pin bar + doji with long upper wicks (1 + 2).</div>
</body></html>"""


def main() -> int:
    out = PROJECT_ROOT / "docs" / "reversal_setups.html"
    out.write_text(build_html(), encoding="utf-8")
    print(f"Saved: {out}  (open it in a browser)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
