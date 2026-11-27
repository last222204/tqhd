/* TQHD 실시간 프록시 (Cloudflare Workers, 무료 티어).
 * GET /quotes → QQQ · TQQQ · NQ=F · USD/KRW 를 JSON 으로. CORS 허용, 25초 캐시.
 * 가격마다 거래소 시각(time, 초)을 같이 준다. 화면은 그 시각으로 '멈춘 값'을 걸러낸다.
 *   QQQ·TQQQ: 1분봉 (프리·애프터 포함) → price/time(정규장) + last(시간외 포함 마지막 체결) + regular_close(장 마감 뒤에만)
 *   NQ      : 5분봉 (5일) → price/time + bars [[시각, 종가], ...] (선물 추정의 기준점 찾기용)
 * 같은 동작을 하는 로컬 시험용 쌍둥이: tools/dev_server.py */

export const SYMBOLS = { QQQ: "QQQ", TQQQ: "TQQQ", NQ: "NQ=F", USDKRW: "KRW=X" };
export const CACHE_SECONDS = 25;
export const LOOKBACK_SECONDS = 4 * 86400;   // 주말·연휴 뒤에도 마지막 체결이 들어오게 4일
const YAHOO = "https://query1.finance.yahoo.com/v8/finance/chart/";

/* 야후 range=1d 는 정규장이 열리기 전엔 '그날' 프리장 봉을 안 준다 → 1분봉은 기간을 직접 정해서 받는다 */
export function urlFor(key, nowSec) {
  var base = YAHOO + encodeURIComponent(SYMBOLS[key]);
  if (key === "QQQ" || key === "TQQQ") {
    return base + "?interval=1m&period1=" + (nowSec - LOOKBACK_SECONDS) + "&period2=" + nowSec + "&includePrePost=true";
  }
  if (key === "NQ") return base + "?interval=5m&range=5d&includePrePost=true";
  return base + "?interval=1d&range=5d";
}

function result(j) { return j && j.chart && j.chart.result && j.chart.result[0]; }

export function parseChart(j) {
  var r = result(j);
  var m = r && r.meta;
  if (!m || typeof m.regularMarketPrice !== "number" || typeof m.regularMarketTime !== "number") return null;
  return {
    price: m.regularMarketPrice,
    time: m.regularMarketTime,
    prev_close: typeof m.chartPreviousClose === "number" ? m.chartPreviousClose : null
  };
}

/* 값이 비어 있지 않은 봉만 [[시각, 종가], ...] */
export function bars(j) {
  var r = result(j);
  var ts = (r && r.timestamp) || [];
  var q = r && r.indicators && r.indicators.quote && r.indicators.quote[0];
  var c = (q && q.close) || [];
  var out = [];
  for (var i = 0; i < ts.length; i++) {
    if (typeof ts[i] === "number" && typeof c[i] === "number" && c[i] > 0) out.push([ts[i], c[i]]);
  }
  return out;
}

/* 시간외 포함 마지막 체결: 마지막으로 비어 있지 않은 1분봉 종가와 그 봉 시각 */
export function lastTrade(j) {
  var b = bars(j);
  return b.length ? { price: b[b.length - 1][1], time: b[b.length - 1][0] } : null;
}

/* 오늘 정규장 종가: 정규장 시각이 오늘 정규장 끝 이후일 때만 (장중·장 전엔 null) */
export function regularClose(j) {
  var r = result(j), m = r && r.meta;
  var end = m && m.currentTradingPeriod && m.currentTradingPeriod.regular && m.currentTradingPeriod.regular.end;
  if (!m || typeof end !== "number" || typeof m.regularMarketPrice !== "number" || typeof m.regularMarketTime !== "number") return null;
  return m.regularMarketTime >= end ? { price: m.regularMarketPrice, time: m.regularMarketTime } : null;
}

export function parseFor(key, j) {
  var q = parseChart(j);
  if (!q) return null;
  if (key === "QQQ" || key === "TQQQ") { q.last = lastTrade(j); q.regular_close = regularClose(j); }
  if (key === "NQ") q.bars = bars(j);
  return q;
}

export async function getQuotes(fetchFn, nowSec) {
  var keys = Object.keys(SYMBOLS);
  var results = await Promise.all(keys.map(function (k) {
    return fetchFn(urlFor(k, nowSec), { headers: { "User-Agent": "Mozilla/5.0", "Accept": "application/json" } })
      .then(function (res) { return res.ok ? res.json() : Promise.reject(new Error("HTTP " + res.status)); })
      .then(function (j) { return parseFor(k, j) || Promise.reject(new Error("형식 다름")); })
      .then(function (q) { return { ok: true, q: q }; }, function (e) { return { ok: false, err: String(e && e.message || e) }; });
  }));
  var out = { fetched_at: nowSec, quotes: {}, errors: {} };
  keys.forEach(function (k, i) {
    if (results[i].ok) out.quotes[k] = results[i].q;
    else { out.quotes[k] = null; out.errors[k] = results[i].err; }
  });
  return out;
}

var CORS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET, OPTIONS",
  "Access-Control-Max-Age": "86400"
};

function json(body, status, extra) {
  var h = Object.assign({ "Content-Type": "application/json; charset=utf-8" }, CORS, extra || {});
  return new Response(JSON.stringify(body), { status: status, headers: h });
}

export default {
  async fetch(request, env, ctx) {
    var url = new URL(request.url);
    if (request.method === "OPTIONS") return new Response(null, { status: 204, headers: CORS });
    if (url.pathname !== "/quotes") return json({ error: "GET /quotes 만 있습니다" }, 404);

    var cache = caches.default;
    var key = new Request(url.origin + "/quotes", { method: "GET" });
    var hit = await cache.match(key);
    if (hit) return hit;

    var body = await getQuotes(fetch, Math.floor(Date.now() / 1000));
    var anyOk = Object.keys(body.quotes).some(function (k) { return body.quotes[k]; });
    var res = json(body, anyOk ? 200 : 502, { "Cache-Control": "public, max-age=" + CACHE_SECONDS });
    if (anyOk) ctx.waitUntil(cache.put(key, res.clone()));
    return res;
  }
};
