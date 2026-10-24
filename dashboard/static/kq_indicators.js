// Kunal Quant chart indicators: pure maths, no drawing. Works in the browser (window.KQInd)
// and in Node (require) so the numbers can be tested.
// A "frame" is {t, o, h, l, c, v} arrays of equal length (times are IST-shifted seconds).
(function (root) {
  "use strict";

  // ---------------------------------------------------------------- helpers
  function sma(src, n) {
    const out = new Array(src.length).fill(null);
    let sum = 0;
    for (let i = 0; i < src.length; i++) {
      sum += src[i];
      if (i >= n) sum -= src[i - n];
      if (i >= n - 1) out[i] = sum / n;
    }
    return out;
  }
  function ema(src, n) {        // Pine ta.ema: seeded with the first SMA
    const out = new Array(src.length).fill(null), a = 2 / (n + 1);
    let prev = null, sum = 0;
    for (let i = 0; i < src.length; i++) {
      if (prev === null) {
        sum += src[i];
        if (i === n - 1) { prev = sum / n; out[i] = prev; }
      } else { prev = a * src[i] + (1 - a) * prev; out[i] = prev; }
    }
    return out;
  }
  function rma(src, n) {        // Pine ta.rma (SMMA)
    const out = new Array(src.length).fill(null);
    let prev = null, sum = 0;
    for (let i = 0; i < src.length; i++) {
      if (prev === null) {
        sum += src[i];
        if (i === n - 1) { prev = sum / n; out[i] = prev; }
      } else { prev = (prev * (n - 1) + src[i]) / n; out[i] = prev; }
    }
    return out;
  }
  function wma(src, n) {
    const out = new Array(src.length).fill(null), den = n * (n + 1) / 2;
    for (let i = n - 1; i < src.length; i++) {
      let s = 0;
      for (let k = 0; k < n; k++) s += src[i - k] * (n - k);
      out[i] = s / den;
    }
    return out;
  }
  function vwma(src, vol, n) {
    const pv = src.map((x, i) => x * vol[i]);
    const a = sma(pv, n), b = sma(vol, n);
    return a.map((x, i) => (x === null || !b[i] ? null : x / b[i]));
  }
  function stdev(src, n) {      // Pine ta.stdev (population, "biased")
    const out = new Array(src.length).fill(null);
    for (let i = n - 1; i < src.length; i++) {
      let m = 0;
      for (let k = 0; k < n; k++) m += src[i - k];
      m /= n;
      let s = 0;
      for (let k = 0; k < n; k++) s += (src[i - k] - m) ** 2;
      out[i] = Math.sqrt(s / n);
    }
    return out;
  }
  function source(f, name) {
    const n = f.t.length, out = new Array(n);
    for (let i = 0; i < n; i++) {
      const o = f.o[i], h = f.h[i], l = f.l[i], c = f.c[i];
      out[i] = name === "open" ? o : name === "high" ? h : name === "low" ? l : name === "close" ? c
        : name === "hl2" ? (h + l) / 2 : name === "ohlc4" ? (o + h + l + c) / 4
        : name === "hlcc4" ? (h + l + 2 * c) / 4 : (h + l + c) / 3;            // hlc3
    }
    return out;
  }
  function atr(f, n) {
    const tr = f.t.map((_, i) => (i === 0 ? f.h[i] - f.l[i]
      : Math.max(f.h[i] - f.l[i], Math.abs(f.h[i] - f.c[i - 1]), Math.abs(f.l[i] - f.c[i - 1]))));
    const out = rma(tr, Math.min(n, Math.max(1, tr.length)));
    // before the ATR is ready use the running mean of the true range
    let sum = 0;
    for (let i = 0; i < tr.length; i++) { sum += tr[i]; if (out[i] === null) out[i] = sum / (i + 1); }
    return out;
  }
  const hasVolume = (f) => f.v.some((x) => x > 0);

  // ------------------------------------------------------------------ VWAP
  const VWAP_DEFAULTS = { anchor: "Session", source: "hlc3", offset: 0, mode: "Standard Deviation",
                          band1: true, mult1: 1.0, band2: false, mult2: 2.0, band3: false, mult3: 3.0,
                          hideOnDaily: true };

  function periodKey(t, anchor) {           // t = IST-shifted seconds, read as UTC
    const d = new Date(t * 1000);
    const y = d.getUTCFullYear(), m = d.getUTCMonth();
    if (anchor === "Week") {                 // ISO week starting Monday
      const day = Math.floor(t / 86400), dow = (new Date(day * 86400000).getUTCDay() + 6) % 7;
      return "w" + (day - dow);
    }
    if (anchor === "Month") return y * 12 + m;
    if (anchor === "Quarter") return y * 4 + Math.floor(m / 3);
    if (anchor === "Year") return y;
    return Math.floor(t / 86400);             // Session = trading day
  }

  /** TradingView VWAP with up to 3 bands. Returns {vwap, upper:[3 arrays], lower:[3 arrays], equalWeights}. */
  function vwap(f, settings) {
    const s = Object.assign({}, VWAP_DEFAULTS, settings || {});
    const src = source(f, s.source), n = f.t.length;
    const useVol = hasVolume(f);
    const out = { vwap: new Array(n).fill(null), upper: [[], [], []], lower: [[], [], []], equalWeights: !useVol };
    for (let b = 0; b < 3; b++) { out.upper[b] = new Array(n).fill(null); out.lower[b] = new Array(n).fill(null); }
    let key = null, sv = 0, svv = 0, v = 0;
    const mults = [s.mult1, s.mult2, s.mult3], on = [s.band1, s.band2, s.band3];
    for (let i = 0; i < n; i++) {
      const k = periodKey(f.t[i], s.anchor);
      if (k !== key) { key = k; sv = 0; svv = 0; v = 0; }
      const w = useVol ? f.v[i] : 1;
      sv += src[i] * w; svv += src[i] * src[i] * w; v += w;
      if (v <= 0) continue;
      const mid = sv / v, sd = Math.sqrt(Math.max(svv / v - mid * mid, 0));
      const j = i + (s.offset | 0);
      if (j < 0 || j >= n) continue;
      out.vwap[j] = mid;
      for (let b = 0; b < 3; b++) {
        if (!on[b]) continue;
        const width = s.mode === "Percentage" ? mid * 0.01 * mults[b] : sd * mults[b];
        out.upper[b][j] = mid + width;
        out.lower[b][j] = mid - width;
      }
    }
    return out;
  }

  // ------------------------------------------------------------ Bollinger
  const BB_DEFAULTS = { length: 20, maType: "SMA", source: "close", mult: 2.0, offset: 0 };

  function bollinger(f, settings) {
    const s = Object.assign({}, BB_DEFAULTS, settings || {});
    const src = source(f, s.source), n = src.length, len = Math.max(1, s.length | 0);
    const basis = s.maType === "EMA" ? ema(src, len) : s.maType === "SMMA (RMA)" ? rma(src, len)
      : s.maType === "WMA" ? wma(src, len) : s.maType === "VWMA" ? vwma(src, f.v, len) : sma(src, len);
    const dev = stdev(src, len);
    const shift = (arr) => { const o = new Array(n).fill(null); for (let i = 0; i < n; i++) { const j = i + (s.offset | 0); if (j >= 0 && j < n) o[j] = arr[i]; } return o; };
    const upper = basis.map((b, i) => (b === null || dev[i] === null ? null : b + s.mult * dev[i]));
    const lower = basis.map((b, i) => (b === null || dev[i] === null ? null : b - s.mult * dev[i]));
    return { basis: shift(basis), upper: shift(upper), lower: shift(lower) };
  }

  // ------------------------------------------------- fixed range volume profile
  // TradingView "Fixed Range Volume Profile" settings (inputs + style)
  const VP_DEFAULTS = { rowsLayout: "Number Of Rows", rowSize: 24, tickSize: 0.05, volume: "Up/Down",
                        valueArea: 70, extendRight: false, showProfile: true, showValues: false,
                        width: 30, placement: "Left", showPoc: true, showVa: true, showHighLow: true,
                        developingPoc: false, developingVa: false, showLabels: false,
                        upColor: "#26a69a", downColor: "#ef5350", vaUpColor: "#26a69a", vaDownColor: "#ef5350",
                        outsideOpacity: 30, vaOpacity: 75, pocColor: "#ff1744", vahColor: "#2962ff",
                        valColor: "#2962ff", devPocColor: "#ff9800", devVaColor: "#00bcd4", highLowColor: "#d1d4dc" };

  function valueArea(totals, poc, share) {
    const total = totals.reduce((a, b) => a + b, 0), target = total * share;
    let lo = poc, hi = poc, sum = totals[poc];
    while (sum < target && (lo > 0 || hi < totals.length - 1)) {
      const up = hi < totals.length - 1 ? totals[hi + 1] : -1, down = lo > 0 ? totals[lo - 1] : -1;
      if (up >= down) { hi++; sum += up; } else { lo--; sum += down; }
    }
    return { lo, hi };
  }
  function pocIndex(totals) {
    let best = 0;
    for (let r = 1; r < totals.length; r++) if (totals[r] > totals[best]) best = r;
    return best;
  }

  /** Volume profile of bars i0..i1 of frame f. Volume of each bar is spread evenly over its high-low.
   *  Without volume (spot data only) each bar counts 1 (time profile), flagged byTime. */
  function volumeProfile(f, i0, i1, settings) {
    const s = Object.assign({}, VP_DEFAULTS, settings || {});
    if (i1 < i0) [i0, i1] = [i1, i0];
    i0 = Math.max(0, i0); i1 = Math.min(f.t.length - 1, i1);
    if (i1 < i0) return null;
    let hi = -Infinity, lo = Infinity;
    for (let i = i0; i <= i1; i++) { hi = Math.max(hi, f.h[i]); lo = Math.min(lo, f.l[i]); }
    const byTime = !f.v.slice(i0, i1 + 1).some((x) => x > 0);
    let rows = s.rowsLayout === "Ticks Per Row"
      ? Math.max(1, Math.ceil((hi - lo) / (Math.max(1, s.rowSize) * s.tickSize)))
      : Math.max(1, s.rowSize | 0);
    rows = Math.min(rows, 1000);
    const step = (hi - lo) / rows || 1;
    const up = new Array(rows).fill(0), down = new Array(rows).fill(0);
    const developing = [];
    const add = (i) => {
      const vol = byTime ? 1 : f.v[i], isUp = f.c[i] >= f.o[i];
      const a = f.l[i], b = f.h[i];
      const r0 = Math.min(rows - 1, Math.floor((a - lo) / step)), r1 = Math.min(rows - 1, Math.floor((b - lo) / step));
      for (let r = r0; r <= r1; r++) {
        const share = b > a ? (Math.min(b, lo + (r + 1) * step) - Math.max(a, lo + r * step)) / (b - a) : 1 / (r1 - r0 + 1);
        if (share <= 0) continue;
        if (isUp) up[r] += vol * share; else down[r] += vol * share;
      }
    };
    const wantDev = s.developingPoc || s.developingVa;
    for (let i = i0; i <= i1; i++) {
      add(i);
      if (wantDev) {
        const totals = up.map((x, r) => x + down[r]);
        const p = pocIndex(totals), va = valueArea(totals, p, s.valueArea / 100);
        developing.push({ t: f.t[i], poc: lo + (p + 0.5) * step, vah: lo + (va.hi + 1) * step, val: lo + va.lo * step });
      }
    }
    const totals = up.map((x, r) => x + down[r]);
    const poc = pocIndex(totals), va = valueArea(totals, poc, s.valueArea / 100);
    return {
      t0: f.t[i0], t1: f.t[i1], high: hi, low: lo, step, rows, up, down, totals, byTime,
      poc: lo + (poc + 0.5) * step, pocRow: poc, vaLow: va.lo, vaHigh: va.hi,
      vah: lo + (va.hi + 1) * step, val: lo + va.lo * step,
      totalVolume: totals.reduce((a, b) => a + b, 0), developing,
    };
  }

  // ------------------------------------------------- Smart Money Concepts
  // Same ideas as the popular LuxAlgo "Smart Money Concepts" script: market structure
  // (BOS / CHoCH, internal and swing), order blocks, fair value gaps, equal highs/lows,
  // swing points, strong/weak highs and lows, premium/discount zones.
  // Same settings groups as LuxAlgo "Smart Money Concepts": smart money, real-time internal structure,
  // real-time swing structure, order blocks, EQH/EQL, fair value gaps, highs & lows MTF, premium/discount.
  const SMC_DEFAULTS = {
    mode: "Historical", style: "Colored", colorCandles: false, showLabels: false,
    internal: true, internalFilter: "All", internalBullColor: "#089981", internalBearColor: "#f23645",
    swing: true, swingFilter: "All", swingBullColor: "#089981", swingBearColor: "#f23645",
    swingLength: 50, internalLength: 5, swingPoints: false, strongWeak: true,
    internalOB: true, internalOBCount: 5, swingOB: false, swingOBCount: 5,
    obFilter: "Atr", obMitigation: "High/Low",
    iobBullColor: "#3179f5", iobBearColor: "#f77c80", sobBullColor: "#1848cc", sobBearColor: "#b22833",
    eqhl: true, eqLength: 3, eqThreshold: 0.1,
    fvg: true, fvgAutoThreshold: true, fvgExtend: 1, fvgBullColor: "#00ff68", fvgBearColor: "#ff0008",
    dailyLevels: false, dailyColor: "#2157f3", weeklyLevels: false, weeklyColor: "#2157f3",
    monthlyLevels: false, monthlyColor: "#2157f3",
    premiumDiscount: false, premiumColor: "#f23645", equilibriumColor: "#878b94", discountColor: "#089981",
  };

  function pivots(f, len) {
    // LuxAlgo "leg": a new high leg starts when the bar `len` ago is above the next `len` bars.
    const n = f.t.length, highs = [], lows = [];
    let leg = null;
    for (let i = len; i < n; i++) {
      let maxH = -Infinity, minL = Infinity;
      for (let k = i - len + 1; k <= i; k++) { maxH = Math.max(maxH, f.h[k]); minL = Math.min(minL, f.l[k]); }
      const p = i - len;
      let newLeg = leg;
      if (f.h[p] > maxH) newLeg = 0;            // bearish leg starts: pivot HIGH at p
      else if (f.l[p] < minL) newLeg = 1;       // bullish leg starts: pivot LOW at p
      if (newLeg !== leg && newLeg !== null) {
        if (newLeg === 0) highs.push({ idx: p, price: f.h[p], at: i });
        else lows.push({ idx: p, price: f.l[p], at: i });
      }
      leg = newLeg;
    }
    return { highs, lows };
  }

  function smc(f, settings) {
    const s = Object.assign({}, SMC_DEFAULTS, settings || {});
    const n = f.t.length;
    const out = { structures: [], orderBlocks: [], fvgs: [], equal: [], swings: [], strongWeak: null, zones: null,
                  levels: [], trend: new Array(n).fill(0) };
    if (n < 3) return out;
    // volatility for the order block filter: ATR(200) or the cumulative mean range
    let vol = atr(f, 200);
    if (s.obFilter === "Cumulative Mean Range") {
      let sum = 0;
      vol = f.t.map((_, i) => { sum += f.h[i] - f.l[i]; return sum / (i + 1); });
    }

    function structure(len, internal) {
      const pv = pivots(f, len);
      const events = [];
      const byBar = new Map();
      for (const h of pv.highs) { if (!byBar.has(h.at)) byBar.set(h.at, []); byBar.get(h.at).push({ type: "H", ...h }); }
      for (const l of pv.lows) { if (!byBar.has(l.at)) byBar.set(l.at, []); byBar.get(l.at).push({ type: "L", ...l }); }
      let top = null, bottom = null, trend = 0;          // 1 bull, -1 bear
      let lastTop = null, lastBottom = null;
      for (let i = 0; i < n; i++) {
        for (const p of byBar.get(i) || []) {
          if (p.type === "H") {
            if (!internal && s.swingPoints) out.swings.push({ idx: p.idx, price: p.price, label: lastTop === null || p.price > lastTop ? "HH" : "LH", high: true });
            lastTop = p.price; top = { price: p.price, idx: p.idx, crossed: false };
          } else {
            if (!internal && s.swingPoints) out.swings.push({ idx: p.idx, price: p.price, label: lastBottom === null || p.price < lastBottom ? "LL" : "HL", high: false });
            lastBottom = p.price; bottom = { price: p.price, idx: p.idx, crossed: false };
          }
        }
        if (top && !top.crossed && f.c[i] > top.price) {
          const tag = trend === -1 ? "CHoCH" : "BOS";
          trend = 1; top.crossed = true;
          events.push({ from: top.idx, to: i, price: top.price, label: tag, bull: true, internal });
          orderBlock(top.idx, i, true, internal);
        }
        if (bottom && !bottom.crossed && f.c[i] < bottom.price) {
          const tag = trend === 1 ? "CHoCH" : "BOS";
          trend = -1; bottom.crossed = true;
          events.push({ from: bottom.idx, to: i, price: bottom.price, label: tag, bull: false, internal });
          orderBlock(bottom.idx, i, false, internal);
        }
        if (internal) out.trend[i] = trend;          // candle colouring follows the internal trend
      }
      return { events, trend, pv };
    }

    function orderBlock(from, to, bull, internal) {
      if ((internal && !s.internalOB) || (!internal && !s.swingOB)) return;
      // volatile bars (range >= 2 x ATR) have high/low swapped, as in LuxAlgo, so they rarely become blocks
      let best = -1;
      for (let k = from; k < to; k++) {
        const big = f.h[k] - f.l[k] >= 2 * vol[k];
        const lowK = big ? f.h[k] : f.l[k], highK = big ? f.l[k] : f.h[k];
        if (best < 0) { best = k; continue; }
        const bigB = f.h[best] - f.l[best] >= 2 * vol[best];
        const lowB = bigB ? f.h[best] : f.l[best], highB = bigB ? f.l[best] : f.h[best];
        if (bull ? lowK < lowB : highK > highB) best = k;
      }
      if (best < 0) return;
      const bigB = f.h[best] - f.l[best] >= 2 * vol[best];
      const top = bigB ? f.l[best] : f.h[best], bottom = bigB ? f.h[best] : f.l[best];
      out.orderBlocks.push({ idx: best, created: to, top: Math.max(top, bottom), bottom: Math.min(top, bottom),
                             bull, internal, end: null });
    }

    const swingRes = structure(Math.max(3, s.swingLength | 0), false);
    let internalRes = { events: [] };
    if (s.internal || s.internalOB) {
      internalRes = structure(Math.max(2, s.internalLength | 0), true);
      // an internal break at the same level as a swing break is shown once, as the swing one
      const swingLevels = new Set(swingRes.events.map((e) => e.price));
      internalRes.events = internalRes.events.filter((e) => !swingLevels.has(e.price));
    }
    const keep = (e, filter) => filter === "All" || e.label === filter;
    if (s.swing) out.structures.push(...swingRes.events.filter((e) => keep(e, s.swingFilter)));
    if (s.internal) out.structures.push(...internalRes.events.filter((e) => keep(e, s.internalFilter)));

    // order block mitigation
    for (const ob of out.orderBlocks) {
      for (let i = ob.created + 1; i < n; i++) {
        const lowP = s.obMitigation === "Close" ? f.c[i] : f.l[i], highP = s.obMitigation === "Close" ? f.c[i] : f.h[i];
        if (ob.bull ? lowP < ob.bottom : highP > ob.top) { ob.end = i; break; }
      }
    }
    const liveOB = (internal, count) => out.orderBlocks.filter((o) => o.internal === internal && o.end === null).slice(-count);
    // like LuxAlgo: only blocks not yet mitigated, the newest N of each kind
    out.orderBlocks = [...(s.internalOB ? liveOB(true, s.internalOBCount) : []),
                       ...(s.swingOB ? liveOB(false, s.swingOBCount) : [])];

    // fair value gaps (3 candles); auto threshold = 2 x running mean of |bar change %|
    if (s.fvg) {
      let cum = 0;
      for (let i = 2; i < n; i++) {
        const deltaPct = Math.abs((f.c[i - 1] - f.o[i - 1]) / f.o[i - 1] * 100);
        cum += deltaPct;
        const threshold = s.fvgAutoThreshold ? (cum / (i - 1)) * 2 : 0;
        if (f.l[i] > f.h[i - 2] && f.c[i - 1] > f.h[i - 2] && deltaPct > threshold)
          out.fvgs.push({ idx: i - 1, top: f.l[i], bottom: f.h[i - 2], bull: true, end: null });
        if (f.h[i] < f.l[i - 2] && f.c[i - 1] < f.l[i - 2] && deltaPct > threshold)
          out.fvgs.push({ idx: i - 1, top: f.l[i - 2], bottom: f.h[i], bull: false, end: null });
      }
      for (const g of out.fvgs) {
        for (let i = g.idx + 2; i < n; i++) {
          if (g.bull ? f.l[i] < g.bottom : f.h[i] > g.top) { g.end = i; break; }
        }
      }
      out.fvgs = out.fvgs.filter((g) => g.end === null);
    }

    // equal highs / lows
    if (s.eqhl) {
      const pv = pivots(f, Math.max(1, s.eqLength | 0));
      for (const [list, label] of [[pv.highs, "EQH"], [pv.lows, "EQL"]]) {
        for (let k = 1; k < list.length; k++) {
          const a = list[k - 1], b = list[k];
          if (Math.abs(a.price - b.price) < s.eqThreshold * vol[b.idx])
            out.equal.push({ from: a.idx, to: b.idx, price: b.price, label, high: label === "EQH" });
        }
      }
    }

    // strong / weak high and low, premium / discount
    const lastHigh = swingRes.pv.highs[swingRes.pv.highs.length - 1], lastLow = swingRes.pv.lows[swingRes.pv.lows.length - 1];
    if (lastHigh || lastLow) {
      let topIdx = lastHigh ? lastHigh.idx : 0, bottomIdx = lastLow ? lastLow.idx : 0;
      const startTop = topIdx, startBottom = bottomIdx;
      let top = f.h[topIdx], bottom = f.l[bottomIdx];
      for (let i = Math.min(startTop, startBottom); i < n; i++) {
        if (i >= startTop && f.h[i] > top) { top = f.h[i]; topIdx = i; }
        if (i >= startBottom && f.l[i] < bottom) { bottom = f.l[i]; bottomIdx = i; }
      }
      out.strongWeak = { top, topIdx, bottom, bottomIdx,
                         topLabel: swingRes.trend === -1 ? "Strong High" : "Weak High",
                         bottomLabel: swingRes.trend === 1 ? "Strong Low" : "Weak Low" };
      out.zones = { from: Math.min(topIdx, bottomIdx), top, bottom,
                    premium: [top, 0.95 * top + 0.05 * bottom], equilibrium: [0.525 * top + 0.475 * bottom, 0.525 * bottom + 0.475 * top],
                    discount: [0.95 * bottom + 0.05 * top, bottom] };
    }
    // previous day / week / month high and low (LuxAlgo "Highs & Lows MTF")
    const periodLevels = (anchor, on, short, color) => {
      if (!on) return;
      let key = null, hi = -Infinity, lo = Infinity, prev = null, start = 0;
      for (let i = 0; i < n; i++) {
        const k = periodKey(f.t[i], anchor);
        if (k !== key) {
          if (key !== null) prev = { hi, lo };
          key = k; hi = -Infinity; lo = Infinity; start = i;
        }
        hi = Math.max(hi, f.h[i]); lo = Math.min(lo, f.l[i]);
      }
      if (prev) {
        out.levels.push({ from: start, price: prev.hi, label: "P" + short + "H", color, high: true });
        out.levels.push({ from: start, price: prev.lo, label: "P" + short + "L", color, high: false });
      }
    };
    periodLevels("Session", s.dailyLevels, "D", s.dailyColor);
    periodLevels("Week", s.weeklyLevels, "W", s.weeklyColor);
    periodLevels("Month", s.monthlyLevels, "M", s.monthlyColor);
    if (s.mode === "Present") {
      out.structures = out.structures.filter((e) => e.to >= n - 1 - Math.max(50, s.swingLength * 2));
    }
    return out;
  }

  const api = { sma, ema, rma, wma, stdev, atr, source, vwap, bollinger, volumeProfile, smc,
                VWAP_DEFAULTS, BB_DEFAULTS, VP_DEFAULTS, SMC_DEFAULTS };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.KQInd = api;
})(typeof window !== "undefined" ? window : globalThis);
