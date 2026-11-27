/* 화면 그리기만 한다. 판정은 core.js (TQHD), 문구는 ui.js (TQHD_UI).
 * 순서: ① 가격 → ② 지금 상태 → ③ 기준선 → ④ 흐름 → ⑤ 휴장 갭 → ⑥ 각오 (TQQQ 는 언제나 QQQ 보다 먼저) */
(function () {
  "use strict";
  var T = window.TQHD, U = window.TQHD_UI, cfg = window.TQHD_CONFIG || {};
  var POLL_MS = 30 * 1000, STATE_MS = 10 * 60 * 1000, FETCH_TIMEOUT = 10 * 1000;

  // localhost 에서만: ?now=ISO 로 시계 바꾸기, ?quotes=URL 로 가짜 시세
  var local = /^(localhost|127\.0\.0\.1)$/.test(location.hostname);
  var qs = new URLSearchParams(location.search);
  var fakeNow = local && qs.get("now") ? Date.parse(qs.get("now")) : null;
  var t0 = Date.now();
  function now() { return fakeNow != null ? fakeNow + (Date.now() - t0) : Date.now(); }
  var proxyUrl = local ? (qs.get("quotes") || "/quotes") : (cfg.proxyUrl || "");

  var state = null, quotes = null, lastTry = null, lastOk = null, stateErr = null;
  var $ = function (id) { return document.getElementById(id); };

  // 기준선 % 기준 (장중에만 고를 수 있음): "ref" = 현재가 대비, "prev" = 전일 종가 대비
  var BASIS_KEY = "tqhd.basis";
  var basis = (function () { try { return localStorage.getItem(BASIS_KEY) === "prev" ? "prev" : "ref"; } catch (e) { return "ref"; } })();
  function setBasis(b) { basis = b; try { localStorage.setItem(BASIS_KEY, b); } catch (e) { /* 저장 못 해도 화면은 그대로 */ } }

  // ── 아이콘 (인라인 SVG 다섯 개) ───────────
  function svg(d) { return '<svg class="ico" viewBox="0 0 16 16" aria-hidden="true">' + d + "</svg>"; }
  var ICON = {
    fx: svg('<path d="M2.5 5.5h10l-2.5-2.5"/><path d="M13.5 10.5h-10l2.5 2.5"/>'),
    fut: svg('<path d="M2 12.5l3.5-3.5 3 2L14 4.5"/><path d="M10.5 4.5H14V8"/>'),
    ma: svg('<path d="M2 6h12"/><path d="M2 10.5h12"/>'),
    rsi: svg('<path d="M3 13V9.5"/><path d="M6.3 13V5"/><path d="M9.7 13V7.5"/><path d="M13 13V3"/>'),
    clock: svg('<circle cx="8" cy="8" r="6"/><path d="M8 4.8V8l2.3 1.4"/>')
  };

  // ── 숫자 표기 ─────────────────────────────
  function N(s) { return '<span class="num">' + s + "</span>"; }
  function usd(x, d) { return x == null || !isFinite(x) ? "–" : "$" + x.toLocaleString("en-US", { minimumFractionDigits: d == null ? 2 : d, maximumFractionDigits: d == null ? 2 : d }); }
  function num(x, d) { return x == null || !isFinite(x) ? "–" : x.toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d }); }
  function pct(x) { if (x == null || !isFinite(x)) return "–"; var v = x * 100; return (v > 0 ? "+" : v < 0 ? "−" : "") + Math.abs(v).toFixed(2) + "%"; }
  function arrowPct(x) { return (x > 0 ? "↑ " : x < 0 ? "↓ " : "") + pct(x); }
  function cls(x) { return x > 0 ? "up" : x < 0 ? "down" : ""; }
  var WD = ["일", "월", "화", "수", "목", "금", "토"];
  function kstDay(t) { var d = new Date(t + 9 * 3600e3); return (d.getUTCMonth() + 1) + "/" + d.getUTCDate() + "(" + WD[d.getUTCDay()] + ")"; }
  function kstHM(t) { return T.fmtKst(t, false); }
  function when(t) { if (t == null) return "–"; return kstDay(t) === kstDay(now()) ? kstHM(t) : T.fmtKst(t); }
  function left(ms) { var m = Math.max(0, Math.round(ms / 60000)); return (m >= 60 ? Math.floor(m / 60) + "시간 " : "") + (m % 60) + "분"; }
  function md(iso) { return iso.slice(5).replace("-", "/"); }
  function isEarly(s) { return s && Date.parse(s.close_utc) - Date.parse(s.open_utc) < 6.5 * 3600e3 - 1; }
  function em(s) { return U.EMOJI[s] || ""; }
  function isLive(v) { return v.mode === "live" || v.mode === "closed"; }

  // ── 마스코트 (상태 배너에만, 한 장만 받는다) ──
  var mascotState = null, mascotFailed = {};
  (function () {
    var img = $("mascotImg");
    img.addEventListener("load", function () { if (mascotState) $("mascot").hidden = false; });
    img.addEventListener("error", function () { if (mascotState) mascotFailed[mascotState] = true; $("mascot").hidden = true; });
  })();
  function mascot(s) {
    var pic = $("mascot");
    if (!s || mascotFailed[s]) { pic.hidden = true; mascotState = s; return; }
    if (s === mascotState) return;
    mascotState = s;
    $("mascotWebp").srcset = "assets/mascot-" + s + ".webp";
    $("mascotImg").src = "assets/mascot-" + s + ".png";
  }

  // ── ① 가격 (TQQQ 왼쪽, QQQ 오른쪽) ─────────
  /* 확정 종가 하루 전 값 (recent 띠에서 as_of 보다 앞선 마지막 날) */
  function closeBefore(asOf) {
    var rs = state.recent || [];
    for (var i = rs.length - 1; i >= 0; i--) if (rs[i].date < asOf) return rs[i].close;
    return null;
  }
  function priceCell(sym, p, chg, est) {
    return '<div class="pcell" data-sym="' + sym + '"><div class="k">' + sym + (est ? ' <span class="tag est">추정</span>' : "") + "</div>" +
      '<div class="num num-big">' + usd(p) + "</div>" +
      '<div class="pchg num ' + cls(chg) + '">' + (chg == null ? "전일 대비 –" : pct(chg)) + "</div></div>";
  }
  function prices(v) {
    var L = v.live, qPrev = state.qqq_prev_close, tPrev = state.tqqq_prev_close, h, q, t, qc, tc, est = false, head;
    if (L && L.ok) {
      q = L.price;
      if (v.tqqq) t = v.tqqq.price; else { t = T.tqqqAt(state, q); est = true; }
      qc = q / qPrev - 1; tc = t / tPrev - 1;
      head = '<span class="tag">' + (L.closing ? "오늘 종가" : "실시간") + '</span><span class="t num">' + when(L.t) + "</span>";
    } else {
      q = qPrev; t = tPrev;
      var before = closeBefore(state.as_of);
      qc = before ? q / before - 1 : null; tc = null;
      head = '<span class="tag off">확정 종가 · ' + md(state.as_of) + "</span>";
    }
    h = '<div class="ch">' + head + "</div>";
    h += '<div class="pc">' + priceCell("TQQQ", t, tc, est) + priceCell("QQQ", q, qc, false) + "</div>";
    $("prices").innerHTML = h;
  }

  // ── ② 지금 상태 ───────────────────────────
  function confLine(v) {
    var c = v.confirmed;
    return '<div class="conf">어제 종가 <span class="v">' + em(c.state) + " " + U.word(c.state, c.weight) + "</span> · 확정 " +
      N(md(c.date) + " " + usd(c.close)) + "</div>";
  }
  function badgeHtml(b) { return b ? '<span class="badge"><span class="em">' + b.emoji + "</span>" + b.text + "</span>" : ""; }
  function bigState(s, w) {
    return '<div class="state"><span class="em">' + em(s) + '</span><span class="w">' + U.word(s, w).replace(/ (\d+%)$/, "") +
      "</span>" + '<span class="wt num">' + (s === "night" ? "현금" : "TQQQ " + U.weightOf(s, w) + "%") + "</span></div>";
  }
  function nextOpen(s) {
    if (!s) return "";
    return '<div class="meta">' + ICON.clock + "다음 개장 " + N(kstDay(Date.parse(s.open_utc)) + " " + kstHM(Date.parse(s.open_utc))) +
      (isEarly(s) ? " · 조기 폐장 " + N(kstHM(Date.parse(s.close_utc))) + " 마감" : "") + "</div>";
  }

  function banner(v) {
    var el = $("banner"), h = "", st = null, c = v.confirmed;
    if (isLive(v)) {
      var L = v.live, close = Date.parse(v.session.close_utc);
      var timeLeft = L && L.closing ? "장 마감" : "마감 " + kstHM(close) + "까지 " + left(close - now());
      var early = isEarly(v.session) ? badgeHtml({ emoji: "⏱️", text: "조기 폐장" }) : "";
      if (L && L.ok) {
        st = L.eval.state;
        h += '<div class="lbl">' + (L.closing ? "오늘 종가" : "지금") + early + "</div>" + bigState(L.eval.state, L.eval.weight);
        h += confLine(v);
        if (L.differs) h += '<div class="diff">종가에 ' + U.word(c.state, c.weight) + " → " + U.word(L.eval.state, L.eval.weight) + "</div>";
      } else {
        h += "<div>" + badgeHtml(U.badge(v)) + early + "</div>";
        h += '<div class="state"><span class="w off">실시간 판정 없음</span></div>';
        h += '<div class="off-msg">' + (L ? L.text : "실시간 연결 끊김, 전일 종가 기준만 유효") + "</div>";
        h += confLine(v);
      }
      h += '<div class="meta">' + ICON.clock + N(timeLeft) + "</div>";
    } else if (v.mode === "gap") {
      st = c.state;
      h += '<div class="lbl">확정 상태' + badgeHtml(U.badge(v)) + "</div>" + bigState(c.state, c.weight);
      h += '<div class="conf">' + N("확정 " + md(c.date) + " 종가 · RSI2 " + num(c.rsi2, 1)) + "</div>";
      h += nextOpen(v.next);
      var g = v.gap;
      if (g && g.ok && g.differs) {
        h += '<div class="diff">선물대로 열리면 ' + U.word(c.state, c.weight) + " → " + U.word(g.eval.state, g.eval.weight) + " (맨 아래 휴장 갭)</div>";
      }
    } else {
      h += badgeHtml(U.badge(v));
      h += '<div class="state"><span class="w off">지금 상태 계산 안 함</span></div>';
      h += confLine(v);
    }
    el.className = "banner" + (st ? " s-" + st : "");
    $("bannerBody").innerHTML = h;
    mascot(st || (c && c.state));                          // 지금 상태가 없으면 어제 확정 상태
  }

  function todo(v) {
    var t = U.todayLine(v);
    var label = v.mode === "closed" && v.live && v.live.ok ? "오늘 종가 기준" : "오늘 할 일";
    $("todo").innerHTML = '<span class="lbl">' + label + '</span><span class="cmd ' + t.kind + '">' + t.text + "</span>";
  }

  function alerts(v) {
    $("alerts").innerHTML = v.warnings.map(function (w) { return '<div class="alert">' + w + "</div>"; }).join("");
  }

  // ── ③ 기준선 ──────────────────────────────
  // 휴장 때 선물 '예상 시가'는 쓰지 않는다: 장중엔 실제 가격(v.card), 그 외엔 확정 종가 기준(T.card(state, null)).
  var NAME = {
    sma50: ["☀️ 50일선", null], sma200: ["☀️ 200일선", null],
    hunt_half: ["🏹 절반 매수", "RSI2 15 아래"], hunt_full: ["🏹 전액 매수", "RSI2 5 아래"], hunt_exit: ["🌙 전부 매도", "RSI2 50 위"]
  };
  function pc(p, d) { return '<div class="c"><div class="num">' + usd(p) + '</div><div class="num ' + cls(d) + '">' + arrowPct(d) + "</div></div>"; }
  function pline(sym, p, d) {
    return '<div class="pl"><span class="s">' + sym + '</span><span class="num">' + usd(p) + '</span><span class="num ' + cls(d) + '">' + pct(d) + "</span></div>";
  }

  function card(v) {
    var el = $("card");
    var c = isLive(v) ? v.card : (v.mode === "gap" ? T.card(state, null) : null);
    if (!c) { el.innerHTML = '<div class="prev">기준 데이터가 멈춰 계산하지 않습니다</div>'; return; }
    var ref = c.ref, useRef = !!ref && basis === "ref";
    var qBase = useRef ? ref.price : c.prev;
    var tBase = useRef ? (v.tqqq ? v.tqqq.price : T.tqqqAt(state, ref.price)) : state.tqqq_prev_close;
    var h = "";

    var tag = !ref ? '<span class="tag off">전일 종가</span>' : ref.kind === "now" ? '<span class="tag">실시간</span>' : '<span class="tag">오늘 종가</span>';
    var sw = ref
      ? '<span class="seg"><button type="button" data-basis="ref"' + (useRef ? ' class="on"' : "") + '>현재가 대비</button>' +
        '<button type="button" data-basis="prev"' + (!useRef ? ' class="on"' : "") + ">전일 종가 대비</button></span>"
      : '<span class="basis-txt">전일 종가 대비</span>';
    h += '<div class="ch">' + tag + sw + "</div>";

    // 게이지: QQQ 위치는 언제나 지금 가격(없으면 확정 종가) 기준
    h += '<div class="gcap">QQQ 가 선보다 몇 % 위/아래</div>';
    h += gauges(c, ref ? ref.price : c.prev, ref ? c.rsi2 : v.confirmed.rsi2);

    // 상태가 바뀌는 가장 가까운 가격
    function box(x, arrow, word) {
      var head = '<div class="k">' + arrow + " " + word + "</div>";
      if (!x) return '<div class="cb">' + head + '<div class="none">안 바뀜</div></div>';
      var tq = T.tqqqAt(state, x.price);
      return '<div class="cb">' + head + '<div class="to">' + em(x.state) + " " + U.word(x.state, x.weight) + "</div>" +
        pline("TQQQ", tq, tq / tBase - 1) + pline("QQQ", x.price, x.price / qBase - 1) + "</div>";
    }
    h += '<div class="chg">' + box(c.changes.down, "↓", "내려가면") + box(c.changes.up, "↑", "올라가면") + "</div>";

    // 표: [이름 | TQQQ | QQQ]
    var by = {};
    c.rows.forEach(function (r) { by[r.key] = r; });
    function row(key) {
      var r = by[key], nm = NAME[key];
      var sub = nm[1] || ("선 " + num(r.line, 2));
      return '<div class="tr"><div class="n"><span>' + nm[0] + "</span><small>" + sub + "</small></div>" +
        pc(r.tqqq, r.tqqq / tBase - 1) + pc(r.price, r.price / qBase - 1) + "</div>";
    }
    h += '<div class="tb"><div class="th"><span></span><span>TQQQ</span><span>QQQ</span></div>';
    h += '<div class="grp">낮 경계선 <small>하나라도 위면 낮</small></div>' + row("sma50") + row("sma200");
    h += '<div class="grp">사냥선 <small>밤(둘 다 아래)일 때만 씀</small></div>' + row("hunt_half") + row("hunt_full") + row("hunt_exit");
    h += "</div>";

    h += '<div class="rsi"><span class="n">' + ICON.rsi + 'RSI2</span><span class="v num">' + num(ref ? c.rsi2 : v.confirmed.rsi2, 1) +
         "<small>" + (ref ? (ref.kind === "close" ? "오늘 종가" : "지금") : "확정") + "</small></span></div>";
    el.innerHTML = h;
  }
  $("card").addEventListener("click", function (e) {
    var b = e.target.closest && e.target.closest("[data-basis]");
    if (!b) return;
    setBasis(b.getAttribute("data-basis"));
    render();
  });

  // 게이지 세 개
  var LINE_RANGE = 0.10;                                   // 선 ±10% 를 양 끝으로 (넘으면 끝에 붙음)
  function lineGauge(label, cross, price) {
    var d = price / cross - 1;                             // QQQ 가 선보다 몇 % 위(+)/아래(−)
    var x = Math.max(-1, Math.min(1, d / LINE_RANGE)) * 50;
    var fill = d >= 0 ? "left:50%;width:" + x + "%" : "left:" + (50 + x) + "%;width:" + (-x) + "%";
    return '<div class="g"><span class="gl">' + label + '</span><span class="gb"><i class="fill ' + (d >= 0 ? "up" : "down") +
      '" style="' + fill + '"></i><i class="mid"></i></span><span class="gv num ' + cls(d) + '">' + pct(d) + "</span></div>";
  }
  function rsiGauge(r) {
    var zones = [[0, 5], [5, 15], [15, 50], [50, 100]], h = '<span class="gb rsi">';
    zones.forEach(function (z, i) {
      var cur = r != null && (i === 3 ? r > 50 : r >= z[0] && (i === 2 ? r <= 50 : r < z[1]));
      h += '<i class="z' + (cur ? " cur" : "") + (i === 0 ? " first" : "") + (i === 3 ? " last" : "") +
           '" style="left:' + z[0] + "%;width:" + (z[1] - z[0]) + '%"></i>';
    });
    [5, 15, 50].forEach(function (t) { h += '<i class="tick" style="left:' + t + '%"></i>'; });
    if (r != null) h += '<i class="dot" style="left:' + Math.max(0, Math.min(100, r)) + '%"></i>';
    return '<div class="g"><span class="gl">RSI2</span>' + h + '</span><span class="gv num">' + num(r, 1) + "</span></div>";
  }
  function gauges(c, price, rsi) {
    return '<div class="gauges">' + lineGauge("50일선", c.rows[0].price, price) + lineGauge("200일선", c.rows[1].price, price) + rsiGauge(rsi) + "</div>";
  }

  // ── ④ 흐름: 60거래일 띠 + 밤 비율 ─────────
  var histSel = null;
  function histLine(r) {
    var d = new Date(r.date + "T12:00:00Z");
    return N((d.getUTCMonth() + 1) + "/" + d.getUTCDate()) + "(" + WD[d.getUTCDay()] + ") · " + N("QQQ " + usd(r.close) + " · RSI2 " + num(r.rsi2, 1)) +
      " · " + em(r.state) + " " + U.word(r.state, r.weight) + (r.source === "역산" ? ' <span class="src">역산</span>' : "");
  }
  function hist() {
    var rs = state.recent || [];
    if (!rs.length) { $("hist").innerHTML = ""; return; }
    if (histSel == null || histSel >= rs.length) histSel = rs.length - 1;
    var h = "<h2><span>최근 " + rs.length + "거래일</span></h2><div class=\"strip\" id=\"strip\">";
    rs.forEach(function (r, i) {
      h += '<span class="b b-' + r.state + (r.state === "hunt" && r.weight === 100 ? " full" : "") + (i === histSel ? " sel" : "") +
           '" data-i="' + i + '" title="' + r.date + " " + U.word(r.state, r.weight) + '"></span>';
    });
    h += '</div><div class="ends num"><span>' + md(rs[0].date) + "</span><span>" + md(rs[rs.length - 1].date) + "</span></div>";
    h += '<div class="pick">' + histLine(rs[histSel]) + "</div>";
    h += '<div class="keys"><span class="b b-day"></span>낮<span class="b b-night"></span>밤<span class="b b-hunt"></span>사냥 50%<span class="b b-hunt full"></span>사냥 100%</div>';
    $("hist").innerHTML = h;
  }
  function pickAt(x, y) {
    var el = document.elementFromPoint(x, y);
    var b = el && el.closest && el.closest("#strip [data-i]");
    if (!b) return;
    var i = +b.getAttribute("data-i");
    if (i !== histSel) { histSel = i; hist(); }
  }
  $("hist").addEventListener("pointerdown", function (e) { pickAt(e.clientX, e.clientY); });
  $("hist").addEventListener("pointermove", function (e) { if (e.pointerType === "mouse" || e.buttons) pickAt(e.clientX, e.clientY); });

  function regime() {
    var r = state.night_ratio || {}, h = "<h2><span>밤 비율</span></h2><div class=\"ratio\">";
    [["1m", "1개월"], ["3m", "3개월"], ["12m", "12개월"]].forEach(function (k) {
      var x = r[k[0]];
      h += '<div><div class="k">' + k[1] + '</div><div class="v num">' + (x == null ? "–" : x.toFixed(1) + "%") + "</div></div>";
    });
    h += '</div><div class="legend"><span>10%대</span> → 확장기, 룰이 거의 작동하지 않는 구간<br>' +
         "<span>30% 이상</span> → 침체 신호, 룰이 돈을 벌기 시작하는 구간</div>";
    $("regime").innerHTML = h;
  }

  // ── ⑤ 휴장 갭 예상 · NQ 선물 ──────────────
  // 휴장·개장 전에는 core 의 v.gap 을 쓰고, 정규장 중에는 같은 식으로 계산만 해서 회색으로 둔다.
  function gapData(v) {
    if (v.mode === "gap") {
      var g = v.gap;
      if (!g.ok) return { msg: g.text };
      return { nq: g.nq, open: g.qqqOpen, tq: g.tqqqOpen, ev: g.eval, differs: g.differs, frozen: g.frozen ? g.frozenText : null };
    }
    var q = quotes && quotes.quotes && quotes.quotes.NQ, ref = state.nq_prev_settle;
    if (!q || typeof q.price !== "number" || !ref) return { msg: "선물 시세 없음" };
    var chg = q.price / ref - 1, open = state.qqq_prev_close * (1 + chg), ev = T.evaluate(state, open), c = v.confirmed;
    return { nq: { price: q.price, t: q.time * 1000, chg: chg, ref: ref }, open: open, tq: T.tqqqAt(state, open), ev: ev,
             differs: ev.state !== c.state || ev.weight !== c.weight, frozen: null };
  }
  function gapCard(v) {
    var el = $("gap"), off = v.mode !== "gap", d = gapData(v), h = "";
    var tag = v.mode === "gap" ? '<span class="tag">' + badgeHtml(U.badge(v)) + "</span>"
            : v.mode === "stale" ? '<span class="tag off">기준 데이터 멈춤</span>'
            : '<span class="tag off">정규장 중 · 휴장 때만 씀</span>';
    var right = v.mode === "gap" && v.next ? '<span class="t num">개장 ' + kstDay(Date.parse(v.next.open_utc)) + " " + kstHM(Date.parse(v.next.open_utc)) + "</span>" : "";
    h += '<div class="ch">' + tag + right + "</div>";
    if (d.msg) {
      h += '<div class="off-msg">' + d.msg + "</div>";
    } else {
      var tPrev = state.tqqq_prev_close, qPrev = state.qqq_prev_close;
      h += '<div class="gp">';
      h += '<div><div class="k">' + ICON.fut + 'NQ 선물</div><div class="v num">' + num(d.nq.price, 2) + ' <small class="' + cls(d.nq.chg) + '">' + pct(d.nq.chg) + "</small></div></div>";
      h += '<div><div class="k">예상 상태</div><div class="v">' + em(d.ev.state) + " " + U.word(d.ev.state, d.ev.weight) +
           " <small>" + (d.differs ? '<span class="down">바뀜</span>' : "동일") + "</small></div></div>";
      h += '<div><div class="k">예상 시가 TQQQ</div><div class="v num">' + usd(d.tq) + ' <small class="' + cls(d.tq / tPrev - 1) + '">' + pct(d.tq / tPrev - 1) + "</small></div></div>";
      h += '<div><div class="k">예상 시가 QQQ</div><div class="v num">' + usd(d.open) + ' <small class="' + cls(d.open / qPrev - 1) + '">' + pct(d.open / qPrev - 1) + "</small></div></div>";
      h += '<div><div class="k">' + ICON.rsi + '예상 RSI2</div><div class="v num">' + num(d.ev.rsi2, 1) + "</div></div>";
      h += "</div>";
      if (d.frozen) h += '<div class="off-msg">' + d.frozen + "</div>";
      h += '<div class="meta">' + ICON.clock + N("선물 " + when(d.nq.t)) + " · 선물과 현물은 차이가 있어 어긋날 수 있음</div>";
    }
    el.className = "card gapc" + (off ? " off" : "");
    el.innerHTML = h;
  }

  // ── ⑥ 각오 ────────────────────────────────
  function resolve() {
    $("resolve").innerHTML = "<h2><span>1999~2026 QQQ 검증</span></h2>" +
      "<p><b>사냥 승률 74% · 평균 +1.9% · 최악 -40%</b><br>최대 평가손실: -57% (2004년 이후) / -96% (1999년 포함)</p>" +
      "<dl><dt>룰이 지는 구간</dt><dd>25% 넘는 급락이 없는 강세장<br>2010~2019년에 3배 단순보유 대비 연 9%p 뒤처졌다. 설계대로다.</dd>" +
      "<dt>사냥이 지는 장</dt><dd>계단식으로 갈아내리는 하락장<br>닷컴에서 사냥 기여는 -2.1%였다. 헛걸음이 이어지는 게 정상이다.</dd></dl>";
  }

  function fx(v) {
    var f = v.fx;
    $("fx").innerHTML = ICON.fx + (f ? 'USD/KRW <span class="v num">' + num(f.price, 2) + "</span> " +
      N(f.live ? when(f.t) : md(f.date)) : "USD/KRW –");
  }

  // ── ⓘ (눌러야 보임) ───────────────────────
  function info(v) {
    var p = !proxyUrl ? "프록시 주소 미설정"
          : lastOk && lastTry === lastOk ? "연결됨 · " + when(lastOk) + " 받음"
          : "끊김 · 마지막 시도 " + when(lastTry);
    $("infoBody").innerHTML =
      "<p><b>판정</b> 장중 상태는 참고용. 주문은 마감 직전 종가로 판단한다. 장중에 선을 넘었다가 종가에 되돌아오는 경우가 있다.</p>" +
      "<p><b>룰</b> 50·200일선 하나라도 위(초과) = 낮(TQQQ 100%), 둘 다 같거나 아래 = 밤(현금). 밤의 비중은 RSI2: 5 미만 100%, 5~15 50%, 15~50 직전 유지(사냥 중), 50 초과 전량 매도. 사냥 중 선 회복 = 청산 없이 낮. RSI2 = Wilder 기간 2.</p>" +
      "<p><b>가격</b> 이동평균·RSI2·$ 는 전부 배당조정(수정주가) 종가 기준이라 증권사 차트의 $ 와 다를 수 있다. 판단은 % 로. 기준선 표의 가격은 그 가격으로 마감하면 상태가 바뀌는 값('선 …'은 지금 이동평균 값).</p>" +
      "<p><b>추정</b> TQQQ 실시간 시세가 없으면 TQQQ = 전일 종가 × (1 + 3 × QQQ 변화율)로 추정하고 '추정'이라고 표시한다. 기준선 표의 TQQQ 값도 같은 식이다.</p>" +
      "<p><b>휴장 갭</b> 맨 아래 카드. 예상 시가 = 전일 종가 × (NQ 선물 ÷ 전일 현물 마감 시각 NQ " + num(state.nq_prev_settle, 2) + "). 선물과 현물은 베이시스 차이가 있어 어긋날 수 있다. 정규장 중에는 계산만 하고 회색으로 둔다. 기준선은 휴장 때도 예상 시가가 아니라 확정 종가 기준.</p>" +
      "<p><b>데이터</b> 기준: yfinance 일봉, GitHub Actions 가 매일 07:00 KST 에 기록 (마지막 " + v.asOf + " 종가, " + when(v.generatedAt) + " 기록). " +
      "실시간: 야후 시세 → Cloudflare 프록시, 30초마다 (NQ 선물은 약 10분 지연) · " + p + ".</p>" +
      (fakeNow != null ? "<p><b>시험 시계</b> " + T.fmtKst(now()) + "</p>" : "");
  }

  function render() {
    if (!state) {
      if (stateErr) $("bannerBody").innerHTML = '<div class="off-msg">state.json 을 불러오지 못했습니다 · ' + stateErr + "</div>";
      return;
    }
    var v = T.buildView(state, quotes, now());
    prices(v); banner(v); todo(v); alerts(v); card(v); fx(v);
    hist(); regime(); gapCard(v); resolve(); info(v);
    window.__view = v;
  }

  // ── 데이터 받기 ───────────────────────────
  function get(url) {
    var ctl = new AbortController(), timer = setTimeout(function () { ctl.abort(); }, FETCH_TIMEOUT);
    return fetch(url, { cache: "no-store", signal: ctl.signal }).then(function (r) {
      clearTimeout(timer);
      if (!r.ok) throw new Error("HTTP " + r.status);
      return r.json();
    }, function (e) { clearTimeout(timer); throw e; });
  }

  function loadState() {
    return get("data/state.json?t=" + Date.now()).then(function (s) { state = s; stateErr = null; },
      function (e) { stateErr = String(e.message || e); });
  }

  function poll() {
    lastTry = now();
    if (!proxyUrl) { quotes = null; render(); return Promise.resolve(); }
    return get(proxyUrl).then(function (q) { quotes = q; lastOk = lastTry; },
      function () { quotes = null; })                     // 실패하면 옛 값을 버린다
      .then(render);
  }

  loadState().then(function () { render(); return poll(); });
  setInterval(poll, POLL_MS);
  setInterval(function () { loadState().then(render); }, STATE_MS);
  setInterval(render, 15 * 1000);                          // 마감까지 남은 시간 · 멈춤 판정은 시계로도 바뀜
  document.addEventListener("visibilitychange", function () { if (!document.hidden) loadState().then(poll); });
})();
