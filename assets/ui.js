/* 화면 문구만 정하는 순수 함수 (DOM 없음, 판정 계산 없음). 판정은 core.js 가 하고, 여기서는 그 결과를 말로 옮긴다.
 * 테스트가 V8 로 이 파일을 그대로 돌린다 (tests/test_ui.py). */
var TQHD_UI = (function () {
  "use strict";

  var EMOJI = { day: "☀️", night: "🌙", hunt: "🏹" };

  function word(s, w) {
    if (s === "day") return "낮";
    if (s === "night") return "밤";
    if (s === "hunt") return "사냥 " + w + "%";
    return "–";
  }

  /* 상태가 뜻하는 TQQQ 비중 (낮 100, 밤 0, 사냥은 그 비중) */
  function weightOf(s, w) { return s === "day" ? 100 : s === "hunt" ? w : 0; }

  /* 직전 거래일 상태 → 오늘 상태 의 전환만으로 할 일을 낸다 (보유 여부는 가정하지 않음). */
  function todo(prev, cur) {
    var a = weightOf(prev.state, prev.weight), b = weightOf(cur.state, cur.weight), d = b - a;
    if (d === 0) return { text: b === 0 ? "할 일 없음" : "보유 유지", kind: "hold" };
    if (d > 0) {
      if (a === 0) return { text: b === 100 ? "TQQQ 전액 매수" : "TQQQ 절반 매수", kind: "buy" };
      return { text: "TQQQ 절반 추가 매수", kind: "buy" };
    }
    return { text: b === 0 ? "전량 매도" : "절반 매도", kind: "sell" };
  }

  /* 화면 전체(buildView 결과)에서 오늘 할 일 한 줄 */
  function todayLine(v) {
    if (v.mode === "stale") return { text: "데이터 멈춤 · 판단 보류", kind: "wait" };
    if (v.mode === "gap") {
      var k = v.reason && v.reason.kind;
      if (k === "holiday" || k === "weekend") return { text: "휴장 · 대기", kind: "wait" };
      if (k === "premarket") return { text: "개장 전 · 대기", kind: "wait" };
      return { text: "장 마감 · 대기", kind: "wait" };
    }
    if (!v.live || !v.live.ok) return { text: "실시간 없음 · 판단 보류", kind: "wait" };
    return todo(v.confirmed, v.live.eval);
  }

  /* 상황 배지 (작은 이모지 + 짧은 글) */
  function badge(v) {
    if (v.mode === "stale") return { emoji: "⚠️", text: "기준 데이터 멈춤" };
    if (v.mode === "gap") {
      var r = v.reason || {};
      if (r.kind === "holiday") {
        var e = r.name === "추수감사절" ? "🏈" : r.name === "크리스마스" ? "🎄" : r.name === "독립기념일" ? "🇺🇸" : "🏛️";
        return { emoji: e, text: r.name + " 휴장" };
      }
      if (r.kind === "weekend") return { emoji: "💤", text: "주말 휴장" };
      if (r.kind === "premarket") return { emoji: "⏳", text: "개장 전" };
      return { emoji: "⏳", text: "장 마감 후" };
    }
    if (v.live && !v.live.ok) {
      return v.live.why === "frozen" ? { emoji: "⚠️", text: "데이터 멈춤" } : { emoji: "🔌", text: "실시간 끊김" };
    }
    return null;
  }

  return { EMOJI: EMOJI, word: word, weightOf: weightOf, todo: todo, todayLine: todayLine, badge: badge };
})();

if (typeof module !== "undefined" && module.exports) module.exports = TQHD_UI;
