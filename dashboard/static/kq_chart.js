// Kunal Quant chart (TradingView style): candles + futures volume + KTMI Uni Lite,
// timeframe buttons, signal filter, indicators (VWAP, Bollinger Bands, OI profile,
// Smart Money Concepts) and drawing tools (horizontal, vertical, rectangle, path,
// measure, fixed range volume profile).
// Inputs set by dashboard/chart_component.py: window.KQ_PAYLOAD, window.KQ_DATA_URL (live updates).
// Everything the owner chooses (timeframe, indicators, settings, drawings) is saved in
// this browser per index. The chart only shows; it never places a trade.
(function () {
  "use strict";
  let P = window.KQ_PAYLOAD;
  const LW = window.LightweightCharts;
  const K = window.KQInd;
  const $ = (id) => document.getElementById(id);
  const wrap = $("chart"), overlay = $("overlay"), ctx = overlay.getContext("2d");
  const hint = $("hint"), legend = $("legend");

  // ------------------------------------------------------------ storage
  const store = (key, value) => { try { localStorage.setItem(key, JSON.stringify(value)); } catch (e) { /* private mode */ } };
  const fetchStored = (key, fallback) => {
    try { const v = localStorage.getItem(key); return v ? JSON.parse(v) : fallback; } catch (e) { return fallback; }
  };
  const IDX = P.index;
  const STATE_KEY = "kq_chart_state_" + IDX, DRAW_KEY = "kq_drawings_" + IDX;

  // ------------------------------------------------- indicator settings schemas
  const SRC = ["open", "high", "low", "close", "hl2", "hlc3", "ohlc4", "hlcc4"];
  const SCHEMAS = {
    volume: { title: "Volume (futures)", defaults: { ma: false, maLength: 20, upColor: "#26a69a", downColor: "#ef5350" },
      fields: [["ma", "Show volume moving average", "bool"], ["maLength", "MA length", "int"],
               ["upColor", "Up colour", "color"], ["downColor", "Down colour", "color"]] },
    ktmi: { title: "KTMI Uni Lite", defaults: { momentum: false },
      fields: [["momentum", "Show momentum lines (silent, not traded)", "bool"]] },
    vwap: { title: "VWAP", defaults: Object.assign({}, K.VWAP_DEFAULTS, { color: "#2962ff", bandColor: "#26a69a", fill: true }),
      fields: [["anchor", "Anchor period", "select", ["Session", "Week", "Month", "Quarter", "Year"]],
               ["source", "Source", "select", SRC], ["offset", "Offset", "int"],
               ["mode", "Bands calculation mode", "select", ["Standard Deviation", "Percentage"]],
               ["band1", "Band #1 (1 SD)", "bool"], ["mult1", "Bands multiplier #1", "float"],
               ["band2", "Band #2 (2 SD)", "bool"], ["mult2", "Bands multiplier #2", "float"],
               ["band3", "Band #3 (3 SD)", "bool"], ["mult3", "Bands multiplier #3", "float"],
               ["hideOnDaily", "Hide VWAP on 1D", "bool"], ["fill", "Fill between bands", "bool"],
               ["color", "VWAP colour", "color"], ["bandColor", "Bands colour", "color"]] },
    bb: { title: "Bollinger Bands", defaults: Object.assign({}, K.BB_DEFAULTS, { basisColor: "#ff6d00", bandColor: "#2962ff", fill: true }),
      fields: [["length", "Length", "int"], ["maType", "Basis MA type", "select", ["SMA", "EMA", "SMMA (RMA)", "WMA", "VWMA"]],
               ["source", "Source", "select", SRC], ["mult", "StdDev", "float"], ["offset", "Offset", "int"],
               ["fill", "Background", "bool"], ["basisColor", "Basis colour", "color"], ["bandColor", "Upper/Lower colour", "color"]] },
    oi: { title: "OI Profile", defaults: { show: "OI", strikes: 10, width: 18, values: true, maxLines: true,
                                           callColor: "#ef5350", putColor: "#26a69a" },
      fields: [["show", "Show", "select", ["OI", "Change in OI", "Both"]], ["strikes", "Strikes each side of spot", "int"],
               ["width", "Width (% of chart)", "int"], ["values", "Show values", "bool"],
               ["maxLines", "Mark highest call / put OI strikes", "bool"],
               ["callColor", "Call OI colour", "color"], ["putColor", "Put OI colour", "color"]] },
    smc: { title: "Smart Money Concepts", defaults: Object.assign({}, K.SMC_DEFAULTS),
      fields: [["mode", "Mode", "select", ["Historical", "Present"]],
               ["internal", "Internal structure", "bool"], ["internalFilter", "Internal: show", "select", ["All", "BOS", "CHoCH"]],
               ["swing", "Swing structure", "bool"], ["swingFilter", "Swing: show", "select", ["All", "BOS", "CHoCH"]],
               ["swingLength", "Swing length", "int"], ["internalLength", "Internal length", "int"],
               ["swingPoints", "Swing points (HH / HL / LH / LL)", "bool"], ["strongWeak", "Strong / weak high and low", "bool"],
               ["internalOB", "Internal order blocks", "bool"], ["internalOBCount", "Internal order blocks: how many", "int"],
               ["swingOB", "Swing order blocks", "bool"], ["swingOBCount", "Swing order blocks: how many", "int"],
               ["obMitigation", "Order block mitigation", "select", ["Close", "High/Low"]],
               ["eqhl", "Equal highs / lows", "bool"], ["eqLength", "Equal highs/lows: bars confirmation", "int"],
               ["eqThreshold", "Equal highs/lows: threshold (x ATR)", "float"],
               ["fvg", "Fair value gaps", "bool"], ["fvgAutoThreshold", "FVG auto threshold", "bool"],
               ["fvgExtend", "FVG extend (bars)", "int"],
               ["premiumDiscount", "Premium / discount zones", "bool"],
               ["bullColor", "Bullish colour", "color"], ["bearColor", "Bearish colour", "color"]] },
    vprofile: { title: "Fixed range volume profile", defaults: Object.assign({}, K.VP_DEFAULTS),
      fields: [["rowsLayout", "Rows layout", "select", ["Number Of Rows", "Ticks Per Row"]], ["rowSize", "Row size", "int"],
               ["tickSize", "Tick size (for Ticks Per Row)", "float"],
               ["volume", "Volume", "select", ["Up/Down", "Total", "Delta"]], ["valueArea", "Value area volume %", "int"],
               ["extendRight", "Extend POC / VA lines right", "bool"], ["showProfile", "Show profile", "bool"],
               ["showValues", "Show values", "bool"], ["width", "Width (% of the box)", "int"],
               ["placement", "Placement", "select", ["Left", "Right"]], ["showHighLow", "Show high / low", "bool"],
               ["developingPoc", "Developing POC", "bool"], ["developingVa", "Developing VA", "bool"],
               ["upColor", "Up volume colour", "color"], ["downColor", "Down volume colour", "color"],
               ["pocColor", "POC colour", "color"], ["vaColor", "Value area lines colour", "color"]] },
  };
  const INDICATORS = ["volume", "ktmi", "vwap", "bb", "oi", "smc"];
  const TF_LABELS = { "1": "1m", "3": "3m", "5": "5m", "10": "10m", "15": "15m", "30": "30m", "60": "1h", "D": "1D" };

  function defaultState() {
    const ind = {};
    for (const k of INDICATORS) ind[k] = { on: k === "volume" || k === "ktmi", s: Object.assign({}, SCHEMAS[k].defaults) };
    return { tf: String(P.default_tf || "3"), signals: "Both", ind };
  }
  const state = (() => {
    const saved = fetchStored(STATE_KEY, null), base = defaultState();
    if (!saved) return base;
    base.tf = P.frames[saved.tf] ? saved.tf : base.tf;
    base.signals = saved.signals || base.signals;
    for (const k of INDICATORS) {
      if (saved.ind && saved.ind[k]) {
        base.ind[k].on = !!saved.ind[k].on;
        Object.assign(base.ind[k].s, saved.ind[k].s || {});
      }
    }
    return base;
  })();
  const saveState = () => store(STATE_KEY, state);

  // ------------------------------------------------------------------ chart
  const chart = LW.createChart(wrap, {
    autoSize: true,
    layout: { background: { type: "solid", color: "#131722" }, textColor: "#d1d4dc", fontSize: 12 },
    grid: { vertLines: { color: "#1e222d" }, horzLines: { color: "#1e222d" } },
    rightPriceScale: { borderColor: "#2a2e39" },
    leftPriceScale: { visible: false },
    timeScale: { borderColor: "#2a2e39", timeVisible: true, secondsVisible: false, rightOffset: 8 },
    crosshair: { mode: LW.CrosshairMode.Normal },
  });
  const line = (opts) => chart.addLineSeries(Object.assign({ priceLineVisible: false, lastValueVisible: false,
                                                             crosshairMarkerVisible: false, lineWidth: 1 }, opts));
  const candles = chart.addCandlestickSeries({ upColor: "#26a69a", downColor: "#ef5350", borderVisible: false,
                                               wickUpColor: "#26a69a", wickDownColor: "#ef5350" });
  const volume = chart.addHistogramSeries({ priceScaleId: "vol", priceFormat: { type: "volume" },
                                            priceLineVisible: false, lastValueVisible: false });
  const volumeMA = line({ priceScaleId: "vol", color: "#f7c948" });
  const vwapLines = { mid: line({ lineWidth: 2 }), up: [line({}), line({}), line({})], down: [line({}), line({}), line({})] };
  const bbLines = { basis: line({}), upper: line({}), lower: line({}) };
  const KTMI_COLORS = { long_speed: "rgb(0,154,130)", long_signal: "rgb(56,180,91)", short_speed: "rgb(244,9,99)",
                        short_signal: "rgb(244,48,72)", momentum_speed: "rgb(254,154,42)", momentum_signal: "rgb(249,239,84)" };
  const ktmiLines = {};
  for (const [name, color] of Object.entries(KTMI_COLORS))
    ktmiLines[name] = line({ priceScaleId: "ktmi", color, lineWidth: name.endsWith("speed") ? 2 : 1 });
  const L = P.levels, grey = "#787b86", purple = "rgb(112,48,160)";
  for (const [price, color, style, width] of [[L.center, grey, LW.LineStyle.Solid, 2], [L.upper, grey, LW.LineStyle.Dashed, 1],
                                                [L.lower, grey, LW.LineStyle.Dashed, 1], [L.overbought, purple, LW.LineStyle.Solid, 1],
                                                [L.oversold, purple, LW.LineStyle.Solid, 1]])
    ktmiLines.long_speed.createPriceLine({ price, color, lineStyle: style, lineWidth: width, axisLabelVisible: false, title: "" });

  let F = null, times = [], N = 0, BAR = 60, PRICE_BOTTOM = 0.68;
  let ind = {};                  // computed indicators for the current frame
  let version = 0;               // bumps when data or timeframe changes (cache key)

  function layout() {
    const ktmiOn = state.ind.ktmi.on, volOn = state.ind.volume.on;
    PRICE_BOTTOM = ktmiOn ? 0.68 : 1.0;
    const volTop = PRICE_BOTTOM - 0.14;
    chart.priceScale("right").applyOptions({ scaleMargins: { top: 0.04, bottom: 1 - PRICE_BOTTOM + (volOn ? 0.13 : 0.03) } });
    volume.priceScale().applyOptions({ scaleMargins: { top: volTop, bottom: 1 - PRICE_BOTTOM + 0.005 } });
    chart.priceScale("ktmi").applyOptions({ scaleMargins: { top: 0.72, bottom: 0.03 } });
    volume.applyOptions({ visible: volOn });
    volumeMA.applyOptions({ visible: volOn && state.ind.volume.s.ma });
    for (const [name, s] of Object.entries(ktmiLines))
      s.applyOptions({ visible: ktmiOn && (!name.startsWith("momentum") || state.ind.ktmi.s.momentum) });
  }

  const series = (vals) => vals.map((v, i) => (v === null || v === undefined || Number.isNaN(v) ? { time: times[i] } : { time: times[i], value: v }));

  function computeIndicators() {
    ind = {};
    const S = state.ind;
    const vw = S.vwap, bb = S.bb;
    // VWAP
    const vwapOn = vw.on && !(vw.s.hideOnDaily && state.tf === "D");
    if (vwapOn) {
      ind.vwap = K.vwap(F, vw.s);
      vwapLines.mid.setData(series(ind.vwap.vwap));
      vwapLines.mid.applyOptions({ color: vw.s.color, visible: true });
      for (let b = 0; b < 3; b++) {
        const on = vw.s["band" + (b + 1)];
        vwapLines.up[b].setData(on ? series(ind.vwap.upper[b]) : []);
        vwapLines.down[b].setData(on ? series(ind.vwap.lower[b]) : []);
        vwapLines.up[b].applyOptions({ color: vw.s.bandColor, visible: on });
        vwapLines.down[b].applyOptions({ color: vw.s.bandColor, visible: on });
      }
    } else {
      vwapLines.mid.applyOptions({ visible: false });
      for (let b = 0; b < 3; b++) { vwapLines.up[b].applyOptions({ visible: false }); vwapLines.down[b].applyOptions({ visible: false }); }
    }
    // Bollinger Bands
    if (bb.on) {
      ind.bb = K.bollinger(F, bb.s);
      bbLines.basis.setData(series(ind.bb.basis));
      bbLines.upper.setData(series(ind.bb.upper));
      bbLines.lower.setData(series(ind.bb.lower));
      bbLines.basis.applyOptions({ color: bb.s.basisColor, visible: true });
      bbLines.upper.applyOptions({ color: bb.s.bandColor, visible: true });
      bbLines.lower.applyOptions({ color: bb.s.bandColor, visible: true });
    } else for (const s of Object.values(bbLines)) s.applyOptions({ visible: false });
    // Volume MA
    if (S.volume.on && S.volume.s.ma) volumeMA.setData(series(K.sma(F.v, Math.max(1, S.volume.s.maLength | 0))));
    // Smart Money Concepts
    if (S.smc.on) ind.smc = K.smc(F, S.smc.s);
  }

  function setMarkers() {
    const show = state.signals, marks = [];
    if (show === "Both" || show === "Long")
      for (const t of F.long) marks.push({ time: t, position: "belowBar", color: "#26a69a", shape: "arrowUp", text: "BUY CALL" });
    if (show === "Both" || show === "Short")
      for (const t of F.short) marks.push({ time: t, position: "aboveBar", color: "#ef5350", shape: "arrowDown", text: "BUY PUT" });
    marks.sort((a, b) => a.time - b.time);
    candles.setMarkers(marks);
  }

  function setFrame(tf, keepView) {
    const oldRange = chart.timeScale().getVisibleLogicalRange(), oldN = N;
    if (!keepView && F) store(`kq_view_${IDX}_${state.tf}`, oldRange ? { fromEnd: N - oldRange.from, toEnd: N - oldRange.to } : null);
    state.tf = tf; saveState();
    F = P.frames[tf]; times = F.t; N = times.length; BAR = tf === "D" ? 86400 : Number(tf) * 60;
    version++;
    const S = state.ind.volume.s;
    candles.setData(times.map((t, i) => ({ time: t, open: F.o[i], high: F.h[i], low: F.l[i], close: F.c[i] })));
    volume.setData(times.map((t, i) => ({ time: t, value: F.v[i], color: (F.c[i] >= F.o[i] ? S.upColor : S.downColor) + "99" })));
    for (const [name, s] of Object.entries(ktmiLines)) s.setData(series(F.ktmi[name] || []));
    setMarkers();
    layout();
    computeIndicators();
    chart.applyOptions({ timeScale: { timeVisible: tf !== "D" } });
    if (keepView && oldRange) {
      const shift = oldRange.to >= oldN - 2 ? N - oldN : 0;          // follow new candles when at the right edge
      chart.timeScale().setVisibleLogicalRange({ from: oldRange.from + shift, to: oldRange.to + shift });
    } else {
      const view = fetchStored(`kq_view_${IDX}_${tf}`, null);
      if (view && N) chart.timeScale().setVisibleLogicalRange({ from: N - view.fromEnd, to: N - view.toEnd });
      else if (N > 160) chart.timeScale().setVisibleLogicalRange({ from: N - 150, to: N + 8 });
      else chart.timeScale().fitContent();
    }
    document.querySelectorAll(".tf").forEach((b) => b.classList.toggle("active", b.dataset.tf === tf));
    renderLegend(null);
  }
  chart.timeScale().subscribeVisibleLogicalRangeChange((r) => {
    if (r && N) store(`kq_view_${IDX}_${state.tf}`, { fromEnd: N - r.from, toEnd: N - r.to });
  });

  // --------------------------------------------------------------- number text
  function big(x) {
    const a = Math.abs(x);
    if (a >= 1e7) return (x / 1e7).toFixed(2) + " Cr";
    if (a >= 1e5) return (x / 1e5).toFixed(2) + " L";
    if (a >= 1e3) return (x / 1e3).toFixed(1) + " K";
    return String(Math.round(x));
  }
  const fmt = (v) => (v === undefined || v === null || Number.isNaN(v) ? "-" : Number(v).toFixed(2));
  function span(seconds) {
    const d = Math.floor(seconds / 86400), h = Math.floor((seconds % 86400) / 3600), m = Math.round((seconds % 3600) / 60);
    return [d ? d + "d" : "", h ? h + "h" : "", m || (!d && !h) ? m + "m" : ""].filter(Boolean).join(" ");
  }

  // --------------------------------------------------------------- legend
  let hoverIndex = null;
  function renderLegend(param) {
    let i = N - 1;
    if (param && param.time !== undefined) {
      const k = times.indexOf(param.time);
      if (k >= 0) i = k;
    }
    hoverIndex = i;
    if (!N) { legend.innerHTML = `<div class="lg"><b>${P.title}</b> &nbsp; no candles yet</div>`; return; }
    const S = state.ind;
    const up = F.c[i] >= F.o[i] ? "#26a69a" : "#ef5350";
    const rows = [`<div class="lg"><b>${P.title} · ${TF_LABELS[state.tf]}</b> &nbsp;<span style="color:${up}">O ${fmt(F.o[i])} H ${fmt(F.h[i])} L ${fmt(F.l[i])} C ${fmt(F.c[i])}</span></div>`];
    const row = (key, text) => `<div class="lg">${text} <button class="lgb" data-gear="${key}" title="Settings">⚙</button><button class="lgb" data-off="${key}" title="Remove">✕</button></div>`;
    if (S.volume.on) rows.push(row("volume", `Vol <span style="color:${up}">${P.volume_source ? big(F.v[i]) : "n/a"}</span>` +
      (P.volume_source ? ` <span class="dim">(${P.volume_source})</span>` : ` <span class="dim">(no futures volume in this data)</span>`)));
    if (ind.vwap) rows.push(row("vwap", `<span style="color:${S.vwap.s.color}">VWAP ${S.vwap.s.anchor} ${fmt(ind.vwap.vwap[i])}</span>` +
      (ind.vwap.equalWeights ? ' <span class="dim">(no volume: equal weights)</span>' : "")));
    if (ind.bb) rows.push(row("bb", `<span style="color:${S.bb.s.basisColor}">BB ${S.bb.s.length} ${S.bb.s.mult}</span> ` +
      `${fmt(ind.bb.basis[i])} <span style="color:${S.bb.s.bandColor}">${fmt(ind.bb.upper[i])} ${fmt(ind.bb.lower[i])}</span>`));
    if (S.oi.on) rows.push(row("oi", P.oi ? `OI Profile <span class="dim">expiry ${P.oi.expiry || "-"} · ${P.oi.updated_at || ""}</span>`
                                         : `OI Profile <span class="dim">(no option-chain data: start the trading program)</span>`));
    if (ind.smc) rows.push(row("smc", `Smart Money Concepts <span class="dim">${ind.smc.structures.length} breaks · ${ind.smc.orderBlocks.length} OB · ${ind.smc.fvgs.length} FVG</span>`));
    if (S.ktmi.on) {
      const k = (n) => fmt(F.ktmi[n] ? F.ktmi[n][i] : null);
      rows.push(row("ktmi", `KTMI Uni Lite <span style="color:${KTMI_COLORS.long_speed}">Long ${k("long_speed")} / ${k("long_signal")}</span> ` +
        `<span style="color:${KTMI_COLORS.short_speed}">Short ${k("short_speed")} / ${k("short_signal")}</span>`));
    }
    legend.innerHTML = rows.join("");
  }
  legend.addEventListener("click", (e) => {
    const b = e.target.closest("button");
    if (!b) return;
    if (b.dataset.gear) openSettings(b.dataset.gear);
    if (b.dataset.off) { state.ind[b.dataset.off].on = false; saveState(); refreshIndicators(); }
  });

  function refreshIndicators() {
    layout(); computeIndicators(); renderLegend(null); syncMenu(); version++;
  }

  // --------------------------------------------------------------- top bar
  $("tfs").innerHTML = Object.keys(TF_LABELS).filter((tf) => P.frames[tf])
    .map((tf) => `<button class="tf" data-tf="${tf}">${TF_LABELS[tf]}</button>`).join("");
  document.querySelectorAll(".tf").forEach((b) => b.addEventListener("click", () => setFrame(b.dataset.tf, false)));
  document.querySelectorAll(".sig").forEach((b) => b.addEventListener("click", () => {
    state.signals = b.dataset.sig; saveState(); setMarkers();
    document.querySelectorAll(".sig").forEach((x) => x.classList.toggle("active", x === b));
  }));
  document.querySelectorAll(".sig").forEach((x) => x.classList.toggle("active", x.dataset.sig === state.signals));

  const menu = $("indmenu");
  menu.innerHTML = INDICATORS.map((k) => `<label class="mi"><input type="checkbox" data-ind="${k}"> ${SCHEMAS[k].title}` +
    `<button class="lgb" data-gear="${k}" title="Settings">⚙</button></label>`).join("");
  function syncMenu() { menu.querySelectorAll("input[data-ind]").forEach((c) => { c.checked = state.ind[c.dataset.ind].on; }); }
  $("indbtn").addEventListener("click", () => { menu.classList.toggle("open"); syncMenu(); });
  menu.addEventListener("change", (e) => {
    const k = e.target.dataset.ind;
    if (!k) return;
    state.ind[k].on = e.target.checked; saveState(); refreshIndicators();
  });
  menu.addEventListener("click", (e) => { const b = e.target.closest("button"); if (b) { e.preventDefault(); openSettings(b.dataset.gear); } });
  document.addEventListener("mousedown", (e) => { if (!menu.contains(e.target) && e.target !== $("indbtn")) menu.classList.remove("open"); });

  // ------------------------------------------------------------ settings dialog
  const dialog = $("dialog");
  function openSettings(key, drawing) {
    const schema = SCHEMAS[key], target = drawing ? drawing.s : state.ind[key].s;
    menu.classList.remove("open");
    const fieldHtml = schema.fields.map(([name, label, type, options]) => {
      const v = target[name];
      if (type === "bool") return `<label class="fr"><input type="checkbox" name="${name}" ${v ? "checked" : ""}> ${label}</label>`;
      if (type === "select") return `<label class="fr">${label}<select name="${name}">${options.map((o) =>
        `<option ${o === v ? "selected" : ""}>${o}</option>`).join("")}</select></label>`;
      if (type === "color") return `<label class="fr">${label}<input type="color" name="${name}" value="${v}"></label>`;
      return `<label class="fr">${label}<input type="number" name="${name}" value="${v}" step="${type === "int" ? 1 : "any"}"></label>`;
    }).join("");
    dialog.innerHTML = `<div class="dlg"><div class="dh">${schema.title}</div><form id="dform">${fieldHtml}</form>` +
      `<div class="db"><button id="dreset">Defaults</button><span style="flex:1"></span><button id="dcancel">Cancel</button>` +
      `<button id="dok" class="primary">OK</button></div></div>`;
    dialog.classList.add("open");
    $("dcancel").onclick = () => dialog.classList.remove("open");
    $("dreset").onclick = () => { Object.assign(target, SCHEMAS[key].defaults); dialog.classList.remove("open"); apply(); };
    $("dok").onclick = () => {
      for (const [name, , type] of schema.fields) {
        const el = $("dform").elements[name];
        target[name] = type === "bool" ? el.checked : type === "int" ? parseInt(el.value, 10) || 0
          : type === "float" ? parseFloat(el.value) || 0 : el.value;
      }
      dialog.classList.remove("open");
      apply();
    };
    function apply() {
      if (drawing) { saveDrawings(); version++; } else { state.ind[key].on = true; saveState(); setFrame(state.tf, true); refreshIndicators(); }
    }
  }

  // ------------------------------------------------- time <-> bar position
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
    return lo + Math.min(0.999, (t - times[lo]) / BAR);
  }
  const xOfTime = (t) => chart.timeScale().logicalToCoordinate(timeToLogical(t));
  const xOfIndex = (i) => chart.timeScale().logicalToCoordinate(i);
  const yOf = (p) => candles.priceToCoordinate(p);
  function toXY(pt) { const x = xOfTime(pt.t), y = yOf(pt.p); return x === null || y === null ? null : { x, y }; }
  function fromXY(x, y) {
    const l = chart.timeScale().coordinateToLogical(x), p = candles.coordinateToPrice(y);
    return l === null || p === null ? null : { t: logicalToTime(l), p: Math.round(p * 100) / 100 };
  }
  function paneXY(e) { const r = wrap.getBoundingClientRect(); return { x: e.clientX - r.left, y: e.clientY - r.top }; }

  // ------------------------------------------------------------- drawings
  const TOOL_TYPES = ["hline", "vline", "rect", "path", "measure", "vprofile"];
  let drawings = fetchStored(DRAW_KEY, []).filter((d) => TOOL_TYPES.includes(d.type));
  const saveDrawings = () => store(DRAW_KEY, drawings);
  const HINTS = {
    cursor: "Cursor: drag to move the chart. Click a drawing to select it; drag it or its dots. Delete key removes it. Double-click a volume profile for its settings.",
    hline: "Horizontal line: click once at the price.",
    vline: "Vertical line: click once at the time.",
    rect: "Rectangle: click one corner, then the opposite corner.",
    path: "Path: click each point. Click the last point again (or press Enter) to finish. Esc cancels.",
    measure: "Measure: click the start, then the end. Shows points, %, bars and time.",
    vprofile: "Volume profile: click the first candle, then the last candle of the range.",
  };
  const NEEDED = { hline: 1, vline: 1, rect: 2, measure: 2, vprofile: 2 };
  let tool = "cursor", pending = null, hover = null, selected = null, drag = null, press = null;
  const newId = () => Date.now().toString(36) + Math.random().toString(36).slice(2, 6);

  function setTool(name) {
    tool = name; pending = null;
    document.querySelectorAll(".tool").forEach((b) => b.classList.toggle("active", b.dataset.tool === name));
    hint.textContent = HINTS[name];
    chart.applyOptions({ handleScroll: name === "cursor" ? true
      : { mouseWheel: true, pressedMouseMove: false, horzTouchDrag: false, vertTouchDrag: false } });
  }
  function finish() {
    if (pending && pending.pts.length >= (pending.type === "path" ? 2 : NEEDED[pending.type])) {
      drawings.push(pending); selected = pending.id; saveDrawings();
    }
    setTool("cursor");
  }
  function place(x, y) {
    const pt = fromXY(x, y);
    if (!pt) return;
    if (!pending) {
      pending = { id: newId(), type: tool, pts: [], color: $("color").value };
      if (tool === "vprofile") pending.s = Object.assign({}, SCHEMAS.vprofile.defaults);
    }
    if (tool === "path" && pending.pts.length >= 2) {
      const last = toXY(pending.pts[pending.pts.length - 1]);
      if (last && Math.hypot(last.x - x, last.y - y) < 8) { finish(); return; }
    }
    pending.pts.push(pt);
    if (tool !== "path" && pending.pts.length >= NEEDED[tool]) finish();
  }
  wrap.addEventListener("pointerdown", (e) => { if (tool !== "cursor") { press = paneXY(e); e.preventDefault(); } }, true);
  wrap.addEventListener("pointerup", (e) => {
    if (tool === "cursor" || !press) return;
    const up = paneXY(e);
    if (Math.hypot(up.x - press.x, up.y - press.y) < 6) place(up.x, up.y);
    press = null;
  }, true);
  chart.subscribeCrosshairMove((param) => { hover = param.point || null; renderLegend(param); });

  // hit testing
  function segDist(px, py, a, b) {
    const dx = b.x - a.x, dy = b.y - a.y, len = dx * dx + dy * dy;
    const u = len ? Math.max(0, Math.min(1, ((px - a.x) * dx + (py - a.y) * dy) / len)) : 0;
    return Math.hypot(px - (a.x + u * dx), py - (a.y + u * dy));
  }
  function boxOf(d) {
    if (d.type === "vprofile") {
      const vp = profileOf(d);
      if (!vp) return null;
      const x0 = xOfTime(Math.min(d.pts[0].t, d.pts[1].t)), x1 = xOfTime(Math.max(d.pts[0].t, d.pts[1].t));
      const y0 = yOf(vp.high), y1 = yOf(vp.low);
      return x0 === null || x1 === null || y0 === null || y1 === null ? null : { x0, x1, y0, y1 };
    }
    const a = toXY(d.pts[0]), b = toXY(d.pts[1]);
    return a && b ? { x0: Math.min(a.x, b.x), x1: Math.max(a.x, b.x), y0: Math.min(a.y, b.y), y1: Math.max(a.y, b.y) } : null;
  }
  function hitDistance(d, x, y) {
    if (d.type === "rect" || d.type === "measure" || d.type === "vprofile") {
      const b = boxOf(d);
      return b && x >= b.x0 - 3 && x <= b.x1 + 3 && y >= b.y0 - 3 && y <= b.y1 + 3 ? 0 : Infinity;
    }
    const xy = d.pts.map(toXY);
    if (xy.some((v) => v === null)) return Infinity;
    if (d.type === "hline") return Math.abs(y - xy[0].y);
    if (d.type === "vline") return Math.abs(x - xy[0].x);
    let best = Infinity;
    for (let i = 1; i < xy.length; i++) best = Math.min(best, segDist(x, y, xy[i - 1], xy[i]));
    return best;
  }
  function hitDrawing(x, y) {
    let best = null, bestD = 7;
    for (const d of drawings) { const dist = hitDistance(d, x, y); if (dist <= bestD) { best = d; bestD = dist; } }
    return best;
  }
  function hitHandle(x, y) {
    const d = drawings.find((v) => v.id === selected);
    if (!d || d.type === "hline" || d.type === "vline") return null;
    for (let i = 0; i < d.pts.length; i++) {
      const p = toXY(d.pts[i]);
      if (p && Math.hypot(p.x - x, p.y - y) <= 8) return { d, i };
    }
    return null;
  }
  wrap.addEventListener("pointerdown", (e) => {
    if (tool !== "cursor" || e.target.closest("#legend")) return;
    const { x, y } = paneXY(e);
    const handle = hitHandle(x, y), d = handle ? handle.d : hitDrawing(x, y);
    if (!d) { selected = null; return; }
    selected = d.id;
    $("color").value = d.color || $("color").value;
    drag = { d, index: handle ? handle.i : null, l0: chart.timeScale().coordinateToLogical(x),
             p0: candles.coordinateToPrice(y), orig: d.pts.map((p) => ({ ...p })) };
    chart.applyOptions({ handleScroll: false, handleScale: false });
    e.preventDefault(); e.stopPropagation();
  }, true);
  window.addEventListener("pointermove", (e) => {
    if (!drag) return;
    const { x, y } = paneXY(e);
    if (drag.index !== null) { const pt = fromXY(x, y); if (pt) drag.d.pts[drag.index] = pt; return; }
    const l = chart.timeScale().coordinateToLogical(x), p = candles.coordinateToPrice(y);
    if (l === null || p === null || drag.l0 === null || drag.p0 === null) return;
    drag.d.pts = drag.orig.map((o) => ({ t: logicalToTime(timeToLogical(o.t) + (l - drag.l0)),
                                         p: Math.round((o.p + (p - drag.p0)) * 100) / 100 }));
  });
  window.addEventListener("pointerup", () => {
    if (!drag) return;
    drag = null; chart.applyOptions({ handleScroll: true, handleScale: true }); saveDrawings();
  });
  wrap.addEventListener("dblclick", () => {
    const d = drawings.find((v) => v.id === selected);
    if (d && d.type === "vprofile") openSettings("vprofile", d);
  });
  document.addEventListener("keydown", (e) => {
    if (dialog.classList.contains("open")) return;
    if ((e.key === "Delete" || e.key === "Backspace") && selected) {
      drawings = drawings.filter((d) => d.id !== selected); selected = null; saveDrawings();
    } else if (e.key === "Escape") { setTool("cursor"); }
    else if (e.key === "Enter" && pending && pending.type === "path") finish();
  });
  document.querySelectorAll(".tool").forEach((b) => b.addEventListener("click", () => setTool(b.dataset.tool)));
  $("delete").addEventListener("click", () => {
    if (!selected) { hint.textContent = "Select a drawing first (cursor tool, click on it)."; return; }
    drawings = drawings.filter((d) => d.id !== selected); selected = null; saveDrawings();
  });
  $("gear").addEventListener("click", () => {
    const d = drawings.find((v) => v.id === selected);
    if (d && d.type === "vprofile") openSettings("vprofile", d);
    else hint.textContent = "Select a volume profile first; the other drawings only have a colour.";
  });
  let clearArmed = 0;
  $("clear").addEventListener("click", () => {
    if (Date.now() - clearArmed < 3000) {
      drawings = []; selected = null; saveDrawings(); clearArmed = 0; $("clear").classList.remove("armed");
      hint.textContent = "All drawings removed for this index."; return;
    }
    clearArmed = Date.now(); $("clear").classList.add("armed");
    hint.textContent = "Click the bin again within 3 seconds to remove ALL drawings for this index.";
    setTimeout(() => $("clear").classList.remove("armed"), 3000);
  });
  $("color").addEventListener("input", () => {
    const d = drawings.find((v) => v.id === selected);
    if (d) { d.color = $("color").value; saveDrawings(); }
  });

  // ------------------------------------------------- volume profile (cached)
  const vpCache = new Map();
  function profileOf(d) {
    if (d.pts.length < 2) return null;
    const key = `${version}|${JSON.stringify(d.pts)}|${JSON.stringify(d.s)}`;
    const hit = vpCache.get(d.id);
    if (hit && hit.key === key) return hit.vp;
    const t0 = Math.min(d.pts[0].t, d.pts[1].t), t1 = Math.max(d.pts[0].t, d.pts[1].t);
    // Use 1-minute candles when they cover the range (more precise), else the chart's own candles.
    const one = P.frames["1"];
    const src = state.tf !== "D" && one && one.t.length && t0 >= one.t[0] ? one : F;
    let i0 = src.t.findIndex((t) => t >= t0), i1 = -1;
    for (let i = src.t.length - 1; i >= 0; i--) if (src.t[i] <= t1 + BAR - 1) { i1 = i; break; }
    const vp = i0 < 0 || i1 < i0 ? null : K.volumeProfile(src, i0, i1, d.s);
    vpCache.set(d.id, { key, vp });
    return vp;
  }

  // ------------------------------------------------------------- painting
  function alpha(color, a) {
    if (color.startsWith("rgb")) return color.replace("rgb(", "rgba(").replace(")", `,${a})`);
    const n = parseInt(color.slice(1, 7), 16);
    return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${a})`;
  }
  function label(text, x, y, bg, align, fg) {
    ctx.font = "11px sans-serif";
    const w = ctx.measureText(text).width + 8;
    const bx = align === "right" ? x - w : align === "center" ? x - w / 2 : x;
    ctx.fillStyle = bg; ctx.fillRect(bx, y - 8, w, 16);
    ctx.fillStyle = fg || "#ffffff"; ctx.fillText(text, bx + 4, y + 4);
  }
  function text(t, x, y, color, align) {
    ctx.font = "10px sans-serif"; ctx.fillStyle = color; ctx.textAlign = align || "left"; ctx.fillText(t, x, y); ctx.textAlign = "left";
  }
  function hLine(x0, x1, y, color, width, dash) {
    ctx.strokeStyle = color; ctx.lineWidth = width || 1; ctx.setLineDash(dash || []);
    ctx.beginPath(); ctx.moveTo(x0, y); ctx.lineTo(x1, y); ctx.stroke(); ctx.setLineDash([]);
  }

  function paintBandFill(upper, lower, color) {
    const r = chart.timeScale().getVisibleLogicalRange();
    if (!r) return;
    const a = Math.max(0, Math.floor(r.from) - 1), b = Math.min(N - 1, Math.ceil(r.to) + 1);
    let started = false;
    const top = [], bottom = [];
    for (let i = a; i <= b; i++) {
      if (upper[i] === null || lower[i] === null || upper[i] === undefined) continue;
      const x = xOfIndex(i), y0 = yOf(upper[i]), y1 = yOf(lower[i]);
      if (x === null || y0 === null || y1 === null) continue;
      top.push([x, y0]); bottom.push([x, y1]); started = true;
    }
    if (!started) return;
    ctx.fillStyle = color; ctx.beginPath();
    top.forEach(([x, y], k) => (k ? ctx.lineTo(x, y) : ctx.moveTo(x, y)));
    for (let k = bottom.length - 1; k >= 0; k--) ctx.lineTo(bottom[k][0], bottom[k][1]);
    ctx.closePath(); ctx.fill();
  }

  function paintOI(W) {
    const s = state.ind.oi.s, oi = P.oi;
    if (!oi || !oi.rows || !oi.rows.length) return;
    const spot = oi.spot || F.c[N - 1];
    const rows = oi.rows.slice().sort((a, b) => Math.abs(a.strike - spot) - Math.abs(b.strike - spot))
      .slice(0, Math.max(1, s.strikes) * 2 + 1).sort((a, b) => a.strike - b.strike);
    if (!rows.length) return;
    const step = rows.length > 1 ? rows[1].strike - rows[0].strike : 50;
    const value = (r, side) => (s.show === "Change in OI" ? r[side + "_oi_change"] : r[side + "_oi"]);
    const max = Math.max(1, ...rows.map((r) => Math.max(Math.abs(value(r, "call")), Math.abs(value(r, "put")))));
    const width = W * Math.max(5, Math.min(80, s.width)) / 100;
    for (const r of rows) {
      const y = yOf(r.strike), yA = yOf(r.strike + step / 2), yB = yOf(r.strike - step / 2);
      if (y === null || yA === null || yB === null) continue;
      const h = Math.max(2, Math.abs(yB - yA) * 0.4);
      for (const [side, color, dy] of [["call", s.callColor, -h], ["put", s.putColor, 0]]) {
        const v = value(r, side), len = width * Math.abs(v) / max;
        ctx.fillStyle = alpha(color, v < 0 ? 0.35 : 0.7);
        ctx.fillRect(W - len, y + dy, len, h);
        if (s.show === "Both") {
          const c = r[side + "_oi_change"], cl = width * Math.abs(c) / max;
          ctx.strokeStyle = color; ctx.lineWidth = 1; ctx.strokeRect(W - cl, y + dy, cl, h);
        }
        if (s.values && len > 0 && h >= 7) text(`${side === "call" ? "C" : "P"} ${big(v)}`, W - len - 4, y + dy + h - 1, color, "right");
      }
      if (h >= 7) text(String(r.strike), W - 4, y - h - 2, "#9598a1", "right");
    }
    if (s.maxLines) {
      const maxCall = rows.reduce((a, b) => (b.call_oi > a.call_oi ? b : a)), maxPut = rows.reduce((a, b) => (b.put_oi > a.put_oi ? b : a));
      for (const [r, color, name] of [[maxCall, s.callColor, "Max call OI (resistance)"], [maxPut, s.putColor, "Max put OI (support)"]]) {
        const y = yOf(r.strike);
        if (y === null) continue;
        hLine(0, W, y, color, 1, [6, 4]);
        label(`${name} ${r.strike}`, W - width - 6, y - 10, alpha(color, 0.85), "right");
      }
    }
  }

  function paintSMC(W) {
    const r = ind.smc, s = state.ind.smc.s;
    if (!r) return;
    const col = (bull, a) => alpha(bull ? s.bullColor : s.bearColor, a);
    const right = W;
    if (s.premiumDiscount && r.zones) {
      const z = r.zones, x0 = xOfIndex(z.from);
      if (x0 !== null) {
        for (const [band, color, name] of [[z.premium, s.bearColor, "Premium"], [z.equilibrium, "#878b94", "Equilibrium"], [z.discount, s.bullColor, "Discount"]]) {
          const y0 = yOf(band[0]), y1 = yOf(band[1]);
          if (y0 === null || y1 === null) continue;
          ctx.fillStyle = alpha(color, 0.15); ctx.fillRect(x0, Math.min(y0, y1), right - x0, Math.abs(y1 - y0));
          text(name, right - 4, (y0 + y1) / 2 + 3, color, "right");
        }
      }
    }
    for (const ob of r.orderBlocks) {
      const x0 = xOfIndex(ob.idx), y0 = yOf(ob.top), y1 = yOf(ob.bottom);
      if (x0 === null || y0 === null || y1 === null) continue;
      ctx.fillStyle = col(ob.bull, ob.internal ? 0.18 : 0.28); ctx.fillRect(x0, y0, right - x0, y1 - y0);
      ctx.strokeStyle = col(ob.bull, 0.6); ctx.lineWidth = 1; ctx.strokeRect(x0, y0, right - x0, y1 - y0);
      text(ob.internal ? "OB" : "Swing OB", right - 4, y0 + 10, col(ob.bull, 0.9), "right");
    }
    for (const g of r.fvgs) {
      const x0 = xOfIndex(g.idx - 1), x1 = xOfIndex(N - 1 + Math.max(0, s.fvgExtend | 0)), y0 = yOf(g.top), y1 = yOf(g.bottom);
      if (x0 === null || x1 === null || y0 === null || y1 === null) continue;
      ctx.fillStyle = col(g.bull, 0.22); ctx.fillRect(x0, y0, x1 - x0, y1 - y0);
      text("FVG", x0 + 3, y0 + 10, col(g.bull, 0.9));
    }
    for (const e of r.structures) {
      const x0 = xOfIndex(e.from), x1 = xOfIndex(e.to), y = yOf(e.price);
      if (x0 === null || x1 === null || y === null) continue;
      hLine(x0, x1, y, col(e.bull, 1), e.internal ? 1 : 1.5, e.internal ? [4, 3] : []);
      text(e.label, (x0 + x1) / 2, e.bull ? y - 4 : y + 11, col(e.bull, 1), "center");
    }
    for (const q of r.equal) {
      const x0 = xOfIndex(q.from), x1 = xOfIndex(q.to), y = yOf(q.price);
      if (x0 === null || x1 === null || y === null) continue;
      hLine(x0, x1, y, col(!q.high, 1), 1, [2, 3]);
      text(q.label, (x0 + x1) / 2, q.high ? y - 4 : y + 11, col(!q.high, 1), "center");
    }
    for (const p of r.swings) {
      const x = xOfIndex(p.idx), y = yOf(p.price);
      if (x === null || y === null) continue;
      text(p.label, x, p.high ? y - 6 : y + 14, col(!p.high, 1), "center");
    }
    if (s.strongWeak && r.strongWeak) {
      const w = r.strongWeak;
      for (const [price, idx, name, bull] of [[w.top, w.topIdx, w.topLabel, false], [w.bottom, w.bottomIdx, w.bottomLabel, true]]) {
        const x0 = xOfIndex(idx), y = yOf(price);
        if (x0 === null || y === null) continue;
        hLine(x0, right, y, col(bull, 1), 1);
        text(name, right - 4, bull ? y + 12 : y - 4, col(bull, 1), "right");
      }
    }
  }

  function paintProfile(d, isSelected, W) {
    const vp = profileOf(d);
    if (!vp) return;
    const s = d.s, b = boxOf(d);
    if (!b) return;
    const x0 = b.x0, x1 = Math.max(b.x1, b.x0 + 4), boxW = x1 - x0;
    ctx.fillStyle = "rgba(41,98,255,0.05)"; ctx.fillRect(x0, b.y0, boxW, b.y1 - b.y0);
    if (isSelected) { ctx.strokeStyle = "#2962ff"; ctx.lineWidth = 1; ctx.strokeRect(x0, b.y0, boxW, b.y1 - b.y0); }
    const maxLen = boxW * Math.max(5, Math.min(100, s.width)) / 100;
    const deltas = vp.up.map((u, r) => u - vp.down[r]);
    const scale = s.volume === "Delta" ? Math.max(1, ...deltas.map(Math.abs)) : Math.max(1, ...vp.totals);
    if (s.showProfile) {
      for (let r = 0; r < vp.rows; r++) {
        const yTop = yOf(vp.low + (r + 1) * vp.step), yBot = yOf(vp.low + r * vp.step);
        if (yTop === null || yBot === null) continue;
        const h = Math.max(1, yBot - yTop - 1), inVA = r >= vp.vaLow && r <= vp.vaHigh, a = inVA ? 0.75 : 0.3;
        const parts = s.volume === "Delta" ? [[Math.abs(deltas[r]), deltas[r] >= 0 ? s.upColor : s.downColor]]
          : s.volume === "Total" ? [[vp.totals[r], s.upColor]] : [[vp.up[r], s.upColor], [vp.down[r], s.downColor]];
        let offset = 0;
        for (const [v, color] of parts) {
          const len = maxLen * v / scale;
          ctx.fillStyle = alpha(color, a);
          if (s.placement === "Right") ctx.fillRect(x1 - offset - len, yTop, len, h); else ctx.fillRect(x0 + offset, yTop, len, h);
          offset += len;
        }
        if (s.showValues) {
          const v = s.volume === "Delta" ? deltas[r] : vp.totals[r];
          text(big(v), s.placement === "Right" ? x1 - offset - 3 : x0 + offset + 3, yTop + h / 2 + 3, "#d1d4dc", s.placement === "Right" ? "right" : "left");
        }
      }
    }
    const lineEnd = s.extendRight ? W : x1;
    const yp = yOf(vp.poc), yh = yOf(vp.vah), yl = yOf(vp.val);
    if (yp !== null) { hLine(x0, lineEnd, yp, s.pocColor, 2); label(`POC ${vp.poc.toFixed(2)}`, lineEnd - 2, yp, alpha(s.pocColor, 0.9), "right"); }
    if (yh !== null) { hLine(x0, lineEnd, yh, s.vaColor, 1); text(`VAH ${vp.vah.toFixed(2)}`, lineEnd - 4, yh - 3, s.vaColor, "right"); }
    if (yl !== null) { hLine(x0, lineEnd, yl, s.vaColor, 1); text(`VAL ${vp.val.toFixed(2)}`, lineEnd - 4, yl + 11, s.vaColor, "right"); }
    if (s.showHighLow) {
      hLine(x0, x1, b.y0, "#d1d4dc", 1, [4, 3]); text(`High ${vp.high.toFixed(2)}`, x0 + 2, b.y0 - 3, "#d1d4dc");
      hLine(x0, x1, b.y1, "#d1d4dc", 1, [4, 3]); text(`Low ${vp.low.toFixed(2)}`, x0 + 2, b.y1 + 11, "#d1d4dc");
    }
    for (const [key, field, color] of [["developingPoc", "poc", s.pocColor], ["developingVa", "vah", s.vaColor], ["developingVa", "val", s.vaColor]]) {
      if (!s[key] || !vp.developing.length) continue;
      ctx.strokeStyle = color; ctx.lineWidth = 1; ctx.setLineDash(field === "poc" ? [] : [3, 2]); ctx.beginPath();
      let started = false;
      for (const p of vp.developing) {
        const x = xOfTime(p.t), y = yOf(p[field]);
        if (x === null || y === null) continue;
        if (started) ctx.lineTo(x, y); else { ctx.moveTo(x, y); started = true; }
      }
      ctx.stroke(); ctx.setLineDash([]);
    }
    text(`${vp.byTime ? "Time profile (no futures volume)" : "Vol " + big(vp.totalVolume)} · ${vp.rows} rows`, x0 + 2, b.y1 + 24, "#9598a1");
  }

  function paintMeasure(d, preview) {
    const pts = d.pts.slice();
    if (preview && hover) { const h = fromXY(hover.x, hover.y); if (h) pts.push(h); }
    if (pts.length < 2) return;
    const a = toXY(pts[0]), b = toXY(pts[1]);
    if (!a || !b) return;
    const diff = pts[1].p - pts[0].p, up = diff >= 0, color = up ? "#2962ff" : "#f23645";
    ctx.fillStyle = alpha(color, 0.18); ctx.fillRect(Math.min(a.x, b.x), Math.min(a.y, b.y), Math.abs(b.x - a.x), Math.abs(b.y - a.y));
    ctx.strokeStyle = color; ctx.lineWidth = 1;
    ctx.beginPath(); ctx.moveTo((a.x + b.x) / 2, a.y); ctx.lineTo((a.x + b.x) / 2, b.y); ctx.moveTo(a.x, (a.y + b.y) / 2); ctx.lineTo(b.x, (a.y + b.y) / 2); ctx.stroke();
    const t0 = Math.min(pts[0].t, pts[1].t), t1 = Math.max(pts[0].t, pts[1].t);
    const bars = times.filter((t) => t >= t0 && t <= t1).length - 1;
    const pct = pts[0].p ? (diff / pts[0].p) * 100 : 0;
    label(`${up ? "+" : ""}${diff.toFixed(2)} (${up ? "+" : ""}${pct.toFixed(2)}%)  ·  ${Math.max(0, bars)} bars, ${span(t1 - t0)}`,
          (a.x + b.x) / 2, up ? Math.min(a.y, b.y) - 12 : Math.max(a.y, b.y) + 12, alpha(color, 0.9), "center");
  }

  function paintDrawing(d, isSelected, preview, W, H) {
    if (d.type === "vprofile") {
      if (d.pts.length >= 2) paintProfile(d, isSelected, W);
      else if (preview && hover) { const a = toXY(d.pts[0]); if (a) { ctx.strokeStyle = "#2962ff"; ctx.strokeRect(Math.min(a.x, hover.x), 0, Math.abs(hover.x - a.x), H); } }
      return;
    }
    if (d.type === "measure") { paintMeasure(d, preview); return; }
    const pts = d.pts.slice();
    if (preview && hover) { const h = fromXY(hover.x, hover.y); if (h) pts.push(h); }
    const xy = pts.map(toXY).filter((v) => v !== null);
    if (!xy.length) return;
    ctx.strokeStyle = d.color; ctx.lineWidth = isSelected ? 2.5 : 1.6; ctx.setLineDash([]);
    ctx.beginPath();
    if (d.type === "hline") { ctx.moveTo(0, xy[0].y); ctx.lineTo(W, xy[0].y); ctx.stroke(); label(pts[0].p.toFixed(2), W - 2, xy[0].y, d.color, "right"); }
    else if (d.type === "vline") { ctx.moveTo(xy[0].x, 0); ctx.lineTo(xy[0].x, H); ctx.stroke(); }
    else if (d.type === "path") { xy.forEach((p, i) => (i ? ctx.lineTo(p.x, p.y) : ctx.moveTo(p.x, p.y))); ctx.stroke(); }
    else if (d.type === "rect" && xy.length >= 2) {
      const x = Math.min(xy[0].x, xy[1].x), y = Math.min(xy[0].y, xy[1].y), w = Math.abs(xy[1].x - xy[0].x), h = Math.abs(xy[1].y - xy[0].y);
      ctx.fillStyle = alpha(d.color, 0.15); ctx.fillRect(x, y, w, h); ctx.strokeRect(x, y, w, h);
    }
    if (isSelected || preview) { ctx.fillStyle = "#ffffff"; xy.forEach((p) => { ctx.beginPath(); ctx.arc(p.x, p.y, 4, 0, Math.PI * 2); ctx.fill(); }); }
  }

  function frame() {
    const dpr = window.devicePixelRatio || 1, w = wrap.clientWidth, h = wrap.clientHeight;
    if (overlay.width !== Math.round(w * dpr) || overlay.height !== Math.round(h * dpr)) {
      overlay.width = Math.round(w * dpr); overlay.height = Math.round(h * dpr);
      overlay.style.width = w + "px"; overlay.style.height = h + "px";
    }
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);
    if (!N) { requestAnimationFrame(frame); return; }
    const right = chart.priceScale("right").width(), bottom = chart.timeScale().height();
    const W = w - right, H = h - bottom;
    ctx.save(); ctx.beginPath(); ctx.rect(0, 0, W, H); ctx.clip();
    const S = state.ind;
    if (ind.bb && S.bb.s.fill) paintBandFill(ind.bb.upper, ind.bb.lower, alpha(S.bb.s.bandColor, 0.07));
    if (ind.vwap && S.vwap.s.fill) {
      for (let b = 2; b >= 0; b--) if (S.vwap.s["band" + (b + 1)]) paintBandFill(ind.vwap.upper[b], ind.vwap.lower[b], alpha(S.vwap.s.bandColor, 0.05));
    }
    if (S.ktmi.on) {
      hLine(0, W, H * PRICE_BOTTOM + 2, "#2a2e39", 1);
      text("KTMI Uni Lite", 6, H * PRICE_BOTTOM + 16, "#9598a1");
      const ks = ktmiLines.long_speed;
      for (const [v, color] of [[L.overbought, purple], [L.upper, "#5d606b"], [L.oversold, purple]]) {
        const y = ks.priceToCoordinate(v);
        if (y !== null) label((v > 0 ? "+" : "") + v.toFixed(1), W - 2, y, color, "right");
      }
    }
    // indicators stay inside the price area (above volume and KTMI)
    ctx.save(); ctx.beginPath(); ctx.rect(0, 0, W, H * PRICE_BOTTOM - (S.volume.on ? H * 0.12 : 0)); ctx.clip();
    if (ind.smc) paintSMC(W);
    if (S.oi.on) paintOI(W);
    ctx.restore();
    for (const d of drawings) paintDrawing(d, d.id === selected, false, W, H);
    if (pending) paintDrawing(pending, false, true, W, H);
    ctx.restore();
    requestAnimationFrame(frame);
  }

  // ------------------------------------------------------------- live updates
  // The dashboard page saves fresh data every few seconds; new candles appear
  // without reloading the chart (drawings, menus and zoom stay as they are).
  if (window.KQ_DATA_URL) {
    let lastVersion = P.version;
    setInterval(() => {
      fetch(window.KQ_DATA_URL + "?t=" + Date.now(), { cache: "no-store" })
        .then((r) => (r.ok ? r.json() : null))
        .then((next) => {
          if (!next || next.version === lastVersion || !next.frames) return;
          lastVersion = next.version; P = next;
          setFrame(P.frames[state.tf] ? state.tf : String(P.default_tf), true);
          $("live").textContent = "live · " + (P.updated_at || "");
        })
        .catch(() => { $("live").textContent = "live updates paused"; });
    }, 10000);
  }

  setTool("cursor");
  setFrame(P.frames[state.tf] ? state.tf : String(P.default_tf), false);
  requestAnimationFrame(frame);
  window.KQ_CHART = { chart, drawings: () => drawings, state, setTool, setFrame, ind: () => ind, profileOf };   // for checks
})();
