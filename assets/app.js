/* 화면 그리기만 한다. 판정은 core.js (TQHD), 문구는 ui.js (TQHD_UI). */
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

  // ── 마스코트 (상태 배너에만, 한 장만 받는다) ──
  // 상태가 바뀔 때만 srcset/src 를 바꾼다. 못 불러오면 슬롯을 통째로 숨긴다.
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

  // ── 배너 ──────────────────────────────────
  function confLine(v) {
    return '<div class="conf">어제 종가 <span class="v">' + U.word(v.confirmed.state, v.confirmed.weight) + "</span> · 확정 " +
      N(md(v.confirmed.date) + " " + usd(v.confirmed.close)) + "</div>";
  }
  function badgeHtml(b) { return b ? '<span class="badge"><span class="em">' + b.emoji + "</span>" + b.text + "</span>" : ""; }
  function bigState(s, w) {
    return '<div class="state"><span class="em">' + U.EMOJI[s] + '</span><span class="w">' + U.word(s, w).replace(/ (\d+%)$/, "") +
      "</span>" + '<span class="wt num">' + (s === "night" ? "현금" : "TQQQ " + U.weightOf(s, w) + "%") + "</span></div>";
  }

  function banner(v) {
    var el = $("banner"), h = "", st = null;
    if (v.mode === "live" || v.mode === "closed") {
      var L = v.live, c = Date.parse(v.session.close_utc);
      var timeLeft = L && L.closing ? "장 마감" : "마감 " + kstHM(c) + "까지 " + left(c - now());
      var early = isEarly(v.session) ? badgeHtml({ emoji: "⏱️", text: "조기 폐장" }) : "";
      if (L && L.ok) {
        st = L.eval.state;
        h += '<div class="lbl">' + (L.closing ? "오늘 종가" : "지금") + early + "</div>" + bigState(L.eval.state, L.eval.weight);
        h += confLine(v);
        if (L.differs) h += '<div class="diff">종가에 ' + U.word(v.confirmed.state, v.confirmed.weight) + " → " + U.word(L.eval.state, L.eval.weight) + "</div>";
        h += '<div class="meta">' + ICON.clock + N("QQQ " + usd(L.price) + " · " + when(L.t)) + " · " + N(timeLeft) + "</div>";
      } else {
        h += "<div>" + badgeHtml(U.badge(v)) + early + "</div>";
        h += '<div class="state"><span class="w off">실시간 판정 없음</span></div>';
        h += '<div class="off-msg">' + (L ? L.text : "실시간 연결 끊김, 전일 종가 기준만 유효") + "</div>";
        h += confLine(v);
        h += '<div class="meta">' + ICON.clock + N(timeLeft) + "</div>";
      }
    } else if (v.mode === "gap") {
      var g = v.gap;
      h += badgeHtml(U.badge(v));
      if (v.next) h += '<div class="meta">다음 개장 ' + N(kstDay(Date.parse(v.next.open_utc)) + " " + kstHM(Date.parse(v.next.open_utc))) +
        (isEarly(v.next) ? " · 조기 폐장 " + N(kstHM(Date.parse(v.next.close_utc))) + " 마감" : "") + "</div>";
      if (g.ok) {
        st = g.eval.state;
        h += '<div class="grid">';
        h += '<div><div class="k">' + ICON.fut + 'NQ 선물</div><div class="v num">' + num(g.nq.price, 2) + ' <small class="' + cls(g.nq.chg) + '">' + pct(g.nq.chg) + "</small></div></div>";
        h += '<div><div class="k">예상 시가</div><div class="v num">' + usd(g.qqqOpen) + "</div></div>";
        h += '<div><div class="k">예상 상태</div><div class="v"><span class="em">' + U.EMOJI[g.eval.state] + "</span> " + U.word(g.eval.state, g.eval.weight) +
             " <small>" + (g.differs ? '<span class="down">바뀜</span>' : "동일") + "</small></div></div>";
        h += '<div><div class="k">' + ICON.rsi + '예상 RSI2</div><div class="v num">' + num(g.eval.rsi2, 1) + "</div></div>";
        h += "</div>";
        h += '<div class="meta">' + ICON.clock + N("선물 " + when(g.nq.t)) + "</div>";
        if (g.frozen) h += '<div class="off-msg">' + g.frozenText + "</div>";
      } else {
        h += '<div class="off-msg">' + g.text + "</div>";
      }
      h += confLine(v);
    } else {
      h += badgeHtml(U.badge(v));
      h += '<div class="state"><span class="w off">지금 상태 계산 안 함</span></div>';
      h += confLine(v);
    }
    el.className = "banner" + (st ? " s-" + st : "");
    $("bannerBody").innerHTML = h;
    mascot(st || (v.confirmed && v.confirmed.state));     // 지금 상태가 없으면 어제 확정 상태
  }

  function todo(v) {
    var t = U.todayLine(v);
    var label = v.mode === "closed" && v.live && v.live.ok ? "오늘 종가 기준" : "오늘 할 일";
    $("todo").innerHTML = '<span class="lbl">' + label + '</span><span class="cmd ' + t.kind + '">' + t.text + "</span>";
  }

  // ── 기준선 카드 ───────────────────────────
  var LABEL = { sma50: "50일선", sma200: "200일선", hunt_half: "절반 15", hunt_full: "전액 5", hunt_exit: "청산 50" };
  function card(v) {
    var el = $("card");
    if (!v.card) { el.innerHTML = "<h2><span>" + ICON.ma + "기준선</span></h2>"; return; }
    var c = v.card, ref = c.ref, h = "";
    var tag = !ref ? '<span class="tag off">전일 종가</span>' : ref.kind === "now" ? '<span class="tag">실시간</span>'
            : ref.kind === "close" ? '<span class="tag">오늘 종가</span>' : '<span class="tag">예상 시가</span>';
    h += "<h2><span>" + ICON.ma + "QQQ 기준선</span>" + tag + "</h2>";
    if (ref) {
      h += '<div class="px"><span class="num num-big">' + usd(ref.price) + '</span><span class="c num ' + cls(c.refChg) + '">' + pct(c.refChg) +
           '</span><span class="t num">' + when(ref.t) + "</span></div>";
    }
    h += '<div class="prev">전일 ' + N(usd(c.prev) + " · " + md(v.asOf)) + "</div>";

    var basePrice = ref ? ref.price : c.prev;
    h += gauges(c, basePrice, ref ? c.rsi2 : v.confirmed.rsi2);
    function chg(x, arrow) {
      if (!x) return '<div><div class="v">' + arrow + '</div><div class="none">안 바뀜</div></div>';
      var d = x.price / basePrice - 1;
      return '<div><div class="v num ' + cls(d) + '">' + arrow + " " + pct(d) + '</div><div class="to num">' + usd(x.price) + " → " + U.word(x.state, x.weight) + "</div></div>";
    }
    h += '<div class="chg">' + chg(c.changes.down, "↓") + chg(c.changes.up, "↑") + "</div>";

    h += '<div class="rh">' + (ref ? "현재가 대비" : "전일 종가 대비") + "</div><div class=\"rows\">";
    c.rows.forEach(function (r, i) {
      var isLine = r.key === "sma50" || r.key === "sma200";
      var d = r.fromRef != null ? r.fromRef : r.fromPrev;
      var sub = [];
      if (isLine) sub.push("닿는 " + usd(r.price));
      if (r.fromRef != null) sub.push("전일 " + pct(r.fromPrev));
      sub.push("TQQQ " + usd(r.tqqq));
      h += '<div class="r' + (i === 2 ? " sep" : "") + '"><span class="n">' + LABEL[r.key] + '</span><span class="p num">' + usd(isLine ? r.line : r.price) +
           '</span><span class="d num ' + cls(d) + '">' + arrowPct(d) + '</span><span class="s num">' + sub.join(" · ") + "</span></div>";
    });
    h += "</div>";
    h += '<div class="rsi"><span class="n">' + ICON.rsi + "RSI2</span><span class=\"v num\">" + num(ref ? c.rsi2 : v.confirmed.rsi2, 1) +
         "<small>" + (ref ? (ref.kind === "open" ? "예상" : "지금") : "확정") + "</small></span></div>";
    el.innerHTML = h;
  }

  // ── 게이지 세 개 ──────────────────────────
  var LINE_RANGE = 0.10;                                   // 선 ±10% 를 양 끝으로 (넘으면 끝에 붙음)
  function lineGauge(label, cross, price) {
    var d = price / cross - 1;                             // 현재가가 선보다 몇 % 위(+)/아래(−)
    var x = Math.max(-1, Math.min(1, d / LINE_RANGE)) * 50;
    var fill = d >= 0 ? 'left:50%;width:' + x + '%' : 'left:' + (50 + x) + '%;width:' + (-x) + '%';
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
    var r50 = c.rows[0], r200 = c.rows[1];
    return '<div class="gauges">' + lineGauge("50일선", r50.price, price) + lineGauge("200일선", r200.price, price) + rsiGauge(rsi) + "</div>";
  }

  function tqqqCard(v) {
    var prev = state.tqqq_prev_close, h = "<h2><span>TQQQ</span>";
    if (v.tqqq) {
      h += '<span class="tag">실시간</span></h2><div class="px"><span class="num num-big">' + usd(v.tqqq.price) + '</span><span class="c num ' +
           cls(v.tqqq.price / prev - 1) + '">' + pct(v.tqqq.price / prev - 1) + '</span><span class="t num">' + when(v.tqqq.t) + "</span></div>";
    } else if (v.gap && v.gap.ok) {
      h += '<span class="tag">예상 시가</span></h2><div class="px"><span class="num num-big">' + usd(v.gap.tqqqOpen) + "</span></div>";
    } else {
      h += '<span class="tag off">전일 종가</span></h2>';
    }
    h += '<div class="prev">전일 ' + N(usd(prev)) + "</div>";
    $("tqqq").innerHTML = h;
  }

  function fx(v) {
    var f = v.fx;
    $("fx").innerHTML = ICON.fx + (f ? 'USD/KRW <span class="v num">' + num(f.price, 2) + "</span> " +
      N(f.live ? when(f.t) : md(f.date)) : "USD/KRW –");
  }

  function alerts(v) {
    $("alerts").innerHTML = v.warnings.map(function (w) { return '<div class="alert">' + w + "</div>"; }).join("");
  }

  // ── 밤 비율 ───────────────────────────────
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

  // ── 최근 60거래일 띠 ──────────────────────
  var histSel = null;
  function histLine(r) {
    var d = new Date(r.date + "T12:00:00Z");
    return N((d.getUTCMonth() + 1) + "/" + d.getUTCDate()) + "(" + WD[d.getUTCDay()] + ") · " + N("QQQ " + usd(r.close) + " · RSI2 " + num(r.rsi2, 1)) +
      " · " + U.word(r.state, r.weight) + (r.source === "역산" ? ' <span class="src">역산</span>' : "");
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

  // ── 각오 카드 (고정) ──────────────────────
  function resolve() {
    $("resolve").innerHTML = "<h2><span>각오 · 1999~2026 QQQ 검증</span></h2>" +
      "<p><b>사냥 승률 74% · 평균 +1.9% · 최악 -40%</b><br>최대 평가손실: -57% (2004년 이후) / -96% (1999년 포함)</p>" +
      "<dl><dt>룰이 지는 구간</dt><dd>25% 넘는 급락이 없는 강세장<br>2010~2019년에 3배 단순보유 대비 연 9%p 뒤처졌다. 설계대로다.</dd>" +
      "<dt>사냥이 지는 장</dt><dd>계단식으로 갈아내리는 하락장<br>닷컴에서 사냥 기여는 -2.1%였다. 헛걸음이 이어지는 게 정상이다.</dd></dl>";
  }

  // ── ⓘ (눌러야 보임) ───────────────────────
  function info(v) {
    var p = !proxyUrl ? "프록시 주소 미설정"
          : lastOk && lastTry === lastOk ? "연결됨 · " + when(lastOk) + " 받음"
          : "끊김 · 마지막 시도 " + when(lastTry);
    $("infoBody").innerHTML =
      "<p><b>판정</b> 장중 상태는 참고용. 주문은 마감 직전 종가로 판단한다. 장중에 선을 넘었다가 종가에 되돌아오는 경우가 있다.</p>" +
      "<p><b>룰</b> 50·200일선 하나라도 위(초과) = 낮(TQQQ 100%), 둘 다 같거나 아래 = 밤(현금). 밤의 비중은 RSI2: 5 미만 100%, 5~15 50%, 15~50 직전 유지(사냥 중), 50 초과 전량 매도. 사냥 중 선 회복 = 청산 없이 낮. RSI2 = Wilder 기간 2.</p>" +
      "<p><b>가격</b> 이동평균·RSI2·$ 는 전부 배당조정(수정주가) 종가 기준이라 증권사 차트의 $ 와 다를 수 있다. 판단은 현재가 대비 % 로. TQQQ 예상 = 전일 종가 × (1 + 3 × QQQ 변화율). '닿는' = 그 가격 이하로 마감하면 선 이하.</p>" +
      "<p><b>휴일 갭</b> 선물과 현물은 베이시스 차이가 있어 예상치는 어긋날 수 있다. 참고용. 예상 시가 = 전일 종가 × (NQ 선물 ÷ 전일 현물 마감 시각 NQ " + num(state.nq_prev_settle, 2) + "). 예상 상태 = 예상 시가로 마감한다면.</p>" +
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
    banner(v); todo(v); alerts(v); card(v); tqqqCard(v); fx(v);
    regime(); hist(); resolve(); info(v);
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
