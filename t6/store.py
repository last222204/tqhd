"""SQLite 저장소. 기록은 전부 data/t6.db 파일 하나에 들어간다."""
from __future__ import annotations

import shutil
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from .config import BACKUP_DIR, DB_PATH
from .sources.base import COLUMNS

SCHEMA = """
CREATE TABLE IF NOT EXISTS prices (
    symbol    TEXT NOT NULL,
    date      TEXT NOT NULL,          -- YYYY-MM-DD (미국 거래일)
    open REAL, high REAL, low REAL,
    close     REAL,                   -- 배당 미조정 종가
    adj_close REAL,                   -- 배당 조정 종가 (신호 계산 기준)
    volume    REAL,
    provisional INTEGER NOT NULL DEFAULT 0,  -- 1 = 일봉이 늦어 1분봉으로 만든 잠정 종가
    PRIMARY KEY (symbol, date)
);
CREATE TABLE IF NOT EXISTS fetch_log (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    fetched_at TEXT NOT NULL,         -- UTC ISO
    symbol     TEXT NOT NULL,
    source     TEXT NOT NULL,
    ok         INTEGER NOT NULL,
    last_date  TEXT,
    rows       INTEGER,
    error      TEXT
);
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""


def _connect(path: Path | None = None) -> sqlite3.Connection:
    path = Path(path or DB_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.execute("PRAGMA foreign_keys = ON")
    return con


@contextmanager
def connect(path: Path | None = None):
    con = _connect(path)
    try:
        yield con
        con.commit()
    finally:
        con.close()


def init_db(path: Path | None = None) -> None:
    with connect(path) as con:
        con.executescript(SCHEMA)
        cols = {r[1] for r in con.execute("PRAGMA table_info(prices)")}
        if "provisional" not in cols:  # 예전 DB 파일 고치기
            con.execute("ALTER TABLE prices ADD COLUMN provisional INTEGER NOT NULL DEFAULT 0")


# ── 시세 ─────────────────────────────────────────
def save_prices(symbol: str, df: pd.DataFrame, path: Path | None = None) -> None:
    """종목 시세를 통째로 바꿔 넣는다.

    배당이 생길 때마다 과거 배당조정 종가 전체가 다시 계산되므로
    덧붙이지 않고 매번 전체를 교체한다.
    """
    prov = df["provisional"] if "provisional" in df else pd.Series(0, index=df.index)
    rows = [
        (symbol, d.strftime("%Y-%m-%d"), *[None if pd.isna(v) else float(v) for v in r], int(bool(p)))
        for d, r, p in zip(df.index, df[COLUMNS].itertuples(index=False), prov)
    ]
    with connect(path) as con:
        con.execute("DELETE FROM prices WHERE symbol = ?", (symbol,))
        con.executemany(
            "INSERT INTO prices (symbol, date, open, high, low, close, adj_close, volume, provisional) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            rows,
        )


def load_prices(symbol: str, path: Path | None = None) -> pd.DataFrame:
    with connect(path) as con:
        df = pd.read_sql_query(
            "SELECT date, open, high, low, close, adj_close, volume, provisional FROM prices "
            "WHERE symbol = ? ORDER BY date",
            con,
            params=(symbol,),
        )
    df["date"] = pd.to_datetime(df["date"])
    df["provisional"] = df["provisional"].astype(bool)
    return df.set_index("date")


def last_is_provisional(symbol: str, path: Path | None = None) -> bool:
    with connect(path) as con:
        row = con.execute(
            "SELECT provisional FROM prices WHERE symbol = ? ORDER BY date DESC LIMIT 1", (symbol,)
        ).fetchone()
    return bool(row and row[0])


def last_price_date(symbol: str, path: Path | None = None) -> str | None:
    with connect(path) as con:
        row = con.execute("SELECT MAX(date) FROM prices WHERE symbol = ?", (symbol,)).fetchone()
    return row[0] if row else None


# ── 받기 기록 ─────────────────────────────────────
def log_fetch(symbol: str, source: str, ok: bool, last_date: str | None, rows: int | None,
              error: str | None = None, path: Path | None = None, at: datetime | None = None) -> None:
    with connect(path) as con:
        con.execute(
            "INSERT INTO fetch_log (fetched_at, symbol, source, ok, last_date, rows, error) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ((at or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat(timespec="seconds"), symbol, source,
             int(ok), last_date, rows, error),
        )


def last_fetch(symbol: str | None = None, ok: bool | None = None, path: Path | None = None) -> dict | None:
    q = "SELECT fetched_at, symbol, source, ok, last_date, rows, error FROM fetch_log"
    cond, params = [], []
    if symbol:
        cond.append("symbol = ?")
        params.append(symbol)
    if ok is not None:
        cond.append("ok = ?")
        params.append(int(ok))
    if cond:
        q += " WHERE " + " AND ".join(cond)
    q += " ORDER BY id DESC LIMIT 1"
    with connect(path) as con:
        row = con.execute(q, params).fetchone()
    if not row:
        return None
    keys = ["fetched_at", "symbol", "source", "ok", "last_date", "rows", "error"]
    out = dict(zip(keys, row))
    out["fetched_at"] = datetime.fromisoformat(out["fetched_at"])
    return out


def data_version(path: Path | None = None) -> int:
    """화면 캐시를 새로 그릴지 판단하는 번호 (받을 때마다 커진다)."""
    with connect(path) as con:
        row = con.execute("SELECT COALESCE(MAX(id), 0) FROM fetch_log").fetchone()
    return int(row[0])


# ── 설정 ─────────────────────────────────────────
def get_setting(key: str, default: str | None = None, path: Path | None = None) -> str | None:
    with connect(path) as con:
        row = con.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row[0] if row else default


def set_setting(key: str, value: str, path: Path | None = None) -> None:
    with connect(path) as con:
        con.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )


# ── 백업 ─────────────────────────────────────────
def backup_db(path: Path | None = None) -> Path:
    """DB 파일을 data/backup/t6_YYYYmmdd_HHMMSS.db 로 안전하게 복사한다."""
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    dest = BACKUP_DIR / f"t6_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
    src = _connect(path)
    try:
        dst = sqlite3.connect(dest)
        with dst:
            src.backup(dst)
        dst.close()
    finally:
        src.close()
    return dest


def copy_file(src: Path, dest: Path) -> None:
    shutil.copy2(src, dest)
