"""Chart with drawing tools, shown inside a Streamlit page.

The chart library (TradingView Lightweight Charts 4.2.3, Apache-2.0) is stored in
dashboard/static/lightweight-charts, so nothing is downloaded at run time.
"""

from __future__ import annotations

import json
from pathlib import Path

STATIC = Path(__file__).resolve().parent / "static"
LIBRARY = STATIC / "lightweight-charts" / "lightweight-charts.standalone.production.js"
SCRIPT = STATIC / "drawing_chart.js"

# Toolbar: tool id, tooltip, SVG icon (24 x 24).
TOOLS = (
    ("cursor", "Cursor: move the chart, select and drag drawings",
     '<path d="M6 3l12 9-5 1 3 6-2 1-3-6-4 4z"/>'),
    ("trend", "Trend line", '<line x1="5" y1="19" x2="19" y2="5"/><circle cx="5" cy="19" r="2"/><circle cx="19" cy="5" r="2"/>'),
    ("hline", "Horizontal line", '<line x1="2" y1="12" x2="22" y2="12"/><circle cx="12" cy="12" r="2"/>'),
    ("vline", "Vertical line", '<line x1="12" y1="2" x2="12" y2="22"/><circle cx="12" cy="12" r="2"/>'),
    ("rect", "Rectangle", '<rect x="5" y="6" width="14" height="12"/>'),
    ("path", "Path (several connected lines)", '<polyline points="3,17 8,10 13,14 20,5"/>'),
    ("fib", "Fib retracement", '<line x1="3" y1="5" x2="21" y2="5"/><line x1="3" y1="10" x2="21" y2="10"/>'
     '<line x1="3" y1="14" x2="21" y2="14"/><line x1="3" y1="19" x2="21" y2="19"/>'),
)

CSS = """
html, body { margin: 0; padding: 0; background: #131722; color: #d1d4dc; font: 12px sans-serif; }
#box { display: flex; height: 100vh; }
#bar { width: 40px; background: #1e222d; display: flex; flex-direction: column; align-items: center; padding-top: 4px; gap: 2px; }
#bar button { width: 34px; height: 34px; border: 0; border-radius: 4px; background: transparent; cursor: pointer; padding: 5px; }
#bar button:hover { background: #2a2e39; }
#bar button.active { background: #2962ff; }
#bar button.armed { background: #b71c1c; }
#bar svg { width: 22px; height: 22px; stroke: #d1d4dc; fill: none; stroke-width: 1.6; }
#bar input[type=color] { width: 30px; height: 26px; border: 0; background: transparent; padding: 0; margin-top: 4px; }
#bar hr { width: 26px; border: 0; border-top: 1px solid #2a2e39; margin: 4px 0; }
#main { flex: 1; display: flex; flex-direction: column; min-width: 0; }
#chart { flex: 1; position: relative; }
#overlay { position: absolute; left: 0; top: 0; pointer-events: none; z-index: 3; }
#legend { position: absolute; left: 60px; top: 6px; z-index: 4; pointer-events: none; line-height: 1.5; }
#hint { height: 22px; line-height: 22px; padding: 0 8px; color: #9598a1; background: #1e222d; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
"""

DELETE_ICON = '<path d="M5 7h14M10 7V4h4v3M7 7l1 13h8l1-13"/>'
CLEAR_ICON = '<path d="M5 7h14M10 7V4h4v3M7 7l1 13h8l1-13M10 11v6M14 11v6"/>'


def _svg(body: str) -> str:
    return f'<svg viewBox="0 0 24 24">{body}</svg>'


def _js_value(value) -> str:
    return json.dumps(value).replace("</", "<\\/")


def chart_html(payload: dict, *, store_key: str, title: str) -> str:
    buttons = "".join(
        f'<button class="tool" data-tool="{tool}" title="{tip}">{_svg(icon)}</button>' for tool, tip, icon in TOOLS)
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>{CSS}</style></head><body>
<div id="box">
  <div id="bar">{buttons}<hr>
    <input id="color" type="color" value="#f7c948" title="Colour of the next drawing (or the selected one)">
    <button id="delete" title="Delete the selected drawing (or press Delete)">{_svg(DELETE_ICON)}</button>
    <button id="clear" title="Remove ALL drawings for this index (click twice)">{_svg(CLEAR_ICON)}</button>
  </div>
  <div id="main"><div id="chart"><canvas id="overlay"></canvas><div id="legend"></div></div><div id="hint"></div></div>
</div>
<script>{LIBRARY.read_text(encoding="utf-8")}</script>
<script>window.KQ_PAYLOAD = {_js_value(payload)}; window.KQ_STORE_KEY = {_js_value(store_key)};
window.KQ_TITLE = {_js_value(title)};</script>
<script>{SCRIPT.read_text(encoding="utf-8")}</script>
</body></html>"""


def show_chart(payload: dict, *, store_key: str, title: str, height: int = 640) -> None:
    import streamlit.components.v1 as components
    components.html(chart_html(payload, store_key=store_key, title=title), height=height, scrolling=False)


__all__ = ["TOOLS", "chart_html", "show_chart"]
