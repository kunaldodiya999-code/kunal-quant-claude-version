// Kunal Quant chart: candles + KTMI Uni Lite + drawing tools.
// Inputs (set by dashboard/chart_component.py): window.KQ_PAYLOAD, window.KQ_STORE_KEY, window.KQ_TITLE.
// Drawings are saved in this browser (localStorage), per index, by time and price,
// so they stay put across refreshes and timeframes.
(function () {
  "use strict";
  const P = window.KQ_PAYLOAD;
  const KEY = window.KQ_STORE_KEY;
  const LW = window.LightweightCharts;
  const wrap = document.getElementById("chart");
  const overlay = document.getElementById("overlay");
  const ctx = overlay.getContext("2d");
  const hint = document.getElementById("hint");
  const legend = document.getElementById("legend");
  const colorInput = document.getElementById("color");

  const PRICE_AREA = 0.68;          // top 68% candles, bottom part KTMI Uni Lite
  const FIB_LEVELS = [0, 0.236, 0.382, 0.5, 0.618, 0.786, 1];
  const HINTS = {
    cursor: "Cursor: drag to move the chart. Click a drawing to select it, drag it or its dots to move. Delete key removes it.",
    trend: "Trend line: click the start point, then the end point.",
    hline: "Horizontal line: click once at the price.",
    vline: "Vertical line: click once at the time.",
    rect: "Rectangle: click one corner, then the opposite corner.",
    path: "Path: click each point. Click the last point again (or double-click, or press Enter) to finish. Esc cancels.",
    fib: "Fib retracement: click the swing start, then the swing end.",
  };

  // ------------------------------------------------------------------ chart
  const chart = LW.createChart(wrap, {
    autoSize: true,
    layout: { background: { type: "solid", color: "#131722" }, textColor: "#d1d4dc", fontSize: 12 },
    grid: { vertLines: { color: "#1e222d" }, horzLines: { color: "#1e222d" } },
    rightPriceScale: { borderColor: "#2a2e39", scaleMargins: { top: 0.04, bottom: 1 - PRICE_AREA + 0.03 } },
    leftPriceScale: { visible: false },
    timeScale: { borderColor: "#2a2e39", timeVisible: true, secondsVisible: false, rightOffset: 6 },
    crosshair: { mode: LW.CrosshairMode.Normal },
  });
  const candles = chart.addCandlestickSeries({
    upColor: "#26a69a", downColor: "#ef5350", borderVisible: false,
    wickUpColor: "#26a69a", wickDownColor: "#ef5350", priceScaleId: "right",
  });
  candles.setData(P.candles);
  candles.setMarkers(P.markers);

  const LINE_COLORS = {
    long_speed: "rgb(0,154,130)", long_signal: "rgb(56,180,91)",
    short_speed: "rgb(244,9,99)", short_signal: "rgb(244,48,72)",
    momentum_speed: "rgb(254,154,42)", momentum_signal: "rgb(249,239,84)",
  };
  const lineSeries = {};
  let levelSeries = null;
  for (const [name, data] of Object.entries(P.lines)) {
    const s = chart.addLineSeries({
      color: LINE_COLORS[name], lineWidth: name.endsWith("speed") ? 2 : 1, priceScaleId: "ktmi",
      priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false,
    });
    s.setData(data);
    lineSeries[name] = s;
    levelSeries = levelSeries || s;
  }
  // KTMI Uni Lite has its own (hidden) scale in the bottom part; its levels are labelled on the overlay.
  chart.priceScale("ktmi").applyOptions({ scaleMargins: { top: PRICE_AREA + 0.04, bottom: 0.03 } });
  if (levelSeries) {
    const L = P.levels, grey = "#787b86", purple = "rgb(112,48,160)";
    const lvl = (price, color, style, width) => levelSeries.createPriceLine(
      { price, color, lineStyle: style, lineWidth: width, axisLabelVisible: false, title: "" });
    lvl(L.center, grey, LW.LineStyle.Solid, 2);
    lvl(L.upper, grey, LW.LineStyle.Dashed, 1);
    lvl(L.lower, grey, LW.LineStyle.Dashed, 1);
    lvl(L.overbought, purple, LW.LineStyle.Solid, 1);
    lvl(L.oversold, purple, LW.LineStyle.Solid, 1);
  }

  // Keep the user's zoom across refreshes (measured from the newest bar).
  const N = P.candles.length;
  const VIEW_KEY = KEY + "_view";
  function store(key, value) { try { localStorage.setItem(key, JSON.stringify(value)); } catch (e) { /* private mode */ } }
  function fetchStored(key, fallback) {
    try { const v = localStorage.getItem(key); return v ? JSON.parse(v) : fallback; } catch (e) { return fallback; }
  }
  const view = fetchStored(VIEW_KEY, null);
  if (view && N) {
    chart.timeScale().setVisibleLogicalRange({ from: N - view.fromEnd, to: N - view.toEnd });
  } else if (N > 160) {
    chart.timeScale().setVisibleLogicalRange({ from: N - 150, to: N + 6 });
  } else {
    chart.timeScale().fitContent();
  }
  chart.timeScale().subscribeVisibleLogicalRangeChange((r) => {
    if (r && N) store(VIEW_KEY, { fromEnd: N - r.from, toEnd: N - r.to });
  });

  // ------------------------------------------------------------- legend
  const fmt = (v) => (v === undefined || v === null ? "-" : Number(v).toFixed(2));
  function showLegend(param) {
    const bar = param && param.seriesData ? param.seriesData.get(candles) : null;
    const last = bar || P.candles[N - 1];
    const k = (name) => {
      const s = lineSeries[name];
      const d = s && param && param.seriesData ? param.seriesData.get(s) : null;
      return fmt(d ? d.value : (P.lines[name] && P.lines[name].length ? P.lines[name][P.lines[name].length - 1].value : null));
    };
    legend.innerHTML = last
      ? `<b>${window.KQ_TITLE}</b> &nbsp; O ${fmt(last.open)} H ${fmt(last.high)} L ${fmt(last.low)} C ${fmt(last.close)}` +
        `<br><span style="color:${LINE_COLORS.long_speed}">Long ${k("long_speed")} / ${k("long_signal")}</span> &nbsp; ` +
        `<span style="color:${LINE_COLORS.short_speed}">Short ${k("short_speed")} / ${k("short_signal")}</span>`
      : `<b>${window.KQ_TITLE}</b> &nbsp; no candles yet`;
  }
  showLegend(null);

  // ------------------------------------------------- time <-> bar position
  const times = P.candles.map((c) => c.time);
  const BAR = P.bar_seconds || 60;
  function logicalToTime(l) {
    if (!N) return 0;
    if (l <= 0) return times[0] + l * BAR;
    if (l >= N - 1) return times[N - 1] + (l - (N - 1)) * BAR;
    const i = Math.floor(l);
    return times[i] + (l - i) * (times[i + 1] - times[i]);
  }
  function timeToLogical(t) {
    if (!N) return 0;
    if (t <= times[0]) return (t - times[0]) / BAR;
    if (t >= times[N - 1]) return N - 1 + (t - times[N - 1]) / BAR;
    let lo = 0, hi = N - 1;
    while (hi - lo > 1) { const m = (lo + hi) >> 1; if (times[m] <= t) lo = m; else hi = m; }
    return lo + (t - times[lo]) / (times[hi] - times[lo]);
  }
  const paneLeft = () => chart.priceScale("left").width();
  function toXY(pt) {
    const x = chart.timeScale().logicalToCoordinate(timeToLogical(pt.t));
    const y = candles.priceToCoordinate(pt.p);
    return x === null || y === null ? null : { x, y };
  }
  function fromXY(x, y) {      // x, y inside the pane (left scale excluded)
    const l = chart.timeScale().coordinateToLogical(x);
    const p = candles.coordinateToPrice(y);
    return l === null || p === null ? null : { t: logicalToTime(l), p: Math.round(p * 100) / 100 };
  }
  function paneXY(e) {
    const r = wrap.getBoundingClientRect();
    return { x: e.clientX - r.left - paneLeft(), y: e.clientY - r.top };
  }

  // ------------------------------------------------------------- drawings
  let drawings = fetchStored(KEY, []);
  let tool = "cursor";
  let pending = null;        // drawing being placed
  let hover = null;          // mouse point for the preview
  let selected = null;       // id of the selected drawing
  let drag = null;
  const save = () => store(KEY, drawings);
  const newId = () => Date.now().toString(36) + Math.random().toString(36).slice(2, 6);

  function setTool(name) {
    tool = name;
    pending = null;
    document.querySelectorAll(".tool").forEach((b) => b.classList.toggle("active", b.dataset.tool === name));
    hint.textContent = HINTS[name];
    // While a drawing tool is on, a mouse drag must not pan the chart.
    chart.applyOptions({ handleScroll: name === "cursor" ? true : { mouseWheel: true, pressedMouseMove: false,
                                                                      horzTouchDrag: false, vertTouchDrag: false } });
  }
  const POINTS_NEEDED = { trend: 2, rect: 2, fib: 2, hline: 1, vline: 1 };

  function finish() {
    if (pending && pending.pts.length >= (pending.type === "path" ? 2 : POINTS_NEEDED[pending.type])) {
      drawings.push(pending);
      selected = pending.id;
      save();
    }
    setTool("cursor");
  }

  // Clicks are detected here (press + release without moving), not with the chart's
  // own click event, which drops a second click that follows quickly.
  let press = null;
  function place(x, y) {
    const pt = fromXY(x, y);
    if (!pt) return;
    if (!pending) pending = { id: newId(), type: tool, pts: [], color: colorInput.value };
    if (tool === "path" && pending.pts.length >= 2) {
      const last = toXY(pending.pts[pending.pts.length - 1]);
      if (last && Math.hypot(last.x - x, last.y - y) < 8) { finish(); return; }
    }
    pending.pts.push(pt);
    if (tool !== "path" && pending.pts.length >= POINTS_NEEDED[tool]) finish();
  }
  wrap.addEventListener("pointerdown", (e) => {
    if (tool === "cursor") return;
    press = paneXY(e);
    e.preventDefault();
  }, true);
  wrap.addEventListener("pointerup", (e) => {
    if (tool === "cursor" || !press) return;
    const up = paneXY(e);
    if (Math.hypot(up.x - press.x, up.y - press.y) < 6 && up.x >= 0) place(up.x, up.y);
    press = null;
  }, true);
  chart.subscribeCrosshairMove((param) => {
    hover = param.point || null;
    showLegend(param);
  });

  // ---- hit testing (pixels)
  function segDist(px, py, a, b) {
    const dx = b.x - a.x, dy = b.y - a.y, len = dx * dx + dy * dy;
    const u = len ? Math.max(0, Math.min(1, ((px - a.x) * dx + (py - a.y) * dy) / len)) : 0;
    return Math.hypot(px - (a.x + u * dx), py - (a.y + u * dy));
  }
  function fibPrice(d, level) { return d.pts[1].p + (d.pts[0].p - d.pts[1].p) * level; }
  function hitDistance(d, x, y) {
    const xy = d.pts.map(toXY);
    if (xy.some((v) => v === null)) return Infinity;
    switch (d.type) {
      case "hline": return Math.abs(y - xy[0].y);
      case "vline": return Math.abs(x - xy[0].x);
      case "trend": return segDist(x, y, xy[0], xy[1]);
      case "path": {
        let best = Infinity;
        for (let i = 1; i < xy.length; i++) best = Math.min(best, segDist(x, y, xy[i - 1], xy[i]));
        return best;
      }
      case "rect": {
        const [a, b] = xy;
        const inside = x >= Math.min(a.x, b.x) && x <= Math.max(a.x, b.x) && y >= Math.min(a.y, b.y) && y <= Math.max(a.y, b.y);
        return inside ? 0 : Infinity;
      }
      case "fib": {
        const x0 = Math.min(xy[0].x, xy[1].x), x1 = Math.max(xy[0].x, xy[1].x);
        let best = segDist(x, y, xy[0], xy[1]);
        for (const lv of FIB_LEVELS) {
          const ly = candles.priceToCoordinate(fibPrice(d, lv));
          if (ly !== null) best = Math.min(best, segDist(x, y, { x: x0, y: ly }, { x: x1, y: ly }));
        }
        return best;
      }
    }
    return Infinity;
  }
  function hitDrawing(x, y) {
    let best = null, bestD = 7;
    for (const d of drawings) { const dist = hitDistance(d, x, y); if (dist <= bestD) { best = d; bestD = dist; } }
    return best;
  }
  function hitHandle(x, y) {
    const d = drawings.find((v) => v.id === selected);
    if (!d) return null;
    for (let i = 0; i < d.pts.length; i++) {
      const p = toXY(d.pts[i]);
      if (p && Math.hypot(p.x - x, p.y - y) <= 8) return { d, i };
    }
    return null;
  }

  // ---- select and drag in cursor mode (runs before the chart sees the press)
  wrap.addEventListener("pointerdown", (e) => {
    if (tool !== "cursor") return;
    const { x, y } = paneXY(e);
    const handle = hitHandle(x, y);
    const d = handle ? handle.d : hitDrawing(x, y);
    if (!d) { selected = null; return; }
    selected = d.id;
    const l0 = chart.timeScale().coordinateToLogical(x), p0 = candles.coordinateToPrice(y);
    drag = { d, index: handle && d.type !== "hline" && d.type !== "vline" ? handle.i : null,
             l0, p0, orig: d.pts.map((p) => ({ ...p })) };
    chart.applyOptions({ handleScroll: false, handleScale: false });
    e.preventDefault();
    e.stopPropagation();
  }, true);
  window.addEventListener("pointermove", (e) => {
    if (!drag) return;
    const { x, y } = paneXY(e);
    if (drag.index !== null) {
      const pt = fromXY(x, y);
      if (pt) drag.d.pts[drag.index] = pt;
      return;
    }
    const l = chart.timeScale().coordinateToLogical(x), p = candles.coordinateToPrice(y);
    if (l === null || p === null || drag.l0 === null || drag.p0 === null) return;
    drag.d.pts = drag.orig.map((o) => ({ t: logicalToTime(timeToLogical(o.t) + (l - drag.l0)),
                                         p: Math.round((o.p + (p - drag.p0)) * 100) / 100 }));
  });
  window.addEventListener("pointerup", () => {
    if (!drag) return;
    drag = null;
    chart.applyOptions({ handleScroll: true, handleScale: true });
    save();
  });

  // ---- keyboard
  document.addEventListener("keydown", (e) => {
    if ((e.key === "Delete" || e.key === "Backspace") && selected) {
      drawings = drawings.filter((d) => d.id !== selected);
      selected = null;
      save();
    } else if (e.key === "Escape") {
      pending = null;
      setTool("cursor");
    } else if (e.key === "Enter" && pending && pending.type === "path") {
      finish();
    }
  });

  // ---- toolbar
  document.querySelectorAll(".tool").forEach((b) => b.addEventListener("click", () => setTool(b.dataset.tool)));
  document.getElementById("delete").addEventListener("click", () => {
    if (!selected) { hint.textContent = "Select a drawing first (cursor tool, click on it)."; return; }
    drawings = drawings.filter((d) => d.id !== selected);
    selected = null;
    save();
  });
  const clearBtn = document.getElementById("clear");
  let clearArmed = 0;
  clearBtn.addEventListener("click", () => {
    if (Date.now() - clearArmed < 3000) {
      drawings = [];
      selected = null;
      save();
      clearArmed = 0;
      clearBtn.classList.remove("armed");
      hint.textContent = "All drawings removed for this index.";
      return;
    }
    clearArmed = Date.now();
    clearBtn.classList.add("armed");
    hint.textContent = "Click the bin again within 3 seconds to remove ALL drawings for this index.";
    setTimeout(() => clearBtn.classList.remove("armed"), 3000);
  });
  colorInput.addEventListener("input", () => {
    const d = drawings.find((v) => v.id === selected);
    if (d) { d.color = colorInput.value; save(); }
  });

  // ------------------------------------------------------------- painting
  function alpha(hex, a) {
    const n = parseInt(hex.slice(1), 16);
    return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${a})`;
  }
  function label(text, x, y, color, align) {
    ctx.font = "11px sans-serif";
    const w = ctx.measureText(text).width + 8;
    const bx = align === "right" ? x - w : x;
    ctx.fillStyle = color;
    ctx.fillRect(bx, y - 8, w, 16);
    ctx.fillStyle = "#ffffff";
    ctx.fillText(text, bx + 4, y + 4);
  }
  function paint(d, isSelected, preview) {
    const pts = d.pts.slice();
    if (preview && hover && tool !== "cursor") {
      const h = fromXY(hover.x, hover.y);
      if (h) pts.push(h);
    }
    const xy = pts.map(toXY).filter((v) => v !== null);
    if (!xy.length) return;
    const W = overlay.width / devicePixelRatio - paneLeft(), H = overlay.height / devicePixelRatio;
    ctx.strokeStyle = d.color;
    ctx.lineWidth = isSelected ? 2.5 : 1.6;
    ctx.setLineDash([]);
    ctx.beginPath();
    switch (d.type) {
      case "hline":
        ctx.moveTo(0, xy[0].y); ctx.lineTo(W, xy[0].y); ctx.stroke();
        label(pts[0].p.toFixed(2), W - 2, xy[0].y, d.color, "right");
        break;
      case "vline":
        ctx.moveTo(xy[0].x, 0); ctx.lineTo(xy[0].x, H); ctx.stroke();
        break;
      case "trend":
      case "path":
        xy.forEach((p, i) => (i ? ctx.lineTo(p.x, p.y) : ctx.moveTo(p.x, p.y)));
        ctx.stroke();
        break;
      case "rect":
        if (xy.length < 2) break;
        ctx.fillStyle = alpha(d.color, 0.15);
        ctx.fillRect(Math.min(xy[0].x, xy[1].x), Math.min(xy[0].y, xy[1].y),
                     Math.abs(xy[1].x - xy[0].x), Math.abs(xy[1].y - xy[0].y));
        ctx.strokeRect(Math.min(xy[0].x, xy[1].x), Math.min(xy[0].y, xy[1].y),
                       Math.abs(xy[1].x - xy[0].x), Math.abs(xy[1].y - xy[0].y));
        break;
      case "fib": {
        if (xy.length < 2) break;
        const x0 = Math.min(xy[0].x, xy[1].x), x1 = Math.max(xy[0].x, xy[1].x);
        ctx.setLineDash([4, 4]);
        ctx.moveTo(xy[0].x, xy[0].y); ctx.lineTo(xy[1].x, xy[1].y); ctx.stroke();
        ctx.setLineDash([]);
        const f = { pts: pts };
        for (const lv of FIB_LEVELS) {
          const price = fibPrice(f, lv), y = candles.priceToCoordinate(price);
          if (y === null) continue;
          ctx.beginPath(); ctx.moveTo(x0, y); ctx.lineTo(x1, y); ctx.stroke();
          ctx.font = "11px sans-serif";
          ctx.fillStyle = d.color;
          ctx.fillText(`${lv} (${price.toFixed(2)})`, x0 + 3, y - 3);
        }
        break;
      }
    }
    if (isSelected || preview) {
      ctx.fillStyle = "#ffffff";
      xy.forEach((p) => { ctx.beginPath(); ctx.arc(p.x, p.y, 4, 0, Math.PI * 2); ctx.fill(); });
    }
  }
  function frame() {
    const dpr = window.devicePixelRatio || 1;
    const w = wrap.clientWidth, h = wrap.clientHeight;
    if (overlay.width !== Math.round(w * dpr) || overlay.height !== Math.round(h * dpr)) {
      overlay.width = Math.round(w * dpr); overlay.height = Math.round(h * dpr);
      overlay.style.width = w + "px"; overlay.style.height = h + "px";
    }
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);
    const left = paneLeft(), right = chart.priceScale("right").width(), bottom = chart.timeScale().height();
    // divider between candles and KTMI
    ctx.strokeStyle = "#2a2e39"; ctx.lineWidth = 1; ctx.setLineDash([]);
    ctx.beginPath(); ctx.moveTo(left, (h - bottom) * PRICE_AREA); ctx.lineTo(w - right, (h - bottom) * PRICE_AREA); ctx.stroke();
    if (levelSeries) {
      ctx.font = "10px sans-serif";
      // +0.5 is the trigger (0 and -0.5 sit too close to label them all)
      for (const [v, color] of [[P.levels.overbought, "rgb(112,48,160)"], [P.levels.upper, "#5d606b"],
                                [P.levels.oversold, "rgb(112,48,160)"]]) {
        const y = levelSeries.priceToCoordinate(v);
        if (y === null) continue;
        const text = (v > 0 ? "+" : "") + v.toFixed(1);
        ctx.fillStyle = color; ctx.fillRect(w - right - 34, y - 7, 32, 14);
        ctx.fillStyle = "#ffffff"; ctx.fillText(text, w - right - 30, y + 4);
      }
      ctx.fillStyle = "#9598a1"; ctx.font = "11px sans-serif";
      ctx.fillText("KTMI Uni Lite", left + 6, (h - bottom) * PRICE_AREA + 14);
    }
    ctx.save();
    ctx.beginPath(); ctx.rect(left, 0, w - left - right, h - bottom); ctx.clip();
    ctx.translate(left, 0);
    for (const d of drawings) paint(d, d.id === selected, false);
    if (pending) paint(pending, false, true);
    ctx.restore();
    requestAnimationFrame(frame);
  }
  setTool("cursor");
  requestAnimationFrame(frame);
  window.KQ_CHART = { chart, drawings: () => drawings, setTool };   // for checks
})();
