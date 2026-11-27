/* 기준선 차트 (TradingView Lightweight Charts v5, CDN 버전 고정).
 * 위 패널: QQQ(또는 TQQQ) 종가 · 50/200일선 · 상태 배경 띠 · 기준 가로선 다섯 개
 * 아래 패널: RSI2 (0~100 고정, 5·15·50 가로선, 0~15 사냥 구역)
 * 판정은 하지 않는다. app.js 가 넘겨 준 값(chart.json 줄 + 지금/예상 점 + 가로선 가격)을 그리기만 한다.
 * 라이브러리를 못 불러오면 onFail() 을 부르고 끝 (화면의 나머지는 그대로). */
var TQHD_CHART = (function () {
  "use strict";

  var VERSION = "5.2.1";
  var CDN = "https://cdn.jsdelivr.net/npm/lightweight-charts@" + VERSION + "/dist/lightweight-charts.standalone.production.js";
  var SRI = "sha384-KkYqTZlM13Zya6fVUF3IGCBOQ1ehFeJVVgxaVvD/0MebineF9EI8Jkd3NnWNChqN";
  var LOAD_TIMEOUT = 12000;

  var BG = "#16191f", TEXT = "#ecebe8", MUTED = "#858a94";
  var C50 = "#e0b44c", C200 = "#6f8cff", HUNT = "#ff9a5c", HUNT_FULL = "#ff7a45";
  var BAND = { day: "rgba(125,109,54,0.18)", night: "rgba(51,58,102,0.18)", hunt50: "rgba(125,70,40,0.18)", hunt100: "rgba(176,88,44,0.18)" };
  var RANGE_BARS = { "3m": 63, "6m": 126, "1y": 252 };
  var EMOJI = { day: "☀️", night: "🌙", hunt: "🏹" };
  var WD = ["일", "월", "화", "수", "목", "금", "토"];
  var VIEW_KEY = "tqhd.chartView", RANGE_KEY = "tqhd.chartRange";

  function load(key, def, ok) { try { var v = localStorage.getItem(key); return ok.indexOf(v) >= 0 ? v : def; } catch (e) { return def; } }
  function save(key, v) { try { localStorage.setItem(key, v); } catch (e) { /* 저장 못 해도 동작은 그대로 */ } }

  var view = load(VIEW_KEY, "qqq", ["qqq", "tqqq"]);
  var range = load(RANGE_KEY, "6m", ["3m", "6m", "1y"]);

  var L = null, el = {}, chart = null, S = {}, failed = false, loading = null, onFail = null;
  var sig = null, ctx = null, rowsN = 0, lines = [], rsiLines = [], layoutQueued = false, bandLast = null;

  // ── 라이브러리 불러오기 (실패해도 사이트는 그대로) ──
  function loadLib(url) {
    if (window.LightweightCharts) return Promise.resolve(window.LightweightCharts);
    return new Promise(function (resolve, reject) {
      var s = document.createElement("script"), done = false;
      var timer = setTimeout(function () { if (!done) { done = true; reject(new Error("timeout")); } }, LOAD_TIMEOUT);
      s.src = url;
      if (url === CDN) { s.integrity = SRI; s.crossOrigin = "anonymous"; }
      s.onload = function () {
        if (done) return; done = true; clearTimeout(timer);
        window.LightweightCharts ? resolve(window.LightweightCharts) : reject(new Error("no global"));
      };
      s.onerror = function () { if (done) return; done = true; clearTimeout(timer); reject(new Error("load error")); };
      document.head.appendChild(s);
    });
  }

  function fail() {
    failed = true;
    if (onFail) onFail();
  }

  /* opts: { el, legendEl, tipEl, noteEl, onFail, badUrl } */
  function init(opts) {
    el = opts; onFail = opts.onFail;
    loading = loadLib(opts.badUrl || CDN).then(function (lib) {
      L = lib;
      try { build(); } catch (e) { fail(); return; }
      if (ctx) draw(true);
    }, fail);
  }

  // ── 차트 만들기 ───────────────────────────
  function fontVar() {
    var f = getComputedStyle(document.documentElement).getPropertyValue("--font");
    return (f && f.trim()) || "system-ui, sans-serif";
  }

  function build() {
    chart = L.createChart(el.el, {
      autoSize: true,
      layout: { background: { type: "solid", color: BG }, textColor: MUTED, fontSize: 11, fontFamily: fontVar(), attributionLogo: true,
                panes: { separatorColor: "#252932", separatorHoverColor: "#2c3038", enableResize: false } },
      grid: { vertLines: { color: "rgba(255,255,255,0.03)" }, horzLines: { color: "rgba(255,255,255,0.035)" } },
      rightPriceScale: { borderColor: "#252932", minimumWidth: 58 },
      timeScale: { borderColor: "#252932", rightOffset: 2, minBarSpacing: 1.2 },
      crosshair: { mode: L.CrosshairMode.Normal, vertLine: { color: "rgba(236,235,232,0.25)", labelBackgroundColor: "#262a33" },
                   horzLine: { color: "rgba(236,235,232,0.25)", labelBackgroundColor: "#262a33" } },
      handleScroll: { mouseWheel: true, pressedMouseMove: true, horzTouchDrag: true, vertTouchDrag: false },
      handleScale: { mouseWheel: true, pinch: true, axisPressedMouseMove: { time: true, price: false }, axisDoubleClickReset: true },
      localization: { locale: "ko-KR" }
    });

    var helper = { lastValueVisible: false, priceLineVisible: false, crosshairMarkerVisible: false };
    function dot(color, radius, pane, extra) {
      return chart.addSeries(L.LineSeries, Object.assign({ color: color, lineVisible: false, pointMarkersVisible: true, pointMarkersRadius: radius }, helper, extra || {}), pane);
    }

    // 위 패널
    S.band = {};
    Object.keys(BAND).forEach(function (k) {
      S.band[k] = chart.addSeries(L.AreaSeries, Object.assign({ priceScaleId: "bg", lineVisible: false, lineColor: "rgba(0,0,0,0)",
        lineType: L.LineType.WithSteps,
        topColor: BAND[k], bottomColor: BAND[k],
        autoscaleInfoProvider: function () { return { priceRange: { minValue: 0, maxValue: 1 } }; } }, helper));
    });
    chart.priceScale("bg", 0).applyOptions({ scaleMargins: { top: 0, bottom: 0 }, visible: false });
    S.main = chart.addSeries(L.LineSeries, { color: TEXT, lineWidth: 2, priceLineVisible: false, lastValueVisible: true,
      priceFormat: { type: "price", precision: 2, minMove: 0.01 },
      crosshairMarkerRadius: 3, autoscaleInfoProvider: withLines });
    S.sma50 = chart.addSeries(L.LineSeries, Object.assign({ color: C50, lineWidth: 1.5 }, helper));
    S.sma200 = chart.addSeries(L.LineSeries, Object.assign({ color: C200, lineWidth: 1.5 }, helper));
    S.proj = chart.addSeries(L.LineSeries, Object.assign({ color: MUTED, lineWidth: 1, lineStyle: L.LineStyle.Dotted }, helper));
    S.ring = dot(TEXT, 5, 0); S.ringIn = dot(BG, 3, 0);     // 속 빈 마커 (예상 시가)
    S.today = dot(TEXT, 4, 0);                               // 오늘 실시간 점

    // 아래 패널 (RSI2)
    var fixed = { autoscaleInfoProvider: function () { return { priceRange: { minValue: 0, maxValue: 100 } }; },
                  priceFormat: { type: "price", precision: 0, minMove: 1 } };
    S.z15 = chart.addSeries(L.AreaSeries, Object.assign({ lineVisible: false, lineColor: "rgba(0,0,0,0)", topColor: "rgba(255,154,92,0.10)",
      bottomColor: "rgba(255,154,92,0.10)" }, helper, fixed), 1);
    S.z5 = chart.addSeries(L.AreaSeries, Object.assign({ lineVisible: false, lineColor: "rgba(0,0,0,0)", topColor: "rgba(255,122,69,0.16)",
      bottomColor: "rgba(255,122,69,0.16)" }, helper, fixed), 1);
    S.rsi = chart.addSeries(L.LineSeries, Object.assign({ color: TEXT, lineWidth: 1.5, priceLineVisible: false, lastValueVisible: false,
      crosshairMarkerRadius: 3 }, fixed), 1);
    S.rsiProj = chart.addSeries(L.LineSeries, Object.assign({ color: MUTED, lineWidth: 1, lineStyle: L.LineStyle.Dotted }, helper, fixed), 1);
    S.rsiRing = dot(TEXT, 4, 1, fixed); S.rsiRingIn = dot(BG, 2.5, 1, fixed);
    S.rsiToday = dot(TEXT, 3.5, 1, fixed);
    chart.priceScale("right", 1).applyOptions({ scaleMargins: { top: 0.06, bottom: 0.04 } });
    [[5, "", HUNT_FULL, false], [15, "절반 15 · 전액 5", HUNT, true], [50, "청산 50", MUTED, true]].forEach(function (x) {
      rsiLines.push(S.rsi.createPriceLine({ price: x[0], color: x[2], lineWidth: 1, lineStyle: L.LineStyle.Dotted, axisLabelVisible: x[3],
        title: x[1], axisLabelColor: x[2], axisLabelTextColor: BG }));
    });
    var panes = chart.panes();
    if (panes[1]) panes[1].setHeight(100);

    chart.subscribeCrosshairMove(tip);
    chart.timeScale().subscribeVisibleLogicalRangeChange(queueLayout);
  }

  /* 위 패널 자동 범위에 가로선 가격도 넣는다 (멀리 있는 사냥선도 보이게) */
  function withLines(original) {
    var r = original();
    if (!r || !ctx) return r;
    var lo = r.priceRange.minValue, hi = r.priceRange.maxValue;
    ctx.lines.forEach(function (l) { var p = view === "tqqq" ? l.tqqq : l.qqq; if (isFinite(p)) { lo = Math.min(lo, p); hi = Math.max(hi, p); } });
    r.priceRange = { minValue: lo, maxValue: hi };
    return r;
  }

  // ── 그리기 ────────────────────────────────
  function val(row) { return view === "tqqq" ? row.tqqq : row.qqq; }
  function bandKey(s, w) { return s === "hunt" ? (w === 100 ? "hunt100" : "hunt50") : s; }
  /* 날마다 그날 상태 색: 상태마다 계단 모양 면 하나 (그 상태인 날 1, 아니면 0) → 구간 경계가 곧게 끊긴다 */
  function setBand(rows) {
    var keys = rows.map(function (r) { return bandKey(r.state, r.weight); });
    Object.keys(S.band).forEach(function (k) {
      S.band[k].setData(rows.map(function (r, i) { return { time: r.date, value: keys[i] === k ? 1 : 0 }; }));
    });
    bandLast = keys.length ? keys[keys.length - 1] : null;
  }

  /* ctx: { rows, asOf, live, gap, lines, curState } */
  function update(c) {
    ctx = c;
    if (failed || !chart) return;
    draw(false);
  }

  function signature(c) {
    return [c.asOf, c.rows.length, view, c.live ? "L" + c.live.date : "", c.gap ? "G" + c.gap.date + ":" + c.gap.qqq.toFixed(2) : ""].join("|");
  }

  function draw(force) {
    var c = ctx, s = signature(c);
    if (force || s !== sig) { full(c); sig = s; applyRange(); }
    else live(c);
    queueLayout();
  }

  function full(c) {
    var rows = c.rows.filter(function (r) { return val(r) != null; });
    setBand(rows);
    S.main.setData(rows.map(function (r) { return { time: r.date, value: val(r) }; }));
    var q = view === "qqq";
    S.sma50.applyOptions({ visible: q }); S.sma200.applyOptions({ visible: q });
    S.sma50.setData(rows.map(function (r) { return { time: r.date, value: r.sma50 }; }));
    S.sma200.setData(rows.map(function (r) { return { time: r.date, value: r.sma200 }; }));
    S.rsi.setData(rows.map(function (r) { return { time: r.date, value: r.rsi2 }; }));
    var times = rows.map(function (r) { return r.date; });
    if (c.gap) times.push(c.gap.date);
    S.z15.setData(times.map(function (t) { return { time: t, value: 15 }; }));
    S.z5.setData(times.map(function (t) { return { time: t, value: 5 }; }));
    [S.today, S.rsiToday, S.proj, S.ring, S.ringIn, S.rsiProj, S.rsiRing, S.rsiRingIn].forEach(function (x) { x.setData([]); });

    var last = rows[rows.length - 1];
    if (c.gap && last) {                                   // 휴장·개장 전: 다음 개장일 자리에 예상 시가 (속 빈 마커 + 점선)
      var gv = view === "tqqq" ? c.gap.tqqq : c.gap.qqq;
      S.proj.setData([{ time: last.date, value: val(last) }, { time: c.gap.date, value: gv }]);
      S.ring.setData([{ time: c.gap.date, value: gv }]); S.ringIn.setData([{ time: c.gap.date, value: gv }]);
      S.rsiProj.setData([{ time: last.date, value: last.rsi2 }, { time: c.gap.date, value: c.gap.rsi2 }]);
      S.rsiRing.setData([{ time: c.gap.date, value: c.gap.rsi2 }]); S.rsiRingIn.setData([{ time: c.gap.date, value: c.gap.rsi2 }]);
    }
    rowsN = rows.length + (c.gap ? 1 : 0);
    if (c.live) { live(c); rowsN = rows.length + 1; }
  }

  /* 장중: 오늘 점만 series.update 로 붙이거나 고친다 (30초마다) */
  function live(c) {
    var x = c.live;
    if (!x) return;
    var p = view === "tqqq" ? x.tqqq : x.qqq;
    S.main.update({ time: x.date, value: p });
    Object.keys(S.band).forEach(function (k) { S.band[k].update({ time: x.date, value: k === bandLast ? 1 : 0 }); });   // 어제 상태 띠를 오늘까지
    S.sma50.update({ time: x.date, value: x.sma50 });
    S.sma200.update({ time: x.date, value: x.sma200 });
    S.rsi.update({ time: x.date, value: x.rsi2 });
    S.z15.update({ time: x.date, value: 15 }); S.z5.update({ time: x.date, value: 5 });
    S.today.update({ time: x.date, value: p });
    S.rsiToday.update({ time: x.date, value: x.rsi2 });
  }

  function applyRange() {
    var n = RANGE_BARS[range] || 126;
    chart.timeScale().setVisibleLogicalRange({ from: Math.max(0, rowsN - n), to: rowsN - 1 + 2 });
  }

  // ── 기준 가로선 다섯 개 (가까운 라벨은 하나로 합친다) ──
  function queueLayout() {
    if (layoutQueued || !chart) return;
    layoutQueued = true;
    requestAnimationFrame(function () { layoutQueued = false; drawLines(); });
  }

  var STYLE = {
    sma50: { color: C50, dash: "Solid" }, sma200: { color: C200, dash: "Solid" },
    hunt_half: { color: HUNT, dash: "Dotted" }, hunt_full: { color: HUNT_FULL, dash: "Dotted" }, hunt_exit: { color: MUTED, dash: "Dotted" }
  };
  function pct1(x) { if (x == null || !isFinite(x)) return "–"; var v = x * 100; return (v > 0 ? "+" : v < 0 ? "−" : "") + Math.abs(v).toFixed(1) + "%"; }
  function fade(hex, a) {
    var n = parseInt(hex.slice(1), 16);
    return "rgba(" + (n >> 16) + "," + ((n >> 8) & 255) + "," + (n & 255) + "," + a + ")";
  }

  function drawLines() {
    if (!ctx || !chart) return;
    lines.forEach(function (pl) { S.main.removePriceLine(pl); });
    lines = [];
    var q = view === "qqq", dim = ctx.curState === "day";
    var items = ctx.lines.map(function (l) {
      var price = q ? l.qqq : l.tqqq;
      return { l: l, price: price, y: S.main.priceToCoordinate(price) };
    }).filter(function (it) { return isFinite(it.price); });

    // 지금 가격 라벨 자리도 비워 둔다
    var lastY = null, data = S.main.data();
    if (data.length) lastY = S.main.priceToCoordinate(data[data.length - 1].value);

    var hideLast = false;
    items.sort(function (a, b) { return (a.y == null ? 1e9 : a.y) - (b.y == null ? 1e9 : b.y); });
    var groups = [];
    items.forEach(function (it) {
      var g = groups[groups.length - 1];
      if (g && it.y != null && g.y != null && Math.abs(it.y - g.y) < 15) g.items.push(it);
      else groups.push({ y: it.y, items: [it] });
    });

    groups.forEach(function (g) {
      g.items.forEach(function (it, i) {
        var l = it.l, st = STYLE[l.key], hunt = l.key.indexOf("hunt") === 0;
        var color = hunt && dim ? fade(st.color, 0.35) : st.color;
        var title = "";
        if (i === 0) {
          if (g.items.length === 1) {
            title = q ? l.name + " T$" + l.tqqq.toFixed(2) + " " + pct1(l.tPct)
                      : l.name + " " + pct1(l.tPct) + " Q$" + l.qqq.toFixed(2);
          } else {
            title = g.items.map(function (x) { return x.l.name; }).join("·");     // 가까운 선은 이름만 합친다
          }
        }
        if (i === 0 && lastY != null && it.y != null && Math.abs(it.y - lastY) < 15) hideLast = true;
        lines.push(S.main.createPriceLine({
          price: it.price, color: color, lineWidth: 1, lineStyle: L.LineStyle[st.dash],
          axisLabelVisible: i === 0, title: title,
          axisLabelColor: color, axisLabelTextColor: BG
        }));
      });
    });
    S.main.applyOptions({ lastValueVisible: !hideLast });   // 지금 값은 둥근 점 · 맨 위 가격 칸 · 툴팁에 있음
    legend();
  }

  // ── 범례 · 툴팁 ───────────────────────────
  function legend() {
    if (!el.legendEl) return;
    el.legendEl.innerHTML = view === "qqq"
      ? '<span style="color:' + TEXT + '">— QQQ</span><span style="color:' + C50 + '">— 50일선</span><span style="color:' + C200 + '">— 200일선</span>'
      : '<span style="color:' + TEXT + '">— TQQQ</span>';
    if (el.noteEl) el.noteEl.hidden = view !== "tqqq";
  }

  function tstr(t) {
    if (typeof t === "string") return t;
    if (t && typeof t === "object" && t.year) return t.year + "-" + ("0" + t.month).slice(-2) + "-" + ("0" + t.day).slice(-2);
    if (typeof t === "number") return new Date(t * 1000).toISOString().slice(0, 10);
    return null;
  }
  function usd(x) { return x == null || !isFinite(x) ? "–" : "$" + x.toFixed(2); }
  function word(s, w) { return s === "day" ? "낮" : s === "night" ? "밤" : s === "hunt" ? "사냥 " + w + "%" : "–"; }

  function tip(param) {
    var box = el.tipEl;
    if (!box || !ctx) return;
    var d = param && param.point && tstr(param.time);
    if (!d) { box.hidden = true; return; }
    var r = null, kind = "";
    if (ctx.live && d === ctx.live.date) { r = ctx.live; kind = "지금"; r = { date: d, qqq: r.qqq, tqqq: r.tqqq, sma50: r.sma50, sma200: r.sma200, rsi2: r.rsi2, state: r.state, weight: r.weight }; }
    else if (ctx.gap && d === ctx.gap.date) { r = { date: d, qqq: ctx.gap.qqq, tqqq: ctx.gap.tqqq, sma50: null, sma200: null, rsi2: ctx.gap.rsi2, state: ctx.gap.state, weight: ctx.gap.weight }; kind = "예상"; }
    else for (var i = ctx.rows.length - 1; i >= 0; i--) if (ctx.rows[i].date === d) { r = ctx.rows[i]; break; }
    if (!r) { box.hidden = true; return; }
    var dt = new Date(d + "T12:00:00Z");
    box.innerHTML = '<div class="th1"><span class="num">' + (dt.getUTCMonth() + 1) + "/" + dt.getUTCDate() + "(" + WD[dt.getUTCDay()] + ")</span>" +
      (kind ? ' <span class="k">' + kind + "</span>" : "") + " · " + (EMOJI[r.state] || "") + " " + word(r.state, r.weight) + "</div>" +
      '<div class="num">TQQQ ' + usd(r.tqqq) + " · QQQ " + usd(r.qqq) + "</div>" +
      '<div class="num">50일 ' + usd(r.sma50) + " · 200일 " + usd(r.sma200) + " · RSI2 " + (r.rsi2 == null ? "–" : r.rsi2.toFixed(1)) + "</div>";
    box.hidden = false;
  }

  // ── 조작 ──────────────────────────────────
  function setView(v) { if (v === view) return; view = v; save(VIEW_KEY, v); if (chart && ctx) draw(true); else legend(); }
  function setRange(r) { if (r === range) return; range = r; save(RANGE_KEY, r); if (chart) applyRange(); }

  return {
    VERSION: VERSION, CDN: CDN, init: init, update: update, setView: setView, setRange: setRange,
    view: function () { return view; }, range: function () { return range; }, failed: function () { return failed; }
  };
})();
