"""The chart on the terminal page (TradingView look, TradingView Lightweight Charts 4.2.3, Apache-2.0, in static/).

Three panes on one time axis:  price candles + VWAP + KTMI arrows + trade marks  |  BBP_NM (bull / bear columns,
Direction line green above 0, red below)  |  KTMI Uni Lite (Long Speed, Short Speed, trigger +0.5).
The engine writes static/live/chart.json every pass; the chart fetches it every 2 seconds (no page reload).
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LIBRARY = ROOT / "static" / "lightweight-charts" / "lightweight-charts.standalone.production.js"
DATA_URL = "app/static/live/chart.json"

PAGE = """<!doctype html><html><head><meta charset="utf-8"><style>
html, body { margin: 0; padding: 0; background: #131722; color: #d1d4dc;
  font: 12px -apple-system, 'Trebuchet MS', Roboto, sans-serif; overflow: hidden; }
#box { display: flex; flex-direction: column; height: 100vh; }
.pane { position: relative; border-bottom: 1px solid #2a2e39; }
#p1 { flex: 58; } #p2 { flex: 22; } #p3 { flex: 20; }
.lg { position: absolute; left: 8px; top: 4px; z-index: 5; pointer-events: none; white-space: nowrap;
  background: rgba(19,23,34,0.7); padding: 1px 4px; border-radius: 3px; }
.dim { color: #787b86; } .g { color: #26a69a; } .r { color: #ef5350; } .b { color: #2962ff; } .o { color: #ff9800; }
#wait { position: absolute; inset: 0; display: flex; align-items: center; justify-content: center; color: #787b86;
  font-size: 14px; z-index: 9; background: #131722; }
</style></head><body>
<div id="box"><div class="pane" id="p1"><div class="lg" id="l1"></div></div>
<div class="pane" id="p2"><div class="lg" id="l2"></div></div>
<div class="pane" id="p3"><div class="lg" id="l3"></div></div></div>
<div id="wait">Waiting for the first candles from FYERS...</div>
<script>__LIBRARY__</script>
<script>
const LWC = LightweightCharts, URL_ = "__DATA_URL__";
const base = { layout: { background: { color: "#131722" }, textColor: "#d1d4dc" },
  grid: { vertLines: { color: "#1e222d" }, horzLines: { color: "#1e222d" } },
  rightPriceScale: { borderColor: "#2a2e39", minimumWidth: 80 }, crosshair: { mode: 0 },
  timeScale: { borderColor: "#2a2e39", timeVisible: true, secondsVisible: false, rightOffset: 6 } };
function mk(id, showTime) {
  const el = document.getElementById(id);
  const c = LWC.createChart(el, Object.assign({}, base, { autoSize: true,
    timeScale: Object.assign({}, base.timeScale, { visible: showTime }) }));
  return c;
}
const c1 = mk("p1", false), c2 = mk("p2", false), c3 = mk("p3", true);
const candles = c1.addCandlestickSeries({ upColor: "#26a69a", downColor: "#ef5350", borderVisible: false,
  wickUpColor: "#26a69a", wickDownColor: "#ef5350" });
const vwap = c1.addLineSeries({ color: "#2962ff", lineWidth: 2, priceLineVisible: false, lastValueVisible: false,
  crosshairMarkerVisible: false });
const bull = c2.addHistogramSeries({ color: "rgba(38,166,154,0.55)", priceLineVisible: false, lastValueVisible: false });
const bear = c2.addHistogramSeries({ color: "rgba(239,83,80,0.55)", priceLineVisible: false, lastValueVisible: false });
const dir = c2.addBaselineSeries({ baseValue: { type: "price", price: 0 }, lineWidth: 2,
  topLineColor: "#26a69a", bottomLineColor: "#ef5350",
  topFillColor1: "rgba(0,0,0,0)", topFillColor2: "rgba(0,0,0,0)",
  bottomFillColor1: "rgba(0,0,0,0)", bottomFillColor2: "rgba(0,0,0,0)", priceLineVisible: false });
dir.createPriceLine({ price: 0, color: "#787b86", lineWidth: 1, lineStyle: 2, axisLabelVisible: false });
const kl = c3.addLineSeries({ color: "#26a69a", lineWidth: 2, priceLineVisible: false });
const ks = c3.addLineSeries({ color: "#ef5350", lineWidth: 2, priceLineVisible: false });
kl.createPriceLine({ price: 0.5, color: "#787b86", lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: "" });
kl.createPriceLine({ price: 0, color: "#434651", lineWidth: 1, lineStyle: 3, axisLabelVisible: false });

// every pane gets every candle time (invisible), so the three panes line up bar for bar
const pad = { lineVisible: false, lastValueVisible: false, priceLineVisible: false, crosshairMarkerVisible: false };
const w2 = c2.addLineSeries(pad), w3 = c3.addLineSeries(pad);
// one time axis for the three panes
const charts = [c1, c2, c3]; let syncing = false;
charts.forEach(src => src.timeScale().subscribeVisibleLogicalRangeChange(r => {
  if (syncing || !r) return; syncing = true;
  charts.forEach(dst => { if (dst !== src) dst.timeScale().setVisibleLogicalRange(r); }); syncing = false; }));

let D = null, key = "", fitted = false;
const f = (v, n) => (v === undefined || v === null) ? "-" : Number(v).toFixed(n);
function at(list, t) { if (!list) return undefined; for (let i = list.length - 1; i >= 0; i--) {
  if (list[i].time === t) return list[i].value; if (list[i].time < t) break; } return undefined; }
function legend(t) {
  if (!D || !D.candles.length) return;
  const c = (t && D.candles.find(x => x.time === t)) || D.candles[D.candles.length - 1]; t = c.time;
  document.getElementById("l1").innerHTML = `<b>${D.index}</b> · ${D.timeframe}m &nbsp;` +
    `<span class="dim">O</span> ${f(c.open, 2)} <span class="dim">H</span> ${f(c.high, 2)} ` +
    `<span class="dim">L</span> ${f(c.low, 2)} <span class="dim">C</span> ${f(c.close, 2)} &nbsp;` +
    `<span class="b">VWAP ${f(at(D.vwap, t), 2)}</span> <span class="dim">· updated ${D.updated}</span>`;
  const d = at(D.direction, t);
  document.getElementById("l2").innerHTML = `BBP_NM 10 &nbsp;<span class="g">Bull ${f(at(D.bull, t), 2)}</span> ` +
    `<span class="r">Bear ${f(at(D.bear, t), 2)}</span> ` +
    `<span class="${d >= 0 ? "g" : "r"}">Direction ${f(d, 2)}</span>`;
  document.getElementById("l3").innerHTML = `KTMI Uni Lite &nbsp;<span class="g">Long ${f(at(D.ktmi_long, t), 3)}</span> ` +
    `<span class="r">Short ${f(at(D.ktmi_short, t), 3)}</span> <span class="dim">trigger 0.5</span>`;
}
c1.subscribeCrosshairMove(p => legend(p && p.time));
function load() {
  fetch(URL_ + "?t=" + Date.now(), { cache: "no-store" }).then(r => r.ok ? r.json() : null).then(d => {
    if (!d || !d.candles || !d.candles.length) return;
    D = d; document.getElementById("wait").style.display = "none";
    const k = d.index + d.timeframe;
    const times = d.candles.map(c => ({ time: c.time }));
    w2.setData(times); w3.setData(times);
    candles.setData(d.candles); vwap.setData(d.vwap);
    bull.setData(d.bull); bear.setData(d.bear); dir.setData(d.direction);
    kl.setData(d.ktmi_long); ks.setData(d.ktmi_short);
    candles.setMarkers(d.markers || []);
    if (k !== key) { key = k; fitted = false; }
    if (!fitted) { fitted = true; const n = d.candles.length;
      c1.timeScale().setVisibleLogicalRange({ from: Math.max(0, n - 120), to: n + 6 }); }
    legend();
  }).catch(() => {});
}
load(); setInterval(load, 2000);
</script></body></html>"""


def chart_html() -> str:
    return PAGE.replace("__LIBRARY__", LIBRARY.read_text(encoding="utf-8")).replace("__DATA_URL__", DATA_URL)


__all__ = ["DATA_URL", "chart_html"]
