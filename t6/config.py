"""전략 규칙과 경로 상수. 규칙 숫자는 이 파일 한 곳에만 둔다."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
DB_PATH = DATA_DIR / "t6.db"
BACKUP_DIR = DATA_DIR / "backup"

# ── 전략 규칙 (T6) ────────────────────────────────
SIGNAL_SYMBOL = "QQQ"        # 신호는 QQQ로만 판정
RISK_ON = "TQQQ"             # ☀️ 하나라도 위
RISK_OFF = "SGOV"            # ☂️ 둘 다 아래 (판정·시뮬레이터 내부 이름. 바꾸지 않는다)
REFUGE_LABEL = "현금(달러)"   # 화면에 보이는 피신 자리 이름 (피신 자금은 현금으로 둔다)


def label(signal: str | None) -> str:
    """판정 값(TQQQ/SGOV)을 화면 표기로. 피신은 '현금(달러)'."""
    return REFUGE_LABEL if signal == RISK_OFF else (signal or "–")
SMA_FAST = 50
SMA_SLOW = 200
BORDER_PCT = 0.005           # 경계선 ±0.5%
VOL_WINDOW = 20              # 20거래일 변동성
VOL_ALERT = 0.35             # 연율 35%

INITIAL_KRW = 10_000_000     # 처음 1,000만 원
MONTHLY_KRW = 1_000_000      # 매월 100만 원
CONTRIBUTION_DAY = 17        # 매월 17일 (휴장이면 다음 거래일)

# ── 데이터 ───────────────────────────────────────
FX_SYMBOL = "KRW=X"
CORE_SYMBOLS = [SIGNAL_SYMBOL, RISK_ON, RISK_OFF, FX_SYMBOL]
# 시뮬레이터·변동성 비교용 (QLD 2배, BIL 피난처, ^IRX 단기금리, ^SOX 반도체 지수)
EXTRA_SYMBOLS = ["QLD", "BIL", "^IRX", "^SOX"]
SYMBOLS = CORE_SYMBOLS + EXTRA_SYMBOLS
# 일봉 종가가 늦을 때 1분봉으로 잠정 종가를 만드는 종목 (매일 판정·매매에 쓰는 것만)
PROVISIONAL_SYMBOLS = [SIGNAL_SYMBOL, RISK_ON, RISK_OFF]
# Yahoo 환율(KRW=X)은 2003-12부터라 그 이전은 FRED 공식 환율(DEXKOUS)로 채운다. 키 필요 없음.
FRED_FX = "DEXKOUS"
SOX_SYMBOL = "^SOX"
# QQQ는 1999년 상장. ^SOX 1년 변동성을 1999년부터 내려면 1998년 데이터가 필요하다.
HISTORY_START = "1998-01-01"
VOL_LONG = 252               # 1년 변동성 (거래일)
VOL_BASE_FROM = "1999-01-01" # 기준(중간값) 계산 시작
# 같은 장 마감에 대해 데이터가 아직 안 올라왔을 때 너무 자주 다시 받지 않도록
RETRY_MINUTES = 15
# 수동 새로고침 버튼 대기 시간 (사이트가 외부에 열려 있어 연타 방지)
MANUAL_COOLDOWN_SEC = 60
