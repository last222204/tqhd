/* 화면 그리기만 한다. 계산은 전부 core.js (TQHD) 에 있다. */
(function () {
  "use strict";
  var T = window.TQHD, cfg = window.TQHD_CONFIG || {};
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

  // ── 숫자 표기 ─────────────────────────────
  function usd(x, d) { return x == null || !isFinite(x) ? "–" : "$" + x.toLocaleString("en-US", { minimumFractionDigits: d == null ? 2 : d, maximumFractionDigits: d == null ? 2 : d }); }
  function num(x, d) { return x == null || !isFinite(x) ? "–" : x.toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d }); }
  function pct(x) { if (x == null || !isFinite(x)) return "–"; var v = x * 100; return (v > 0 ? "+" : v < 0 ? "−" : "") + Math.abs(v).toFixed(2) + "%"; }
  function cls(x) { return x > 0 ? "up" : x < 0 ? "down" : ""; }
  var WD = ["일", "월", "화", "수", "목", "금", "토"];
  function kstDay(t) { var d = new Date(t + 9 * 3600e3); return (d.getUTCMonth() + 1) + "/" + d.getUTCDate() + "(" + WD[d.getUTCDay()] + ")"; }
  function kstHM(t) { return T.fmtKst(t, false); }
  function when(t) {           // 오늘이면 시각만, 아니면 날짜까지 (한국 시간)
    if (t == null) return "–";
    return kstDay(t) === kstDay(now()) ? kstHM(t) : T.fmtKst(t);
  }
  function left(ms) { var m = Math.max(0, Math.round(ms / 60000)); return (m >= 60 ? Math.floor(m / 60) + "시간 " : "") + (m % 60) + "분"; }
  function sClass(s) { return "s-" + (s || "off"); }

  // ── 배너 ──────────────────────────────────
  function confLine(v) {
    return '<div class="conf">어제 종가 <span class="st">' + v.confirmed.text + "</span> (확정 · " +
      v.confirmed.date.slice(5).replace("-", "/") + " 종가 " + usd(v.confirmed.close) + ")</div>";
  }

  function sessionNote(s) {
    if (!s) return "";
    var o = Date.parse(s.open_utc), c = Date.parse(s.close_utc);
    var early = c - o < 6.5 * 3600e3 - 1;
    return early ? " · 조기 폐장 " + kstHM(c) + " 마감" : "";
  }

  function banner(v) {
    var el = $("banner"), h = "";
    if (v.mode === "live" || v.mode === "closed") {
      var L = v.live, c = Date.parse(v.session.close_utc);
      if (L && L.ok) {
        var e = L.eval;
        el.className = "banner " + sClass(e.state);
        h += '<div class="row"><span class="lbl">' + (L.closing ? "오늘 종가" : "지금") + '</span><span class="big">' + L.text +
             '</span><span class="act">' + T.action(e.state, e.weight) + "</span></div>";
        h += confLine(v);
        h += L.differs
          ? '<div class="diff">⚠ ' + (L.closing ? "오늘 종가로 " : "지금 가격이면 종가에 ") + v.confirmed.text + " → " + L.text + " 로 바뀜</div>"
          : '<div class="same">어제 종가 상태와 같음</div>';
        h += '<div class="meta">QQQ ' + usd(L.price) + " · " + when(L.t) + " KST 가격 기준 · " +
             (L.closing ? "장 마감 · 종가 자동 기록 대기 (매일 07:00)" : "마감 " + kstHM(c) + "까지 " + left(c - now()) + sessionNote(v.session)) + "</div>";
      } else {
        el.className = "banner s-off";
        h += '<div class="row"><span class="lbl">지금</span><span class="big">실시간 판정 없음</span></div>';
        h += '<div class="off-msg">' + (L ? L.text : "실시간 연결 끊김, 전일 종가 기준만 유효") + "</div>";
        h += confLine(v);
        h += '<div class="meta">장중 · 마감 ' + kstHM(c) + "까지 " + left(c - now()) + sessionNote(v.session) + "</div>";
      }
    } else if (v.mode === "gap") {
      h = gapCard(v);
      el.className = "banner gap " + (v.gap && v.gap.ok ? sClass(v.gap.eval.state) : "s-off");
    } else {
      el.className = "banner s-off";
      h += '<div class="row"><span class="lbl">지금</span><span class="big">기준 데이터 멈춤</span></div>';
      h += '<div class="off-msg">자동 갱신이 멈춰 지금 상태를 계산하지 않습니다</div>';
      h += confLine(v);
    }
    el.innerHTML = h;
  }

  function gapIcon(r) {
    if (!r) return "⏸️";
    if (r.kind === "holiday") return r.name === "추수감사절" ? "🏈" : r.name === "크리스마스" ? "🎄" : "🗓️";
    if (r.kind === "weekend") return "🗓️";
    if (r.kind === "premarket") return "⏰";
    return "⏸️";
  }

  function gapCard(v) {
    var g = v.gap, r = v.reason, h = "";
    var title = r && r.kind === "holiday" ? "미국 현물장 휴장 (" + r.name + ")"
              : r && r.kind === "weekend" ? "미국 현물장 휴장 (주말)"
              : r && r.kind === "premarket" ? "미국 현물장 장 시작 전" : "미국 현물장 마감 후";
    h += '<div class="head">' + gapIcon(r) + " " + title + "</div>";
    if (v.next) h += '<div class="sub">다음 개장 ' + kstDay(Date.parse(v.next.open_utc)) + " " + kstHM(Date.parse(v.next.open_utc)) + " KST" + sessionNote(v.next) + "</div>";
    if (g.ok) {
      h += '<div class="grid">';
      h += '<div><div class="k">나스닥 선물 NQ</div><div class="v">' + num(g.nq.price, 2) + ' <small class="' + cls(g.nq.chg) + '">' + pct(g.nq.chg) + "</small></div></div>";
      h += '<div><div class="k">→ QQQ 예상 시가</div><div class="v">' + usd(g.qqqOpen) + "</div></div>";
      h += '<div><div class="k">→ 예상 상태</div><div class="v">' + g.text + " <small>" + (g.differs ? '<b class="down">바뀜</b>' : "지금과 동일") + "</small></div></div>";
      h += '<div><div class="k">→ 예상 RSI2</div><div class="v">' + num(g.eval.rsi2, 1) + "</div></div>";
      h += "</div>";
      h += '<div class="meta">선물 ' + when(g.nq.t) + " KST 거래 (야후 약 10분 지연) · 기준 = 전일 마감 시각 " + num(g.nq.ref, 2) + "</div>";
      if (g.frozen) h += '<div class="frozen">' + g.frozenText + "</div>";
    } else {
      h += '<div class="off-msg">' + g.text + "</div>";
    }
    h += confLine(v);
    h += '<div class="note">선물과 현물은 베이시스 차이가 있어 예상치는 어긋날 수 있다. 참고용. (예상 상태 = 예상 시가로 마감한다면)</div>';
    return h;
  }

  // ── 기준선 카드 ───────────────────────────
  function card(v) {
    var el = $("card");
    if (!v.card) { el.innerHTML = '<h2>QQQ 기준선</h2><div class="prev">기준 데이터가 멈춰 계산하지 않습니다.</div>'; el.className = "card off"; return; }
    var c = v.card, ref = c.ref, h = "";
    el.className = "card" + (c.basisIsPrev ? " off" : "");
    var refName = !ref ? "실시간 없음 · 전일 종가 기준" : ref.kind === "now" ? "지금 (실시간)" : ref.kind === "close" ? "오늘 종가 (기록 전)" : "예상 시가 (선물 기준)";
    h += "<h2>QQQ · " + refName + "</h2>";
    if (ref) {
      h += '<div class="px"><span class="p">' + usd(ref.price) + '</span><span class="c ' + cls(c.refChg) + '">' + pct(c.refChg) +
           '</span><span class="t">' + when(ref.t) + " KST</span></div>";
    }
    h += '<div class="prev">전일 종가 ' + usd(c.prev) + " (" + v.asOf.slice(5).replace("-", "/") + ")</div>";

    // 상태가 바뀌는 가장 가까운 가격
    var basePrice = ref ? ref.price : c.prev;
    function chg(x, arrow, word) {
      if (!x) return '<div><div class="v">' + arrow + " <small>" + word + '</small></div><div class="none">이 방향으로는 안 바뀜</div></div>';
      return '<div><div class="v ' + cls(x.price / basePrice - 1) + '">' + arrow + " " + pct(x.price / basePrice - 1) + " <small>" + word + "</small>" +
             '</div><div class="to">' + usd(x.price) + " → " + T.stateText(x.state, x.weight) + "</div></div>";
    }
    h += '<div class="chg">' + chg(c.changes.down, "↓", "내리면") + chg(c.changes.up, "↑", "오르면") + "</div>";

    h += '<div class="rows">';
    c.rows.forEach(function (r, i) {
      var isLine = r.key === "sma50" || r.key === "sma200";
      var d = r.fromRef != null ? r.fromRef : r.fromPrev;
      var word = isLine ? (d < 0 ? "이탈까지" : "회복까지") : "";
      var sub = (isLine ? "선 " + usd(r.line) + " · 닿는 가격 " : "가격 ") + "<b>" + usd(r.price) + "</b>";
      if (r.fromRef != null) sub += " · 전일 " + pct(r.fromPrev);
      sub += " · TQQQ≈" + usd(r.tqqq);
      h += '<div class="r' + (i === 2 ? " sep" : "") + '"><div class="n">' + r.label + (word ? " <small>" + word + "</small>" : "") +
           '</div><div class="d ' + cls(d) + '">' + pct(d) + '</div><div class="s">' + sub + "</div></div>";
    });
    h += "</div>";
    h += '<div class="rsi"><span class="n">RSI2 (' + (ref ? (ref.kind === "open" ? "예상" : "지금") : "확정") + ')</span><span class="v">' +
         num(ref ? c.rsi2 : v.confirmed.rsi2, 1) + "</span></div>";
    h += '<div class="basis">% 는 ' + (ref ? "위 가격에서 / 전일 종가에서" : "전일 종가에서") +
         " 그만큼 움직여 그 가격으로 마감하면. TQQQ≈ 는 전일 종가 × (1 + 3 × QQQ 변화율).</div>";
    el.innerHTML = h;
  }

  function tqqqCard(v) {
    var el = $("tqqq"), prev = state.tqqq_prev_close, h = "<h2>TQQQ</h2>";
    if (v.tqqq) {
      h += '<div class="px"><span class="p">' + usd(v.tqqq.price) + '</span><span class="c ' + cls(v.tqqq.price / prev - 1) + '">' +
           pct(v.tqqq.price / prev - 1) + '</span><span class="t">' + when(v.tqqq.t) + " KST</span></div>";
    } else if (v.gap && v.gap.ok) {
      h += '<div class="px"><span class="p">≈ ' + usd(v.gap.tqqqOpen) + '</span><span class="c">예상 시가</span></div>';
    } else {
      h += '<div class="prev">지금 가격 없음</div>';
    }
    h += '<div class="prev">전일 종가 ' + usd(prev) + "</div>";
    el.innerHTML = h;
  }

  function fx(v) {
    var f = v.fx;
    $("fx").innerHTML = f ? "USD/KRW <b>" + num(f.price, 2) + "</b> · " + (f.live ? when(f.t) : f.date.slice(5).replace("-", "/")) : "USD/KRW –";
  }

  function alerts(v) {
    $("alerts").innerHTML = v.warnings.map(function (w) { return '<div class="alert">⛔ ' + w + "</div>"; }).join("");
  }

  function foot(v) {
    var p = !proxyUrl ? "실시간 프록시 주소 미설정 (assets/config.js)"
          : lastOk && lastTry === lastOk ? "실시간 연결됨 · " + when(lastOk) + " 받음 (30초마다)"
          : "실시간 연결 끊김 · 마지막 시도 " + when(lastTry);
    $("foot").innerHTML = "<b>기준</b> " + v.asOf + " 종가 (" + state.price_basis + ") · 자동 기록 " + when(v.generatedAt) + " KST<br>" +
      "<b>규칙</b> 50·200일선 둘 다 아래 = 밤, 하나라도 위 = 낮 · 밤에 RSI2 &lt; 15 사냥 50%, &lt; 5 사냥 100%, 사냥 중 RSI2 &gt; 50 청산 · 사냥 중 선 회복 = 그대로 낮<br>" +
      "<b>실시간</b> " + p + (fakeNow != null ? " · <b>시험 시계</b> " + T.fmtKst(now()) : "");
  }

  function render() {
    if (!state) {
      $("banner").innerHTML = stateErr ? "기준 데이터(state.json)를 불러오지 못했습니다: " + stateErr : "불러오는 중…";
      return;
    }
    var v = T.buildView(state, quotes, now());
    banner(v); alerts(v); card(v); tqqqCard(v); fx(v); foot(v);
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
