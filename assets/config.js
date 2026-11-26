/* 배포한 프록시 주소. Cloudflare Workers 에 올린 뒤 여기 한 줄만 바꾼다.
 * 비어 있으면 실시간 없이 '전일 종가 기준'만 보여준다. (localhost 에서는 tools/dev_server.py 의 /quotes 를 쓴다) */
window.TQHD_CONFIG = {
  proxyUrl: ""
};
