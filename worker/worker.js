/* TQHD 실시간 프록시 (Cloudflare Workers, 무료 티어).
 * GET /quotes → QQQ · TQQQ · NQ=F · USD/KRW 현재가만 JSON 으로. CORS 허용, 25초 캐시.
 * 가격마다 거래소 시각(time, 초)을 같이 준다. 화면은 그 시각으로 '멈춘 값'을 걸러낸다.
 * 같은 동작을 하는 로컬 시험용 쌍둥이: tools/dev_server.py */

export const SYMBOLS = { QQQ: "QQQ", TQQQ: "TQQQ", NQ: "NQ=F", USDKRW: "KRW=X" };
export const CACHE_SECONDS = 25;
const YAHOO = "https://query1.finance.yahoo.com/v8/finance/chart/";

export function parseChart(j) {
  var r = j && j.chart && j.chart.result && j.chart.result[0];
  var m = r && r.meta;
  if (!m || typeof m.regularMarketPrice !== "number" || typeof m.regularMarketTime !== "number") return null;
  return {
    price: m.regularMarketPrice,
    time: m.regularMarketTime,
    prev_close: typeof m.chartPreviousClose === "number" ? m.chartPreviousClose : null
  };
}

export async function getQuotes(fetchFn, nowSec) {
  var keys = Object.keys(SYMBOLS);
  var results = await Promise.all(keys.map(function (k) {
    var url = YAHOO + encodeURIComponent(SYMBOLS[k]) + "?interval=1d&range=5d";
    return fetchFn(url, { headers: { "User-Agent": "Mozilla/5.0", "Accept": "application/json" } })
      .then(function (res) { return res.ok ? res.json() : Promise.reject(new Error("HTTP " + res.status)); })
      .then(function (j) { return parseChart(j) || Promise.reject(new Error("형식 다름")); })
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
