/* TQHD 판정 규칙 (JS 쪽) + 화면에 보여줄 내용 계산.
 * 같은 공식이 scripts/tqhd.py 에 있다. 둘은 tests/test_cross.py 로 대조한다 (오차 1e-9 이내).
 * 여기에는 DOM 이 없다: 브라우저(app.js)와 테스트(V8)가 똑같이 이 파일을 쓴다. */
var TQHD = (function () {
  "use strict";

  var FAST = 50, SLOW = 200, HUNT_HALF = 15, HUNT_FULL = 5, HUNT_EXIT = 50;
  var DAY = "day", NIGHT = "night", HUNT = "hunt";

  // 실시간 값이 '지금 값'으로 인정되는 최대 나이
  var QQQ_MAX_AGE = 5 * 60 * 1000;          // 장중 QQQ: 5분
  var NQ_MAX_AGE = 30 * 60 * 1000;          // 선물: 야후는 약 10분 지연 → 30분 넘게 그대로면 멈춘 것
  var CLOSE_GRACE = 2 * 60 * 1000;

  // ── RSI2 (Wilder) ─────────────────────────────
  function rsiFrom(g, l) {
    if (l === 0) return 100;
    return 100 - 100 / (1 + g / l);
  }

  function rsiStep(prevClose, avgGain, avgLoss, price) {
    var diff = price - prevClose;
    var gain = diff > 0 ? diff : 0;
    var loss = diff < 0 ? -diff : 0;
    var g = avgGain + (gain - avgGain) / 2;
    var l = avgLoss + (loss - avgLoss) / 2;
    return { rsi: rsiFrom(g, l), g: g, l: l };
  }

  // ── 이동평균 · 판정 ───────────────────────────
  function liveSma(sumPrev, n, price) { return (sumPrev + price) / n; }

  /* 두 선 다 같거나 아래(<=)면 밤. 하나라도 위(>)면 낮. */
  function isNight(price, smaFast, smaSlow) { return price <= smaFast && price <= smaSlow; }

  function nextState(prevState, prevWeight, night, rsi) {
    if (!night) return { state: DAY, weight: 100 };               // 사냥 중 선 회복도 청산 없이 낮
    if (rsi < HUNT_FULL) return { state: HUNT, weight: 100 };
    if (rsi < HUNT_HALF) return { state: HUNT, weight: 50 };      // 100% 에서 5~15 로 올라오면 50%
    if (prevState === HUNT) {
      if (rsi > HUNT_EXIT) return { state: NIGHT, weight: 0 };
      return { state: HUNT, weight: prevWeight };                 // 15~50: 직전 비중 유지
    }
    return { state: NIGHT, weight: 0 };
  }

  function evaluate(base, price) {
    var s50 = liveSma(base.sum_prev_49, FAST, price);
    var s200 = liveSma(base.sum_prev_199, SLOW, price);
    var r = rsiStep(base.qqq_prev_close, base.wilder_avg_gain, base.wilder_avg_loss, price);
    var night = isNight(price, s50, s200);
    var st = nextState(base.prev_state, base.prev_weight, night, r.rsi);
    return { sma50: s50, sma200: s200, rsi2: r.rsi, night: night, state: st.state, weight: st.weight };
  }

  // ── 임계 가격 ─────────────────────────────────
  function crossPrice(sumPrev, n) { return sumPrev / (n - 1); }

  function rsiPrice(prevClose, avgGain, avgLoss, target) {
    var flat = rsiFrom(avgGain / 2, avgLoss / 2);
    var rs = target / (100 - target);
    if (target > flat) return prevClose + (rs * avgLoss - avgGain);
    if (target < flat) return prevClose - (avgGain / rs - avgLoss);
    return prevClose;
  }

  function levels(base) {
    var g = base.wilder_avg_gain, l = base.wilder_avg_loss, c = base.qqq_prev_close;
    return {
      sma50: crossPrice(base.sum_prev_49, FAST),
      sma200: crossPrice(base.sum_prev_199, SLOW),
      hunt_half: rsiPrice(c, g, l, HUNT_HALF),
      hunt_full: rsiPrice(c, g, l, HUNT_FULL),
      hunt_exit: rsiPrice(c, g, l, HUNT_EXIT)
    };
  }

  function same(a, b) { return a.state === b.state && a.weight === b.weight; }

  /* 지금 가격에서 아래·위로 가장 가까운 '상태가 바뀌는 가격'. */
  function changes(base, price) {
    var lv = levels(base), bps = [];
    for (var k in lv) if (isFinite(lv[k]) && lv[k] > 0) bps.push(lv[k]);
    bps.sort(function (a, b) { return a - b; });
    var cur = evaluate(base, price), down = null, up = null, i, e;
    for (i = bps.length - 1; i >= 0 && !down; i--) {
      if (bps[i] >= price) continue;
      e = evaluate(base, bps[i] * (1 - 1e-9));                 // 그 가격 바로 아래
      if (!same(e, cur)) down = { price: bps[i], state: e.state, weight: e.weight };
    }
    for (i = 0; i < bps.length && !up; i++) {
      if (bps[i] < price) continue;
      e = evaluate(base, bps[i] * (1 + 1e-9));                 // 그 가격 바로 위
      if (!same(e, cur)) up = { price: bps[i], state: e.state, weight: e.weight };
    }
    return { down: down, up: up };
  }

  function tqqqAt(base, qqqPrice) {
    if (!base.tqqq_prev_close) return null;
    return base.tqqq_prev_close * (1 + 3 * (qqqPrice / base.qqq_prev_close - 1));
  }

  // ── 시간 ──────────────────────────────────────
  function ms(iso) { return Date.parse(iso); }

  function pad(n) { return (n < 10 ? "0" : "") + n; }

  /* 한국 시간 표기 (한국은 서머타임 없음 → UTC+9 고정). */
  function fmtKst(t, withDate) {
    if (t == null) return "–";
    var d = new Date(t + 9 * 3600 * 1000);
    var hm = pad(d.getUTCHours()) + ":" + pad(d.getUTCMinutes());
    return withDate === false ? hm : (d.getUTCMonth() + 1) + "/" + d.getUTCDate() + " " + hm;
  }

  /* 미국 동부 시간의 날짜 (서머타임: 3월 둘째 일요일 ~ 11월 첫째 일요일). */
  function nthSunday(y, m, n) {
    var d = new Date(Date.UTC(y, m, 1));
    var first = (7 - d.getUTCDay()) % 7 + 1;
    return first + 7 * (n - 1);
  }
  function etOffsetHours(t) {
    var y = new Date(t).getUTCFullYear();
    var start = Date.UTC(y, 2, nthSunday(y, 2, 2), 7);       // 02:00 EST = 07:00 UTC
    var end = Date.UTC(y, 10, nthSunday(y, 10, 1), 6);       // 02:00 EDT = 06:00 UTC
    return (t >= start && t < end) ? -4 : -5;
  }
  function etDate(t) {
    var d = new Date(t + etOffsetHours(t) * 3600 * 1000);
    return d.getUTCFullYear() + "-" + pad(d.getUTCMonth() + 1) + "-" + pad(d.getUTCDate());
  }
  function weekdayOf(isoDate) { return new Date(isoDate + "T12:00:00Z").getUTCDay(); }

  // ── 지금 어떤 때인가 ──────────────────────────
  /* live   : as_of 다음 거래일 장중
     closed : 그 거래일 장 마감 뒤, 아직 Actions 가 기록 전
     gap    : 다음 거래일 개장 전 (주말·휴장·장 시작 전)
     stale  : state.json 이 한 거래일 넘게 뒤처짐 (Actions 멈춤) */
  function marketMode(state, now) {
    var ss = (state.calendar && state.calendar.sessions) || [];
    var asOf = state.as_of, lastStarted = -1, i;
    for (i = 0; i < ss.length; i++) if (ms(ss[i].open_utc) <= now) lastStarted = i;
    var next = null;
    for (i = 0; i < ss.length; i++) if (ms(ss[i].open_utc) > now) { next = ss[i]; break; }
    var asOfIdx = -1;
    for (i = 0; i < ss.length; i++) if (ss[i].date === asOf) asOfIdx = i;
    if (asOfIdx < 0 || (!next && lastStarted === ss.length - 1 && now > ms(ss[ss.length - 1].close_utc))) {
      return { mode: "stale", session: null, next: next };
    }
    if (lastStarted <= asOfIdx) {
      return { mode: "gap", session: ss[asOfIdx], next: next, reason: gapReason(state, now, next) };
    }
    if (lastStarted === asOfIdx + 1) {
      var s = ss[lastStarted];
      return { mode: now < ms(s.close_utc) ? "live" : "closed", session: s, next: next };
    }
    return { mode: "stale", session: ss[lastStarted], next: next };
  }

  function gapReason(state, now, next) {
    var d = etDate(now), wd = weekdayOf(d), hs = (state.calendar && state.calendar.holidays) || [];
    for (var i = 0; i < hs.length; i++) if (hs[i].date === d) return { kind: "holiday", name: hs[i].name };
    if (wd === 0 || wd === 6) return { kind: "weekend", name: "주말" };
    if (next && next.date === d) return { kind: "premarket", name: "장 시작 전" };
    return { kind: "afterhours", name: "장 마감 후" };
  }

  // ── 화면 내용 ─────────────────────────────────
  var STATE_LABEL = { day: "☀️ 낮", night: "🌙 밤", hunt: "🏹 사냥" };
  function stateText(s, w) {
    if (!s) return "–";
    return STATE_LABEL[s] + (s === HUNT ? " " + w + "%" : "");
  }
  function action(s, w) {
    if (s === DAY) return "TQQQ 100% 보유";
    if (s === NIGHT) return "전액 현금";
    if (s === HUNT) return "TQQQ " + w + "% 보유";
    return "";
  }

  function quoteOf(quotes, key) {
    if (!quotes || !quotes.quotes) return null;
    var q = quotes.quotes[key];
    if (!q || typeof q.price !== "number" || !(q.price > 0) || typeof q.time !== "number") return null;
    return { price: q.price, t: q.time * 1000 };
  }

  /* 화면 전체에 필요한 값. quotes 가 null 이면 프록시 실패. now 는 epoch ms. */
  function buildView(state, quotes, now) {
    var base = state;
    var mm = marketMode(state, now);
    var conf = state.confirmed;
    var v = {
      mode: mm.mode, session: mm.session, next: mm.next, reason: mm.reason || null,
      confirmed: { state: conf.state, weight: conf.weight, text: stateText(conf.state, conf.weight),
                   date: conf.date, close: conf.close, rsi2: conf.rsi2 },
      generatedAt: ms(state.generated_at), asOf: state.as_of,
      proxyOk: !!(quotes && quotes.quotes),
      live: null, gap: null, ref: null, warnings: [],
      qqq: null, tqqq: null, fx: null, nq: null
    };
    var qqq = quoteOf(quotes, "QQQ"), tqqq = quoteOf(quotes, "TQQQ");
    var nq = quoteOf(quotes, "NQ"), fx = quoteOf(quotes, "USDKRW");

    // 환율: 실시간 → 없으면 state.json 의 마지막 값
    if (fx) v.fx = { price: fx.price, t: fx.t, live: true };
    else if (state.usdkrw) v.fx = { price: state.usdkrw.price, date: state.usdkrw.date, live: false };

    if (mm.mode === "stale") {
      v.warnings.push("기준 데이터가 멈췄습니다 (마지막 기준 " + state.as_of + " 종가, 만든 시각 " +
        fmtKst(v.generatedAt) + "). 자동 갱신(GitHub Actions)을 확인하세요. 지금 상태 계산을 멈춥니다.");
    }

    if (mm.mode === "live" || mm.mode === "closed") {
      var s = mm.session;
      var fresh;
      if (!v.proxyOk) {
        v.live = { ok: false, why: "disconnected", text: "실시간 연결 끊김, 전일 종가 기준만 유효" };
      } else if (!qqq) {
        v.live = { ok: false, why: "missing", text: "실시간 QQQ 가격 없음, 전일 종가 기준만 유효" };
      } else {
        fresh = mm.mode === "live"
          ? (qqq.t >= ms(s.open_utc) && now - qqq.t <= QQQ_MAX_AGE)
          : (qqq.t >= ms(s.close_utc) - CLOSE_GRACE);
        if (!fresh) {
          v.live = { ok: false, why: "frozen", lastT: qqq.t,
                     text: "데이터 멈춤 · 마지막 갱신 " + fmtKst(qqq.t) + " (KST), 전일 종가 기준만 유효" };
        } else {
          var e = evaluate(base, qqq.price);
          v.live = { ok: true, t: qqq.t, price: qqq.price, eval: e, text: stateText(e.state, e.weight),
                     differs: !same(e, conf), closing: mm.mode === "closed" };
          v.ref = { kind: mm.mode === "live" ? "now" : "close", price: qqq.price, t: qqq.t };
        }
      }
      if (qqq && v.live && v.live.ok) v.qqq = { price: qqq.price, t: qqq.t };
      if (tqqq && v.live && v.live.ok && (mm.mode === "live" ? (tqqq.t >= ms(s.open_utc) && now - tqqq.t <= QQQ_MAX_AGE)
                                         : tqqq.t >= ms(s.close_utc) - CLOSE_GRACE)) {
        v.tqqq = { price: tqqq.price, t: tqqq.t };
      }
    }

    if (mm.mode === "gap") {
      var g = { reason: mm.reason, next: mm.next, ok: false, frozen: false, text: "" };
      var ref = state.nq_prev_settle, refT = state.nq_prev_settle_time ? ms(state.nq_prev_settle_time) : null;
      if (!v.proxyOk) {
        g.text = "실시간 연결 끊김, 선물 값을 받지 못했습니다";
      } else if (!nq) {
        g.text = "선물 시세 없음";
      } else if (!ref) {
        g.text = "기준 정산가가 없어 예상치를 낼 수 없습니다";
      } else if (refT && nq.t <= refT) {
        g.text = "선물도 휴장 · 마지막 값 " + fmtKst(nq.t) + " (전일 마감 이후 거래 없음)";
        g.frozen = true;
      } else {
        g.ok = true;
        g.frozen = now - nq.t > NQ_MAX_AGE;
        var chg = nq.price / ref - 1;
        var open = state.qqq_prev_close * (1 + chg);
        var ev = evaluate(base, open);
        g.nq = { price: nq.price, t: nq.t, chg: chg, ref: ref };
        g.qqqOpen = open;
        g.tqqqOpen = tqqqAt(base, open);
        g.eval = ev;
        g.text = stateText(ev.state, ev.weight);
        g.differs = !same(ev, conf);
        if (g.frozen) g.frozenText = "선물도 휴장 · 마지막 값 " + fmtKst(nq.t) + " (KST) 기준";
        v.ref = { kind: "open", price: open, t: nq.t };
      }
      v.gap = g;
    }

    // 기준선 카드 (state 가 멈췄으면 계산하지 않음)
    if (mm.mode !== "stale") v.card = card(base, v.ref);
    return v;
  }

  function card(base, ref) {
    var lv = levels(base), prev = base.qqq_prev_close, p = ref ? ref.price : null;
    var e = evaluate(base, p != null ? p : prev);
    function row(key, label, price, line) {
      return { key: key, label: label, price: price, line: line,
               fromRef: p != null ? price / p - 1 : null, fromPrev: price / prev - 1,
               tqqq: tqqqAt(base, price) };
    }
    return {
      prev: prev, ref: ref, refChg: p != null ? p / prev - 1 : null,
      sma50: e.sma50, sma200: e.sma200, rsi2: p != null ? e.rsi2 : null,
      rows: [
        row("sma50", "50일선", lv.sma50, e.sma50),
        row("sma200", "200일선", lv.sma200, e.sma200),
        row("hunt_half", "사냥 절반 (RSI2 15)", lv.hunt_half),
        row("hunt_full", "사냥 전액 (RSI2 5)", lv.hunt_full),
        row("hunt_exit", "사냥 청산 (RSI2 50)", lv.hunt_exit)
      ],
      changes: changes(base, p != null ? p : prev),
      basisIsPrev: p == null,
      tqqqPrev: base.tqqq_prev_close
    };
  }

  return {
    FAST: FAST, SLOW: SLOW, HUNT_HALF: HUNT_HALF, HUNT_FULL: HUNT_FULL, HUNT_EXIT: HUNT_EXIT,
    rsiFrom: rsiFrom, rsiStep: rsiStep, liveSma: liveSma, isNight: isNight, nextState: nextState,
    evaluate: evaluate, crossPrice: crossPrice, rsiPrice: rsiPrice, levels: levels, changes: changes,
    tqqqAt: tqqqAt, marketMode: marketMode, buildView: buildView, card: card, stateText: stateText, action: action,
    fmtKst: fmtKst, etDate: etDate
  };
})();

if (typeof module !== "undefined" && module.exports) module.exports = TQHD;
