"""TradingView-style chart inside a Streamlit page.

Files (all stored in the project, nothing is downloaded at run time):
  static/lightweight-charts/   TradingView Lightweight Charts 4.2.3 (Apache-2.0)
  static/kq_indicators.js      indicator maths (VWAP, Bollinger, volume profile, Smart Money Concepts)
  static/kq_chart.js           the chart: timeframes, signals, indicators, drawing tools
Live updates: the page saves fresh data to static/live/<name>.json and the chart fetches it
(needs server.enableStaticServing, set in .streamlit/config.toml).
"""

from __future__ import annotations

import json
from pathlib import Path

STATIC = Path(__file__).resolve().parent / "static"
LIBRARY = STATIC / "lightweight-charts" / "lightweight-charts.standalone.production.js"
SCRIPTS = (STATIC / "kq_indicators.js", STATIC / "kq_chart.js")
LIVE_DIR = STATIC / "live"

# Left toolbar: tool id, tooltip, SVG icon (24 x 24).
TOOLS = (
    ("cursor", "Cursor: move the chart, select and drag drawings", '<path d="M6 3l12 9-5 1 3 6-2 1-3-6-4 4z"/>'),
    ("hline", "Horizontal line", '<line x1="2" y1="12" x2="22" y2="12"/><circle cx="12" cy="12" r="2"/>'),
    ("vline", "Vertical line", '<line x1="12" y1="2" x2="12" y2="22"/><circle cx="12" cy="12" r="2"/>'),
    ("rect", "Rectangle", '<rect x="5" y="6" width="14" height="12"/>'),
    ("path", "Path (several connected lines)", '<polyline points="3,17 8,10 13,14 20,5"/>'),
    ("measure", "Measure (scale): points, %, bars and time between two points",
     '<path d="M4 20L20 4M7 17l2 2M10 14l2 2M13 11l2 2M16 8l2 2"/>'),
    ("vprofile", "Fixed range volume profile (POC, value area, high, low)",
     '<line x1="4" y1="3" x2="4" y2="21"/><line x1="4" y1="6" x2="11" y2="6"/><line x1="4" y1="10" x2="18" y2="10"/>'
     '<line x1="4" y1="14" x2="14" y2="14"/><line x1="4" y1="18" x2="8" y2="18"/>'),
)
GEAR_ICON = ('<circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3M4.9 4.9l2.1 2.1M17 17l2.1 2.1'
             'M4.9 19.1L7 17M17 7l2.1-2.1"/>')
DELETE_ICON = '<path d="M5 7h14M10 7V4h4v3M7 7l1 13h8l1-13"/>'
CLEAR_ICON = '<path d="M5 7h14M10 7V4h4v3M7 7l1 13h8l1-13M10 11v6M14 11v6"/>'

CSS = """
html, body { margin: 0; padding: 0; background: #131722; color: #d1d4dc; font: 12px -apple-system, 'Trebuchet MS', sans-serif; }
button { font: inherit; color: #d1d4dc; }
#box { display: flex; flex-direction: column; height: 100vh; }
#top { height: 36px; display: flex; align-items: center; gap: 2px; padding: 0 6px; background: #1e222d; border-bottom: 1px solid #2a2e39; position: relative; }
#top .sym { font-weight: 600; margin-right: 10px; }
#top .sep { width: 1px; height: 20px; background: #2a2e39; margin: 0 6px; }
#top button.tf, #top button.sig, #indbtn { background: transparent; border: 0; border-radius: 4px; padding: 5px 7px; cursor: pointer; }
#top button:hover { background: #2a2e39; }
#top button.active { color: #2962ff; font-weight: 600; }
#top button.sig.active[data-sig=Long] { color: #26a69a; } #top button.sig.active[data-sig=Short] { color: #ef5350; }
#live { margin-left: auto; color: #787b86; }
#indmenu { display: none; position: absolute; top: 36px; z-index: 20; background: #1e222d; border: 1px solid #2a2e39; border-radius: 4px; padding: 6px; min-width: 240px; }
#indmenu.open { display: block; }
.mi { display: flex; align-items: center; gap: 6px; padding: 5px 4px; cursor: pointer; }
.mi:hover { background: #2a2e39; }
.mi .lgb { margin-left: auto; }
#row { flex: 1; display: flex; min-height: 0; }
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
#legend { position: absolute; left: 8px; top: 6px; z-index: 4; pointer-events: none; line-height: 1.6; }
.lg { white-space: nowrap; display: table; background: rgba(19,23,34,0.72); padding: 0 4px; border-radius: 3px; } .dim { color: #787b86; }
.lgb { pointer-events: auto; background: transparent; border: 0; color: #787b86; cursor: pointer; padding: 0 3px; }
.lgb:hover { color: #d1d4dc; }
#hint { height: 22px; line-height: 22px; padding: 0 8px; color: #9598a1; background: #1e222d; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
#dialog { display: none; position: fixed; inset: 0; background: rgba(0,0,0,0.45); z-index: 50; align-items: center; justify-content: center; }
#dialog.open { display: flex; }
.dlg { background: #1e222d; border: 1px solid #2a2e39; border-radius: 6px; width: 380px; max-height: 88vh; display: flex; flex-direction: column; }
.dh { padding: 10px 14px; font-weight: 600; border-bottom: 1px solid #2a2e39; }
#dform { padding: 8px 14px; overflow-y: auto; }
.fr { display: flex; align-items: center; justify-content: space-between; gap: 10px; padding: 4px 0; }
.fr select, .fr input[type=number] { width: 140px; background: #131722; color: #d1d4dc; border: 1px solid #2a2e39; border-radius: 3px; padding: 3px; }
.db { display: flex; gap: 6px; padding: 10px 14px; border-top: 1px solid #2a2e39; }
.db button { background: #2a2e39; border: 0; border-radius: 4px; padding: 6px 12px; cursor: pointer; }
.db button.primary { background: #2962ff; color: #fff; }
"""


def _svg(body: str) -> str:
    return f'<svg viewBox="0 0 24 24">{body}</svg>'


def _js_value(value) -> str:
    return json.dumps(value, separators=(",", ":")).replace("</", "<\\/")


def chart_html(payload: dict, *, data_url: str | None = None) -> str:
    tools = "".join(f'<button class="tool" data-tool="{t}" title="{tip}">{_svg(icon)}</button>' for t, tip, icon in TOOLS)
    signals = "".join(f'<button class="sig" data-sig="{s}" title="Show {s.lower()} signals">{s}</button>'
                      for s in ("Both", "Long", "Short", "Off"))
    scripts = "".join(f"<script>{path.read_text(encoding='utf-8')}</script>" for path in SCRIPTS)
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>{CSS}</style></head><body>
<div id="box">
  <div id="top"><span class="sym">{payload.get("title", "")}</span><span id="tfs"></span><span class="sep"></span>
    <button id="indbtn" title="Add or remove indicators">ƒx Indicators</button><span class="sep"></span>
    <span class="dim">Signals&nbsp;</span>{signals}<span id="live">{"live" if data_url else ""}</span>
    <div id="indmenu"></div></div>
  <div id="row">
    <div id="bar">{tools}<hr>
      <input id="color" type="color" value="#f7c948" title="Colour of the next drawing (or the selected one)">
      <button id="gear" title="Settings of the selected volume profile">{_svg(GEAR_ICON)}</button>
      <button id="delete" title="Delete the selected drawing (or press Delete)">{_svg(DELETE_ICON)}</button>
      <button id="clear" title="Remove ALL drawings for this index (click twice)">{_svg(CLEAR_ICON)}</button>
    </div>
    <div id="main"><div id="chart"><canvas id="overlay"></canvas><div id="legend"></div></div><div id="hint"></div></div>
  </div>
</div>
<div id="dialog"></div>
<script>{LIBRARY.read_text(encoding="utf-8")}</script>
<script>window.KQ_PAYLOAD = {_js_value(payload)}; window.KQ_DATA_URL = {_js_value(data_url)};</script>
{scripts}
</body></html>"""


def write_live_data(name: str, payload: dict) -> str:
    """Save fresh data for a running chart; returns the URL the chart polls."""
    LIVE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = LIVE_DIR / f"{name}.tmp"
    tmp.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
    tmp.replace(LIVE_DIR / f"{name}.json")
    return f"app/static/live/{name}.json"


def show_chart(payload: dict, *, data_url: str | None = None, height: int = 720) -> None:
    import streamlit.components.v1 as components
    components.html(chart_html(payload, data_url=data_url), height=height, scrolling=False)


__all__ = ["TOOLS", "chart_html", "show_chart", "write_live_data"]
