# -*- coding: utf-8 -*-
"""
데이터베이스 헬퍼
- DATABASE_URL 환경변수 있으면 → PostgreSQL (Render 배포용, 재시작해도 데이터 유지)
- 없으면                       → SQLite     (로컬 개발용)
"""

import os
import hashlib
from pathlib import Path
from contextlib import contextmanager

try:
    import bcrypt
    _BCRYPT = True
except ImportError:
    _BCRYPT = False

# ── 드라이버 선택 ────────────────────────────────────────────────────────────
_DATABASE_URL = os.environ.get("DATABASE_URL", "")
# Render가 발급하는 URL은 postgres:// 로 시작하지만 psycopg2는 postgresql:// 요구
if _DATABASE_URL.startswith("postgres://"):
    _DATABASE_URL = _DATABASE_URL.replace("postgres://", "postgresql://", 1)

_USE_PG = bool(_DATABASE_URL)

if _USE_PG:
    import psycopg2
    import psycopg2.extras
    import psycopg2.pool
    _PH = "%s"
    _IntegrityError = psycopg2.IntegrityError
    _pool: "psycopg2.pool.ThreadedConnectionPool | None" = None
else:
    import sqlite3
    _PH = "?"
    _IntegrityError = sqlite3.IntegrityError
    _DB_PATH = Path(__file__).parent / "iran_oil.db"


# ── 연결 풀 (PostgreSQL) ─────────────────────────────────────────────────────
def _ensure_pool() -> None:
    global _pool
    if _pool is None:
        _pool = psycopg2.pool.ThreadedConnectionPool(1, 5, _DATABASE_URL)


# ── 커넥션 컨텍스트 매니저 ──────────────────────────────────────────────────
@contextmanager
def _get_conn():
    if _USE_PG:
        _ensure_pool()
        conn = _pool.getconn()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            _pool.putconn(conn)
    else:
        conn = sqlite3.connect(str(_DB_PATH))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


def _cursor(conn):
    """모드에 맞는 커서 반환 (PG: dict 형태로 row 반환)."""
    if _USE_PG:
        return conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    return conn.cursor()


# ── 품목 정의 ────────────────────────────────────────────────────────────────
ITEM_KR = [
    "라면", "달걀", "우유", "식용유", "생수",
    "샴푸", "택배비", "휘발유", "전기요금", "가스요금",
]
# 컬럼명은 항상 double-quote — SQLite·PostgreSQL 공용
BUDGET_COLS = [f'"budget_{item}"' for item in ITEM_KR]

_SETTINGS_DEFAULTS = {
    "라면": 5000, "달걀": 6500, "우유": 8800, "식용유": 1500,
    "생수": 4800, "샴푸": 2500, "택배비": 10000,
    "휘발유": 80000, "전기요금": 45000, "가스요금": 55000,
}


# ── 테이블 생성 ──────────────────────────────────────────────────────────────
def init_db() -> None:
    if _USE_PG:
        pk      = "SERIAL PRIMARY KEY"
        ts_type = "TIMESTAMP"
        ts_now  = "NOW()"
    else:
        pk      = "INTEGER PRIMARY KEY AUTOINCREMENT"
        ts_type = "TEXT"
        ts_now  = "(datetime('now','localtime'))"   # SQLite: 함수 DEFAULT는 괄호 필요

    hist_cols = ",\n    ".join(
        f'"budget_{item}" INTEGER NOT NULL DEFAULT 0' for item in ITEM_KR
    )
    set_cols = ",\n    ".join(
        f'"budget_{item}" INTEGER NOT NULL DEFAULT {_SETTINGS_DEFAULTS[item]}'
        for item in ITEM_KR
    )

    stmts = [
        f"""CREATE TABLE IF NOT EXISTS users (
    id         {pk},
    name       TEXT      NOT NULL,
    email      TEXT      NOT NULL UNIQUE,
    password   TEXT      NOT NULL,
    created_at {ts_type} NOT NULL DEFAULT {ts_now}
)""",
        f"""CREATE TABLE IF NOT EXISTS living_cost_history (
    id            {pk},
    user_id       INTEGER   NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    recorded_at   {ts_type} NOT NULL DEFAULT {ts_now},
    scenario      TEXT      NOT NULL,
    total_now     INTEGER   NOT NULL,
    total_pred    INTEGER   NOT NULL,
    monthly_extra INTEGER   NOT NULL,
    {hist_cols}
)""",
        f"""CREATE TABLE IF NOT EXISTS user_settings (
    user_id    INTEGER   PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    updated_at {ts_type} NOT NULL DEFAULT {ts_now},
    {set_cols}
)""",
    ]

    with _get_conn() as conn:
        cur = _cursor(conn)
        for stmt in stmts:
            cur.execute(stmt)


# ── 비밀번호 유틸 ────────────────────────────────────────────────────────────
def hash_password(plain: str) -> str:
    if _BCRYPT:
        return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()
    return hashlib.sha256(plain.encode()).hexdigest()


def verify_password(plain: str, hashed: str) -> bool:
    if _BCRYPT:
        try:
            return bcrypt.checkpw(plain.encode(), hashed.encode())
        except Exception:
            return False
    return hashlib.sha256(plain.encode()).hexdigest() == hashed


# ── users CRUD ───────────────────────────────────────────────────────────────
def create_user(name: str, email: str, plain_password: str) -> int:
    """신규 회원 생성. 이메일 중복 시 ValueError."""
    pw_hash = hash_password(plain_password)
    try:
        with _get_conn() as conn:
            cur = _cursor(conn)
            if _USE_PG:
                cur.execute(
                    "INSERT INTO users (name, email, password) VALUES (%s, %s, %s) RETURNING id",
                    (name, email, pw_hash),
                )
                user_id = cur.fetchone()["id"]
                cur.execute(
                    "INSERT INTO user_settings (user_id) VALUES (%s)", (user_id,)
                )
            else:
                cur.execute(
                    "INSERT INTO users (name, email, password) VALUES (?, ?, ?)",
                    (name, email, pw_hash),
                )
                user_id = cur.lastrowid
                cur.execute(
                    "INSERT INTO user_settings (user_id) VALUES (?)", (user_id,)
                )
            return user_id
    except _IntegrityError:
        raise ValueError(f"이미 사용 중인 이메일입니다: {email}")


def get_user_by_email(email: str):
    with _get_conn() as conn:
        cur = _cursor(conn)
        cur.execute(f"SELECT * FROM users WHERE email = {_PH}", (email,))
        return cur.fetchone()


def get_user_by_id(user_id: int):
    with _get_conn() as conn:
        cur = _cursor(conn)
        cur.execute(
            f"SELECT id, name, email, created_at FROM users WHERE id = {_PH}",
            (user_id,),
        )
        return cur.fetchone()


# ── living_cost_history CRUD ─────────────────────────────────────────────────
def save_history(
    user_id: int,
    scenario: str,
    total_now: int,
    total_pred: int,
    monthly_extra: int,
    budgets: dict,
) -> int:
    vals    = [budgets.get(item, 0) for item in ITEM_KR]
    cols_sql = ", ".join(BUDGET_COLS)
    ph_sql   = ", ".join([_PH] * len(BUDGET_COLS))
    sql = (
        f"INSERT INTO living_cost_history"
        f" (user_id, scenario, total_now, total_pred, monthly_extra, {cols_sql})"
        f" VALUES ({_PH}, {_PH}, {_PH}, {_PH}, {_PH}, {ph_sql})"
    )
    if _USE_PG:
        sql += " RETURNING id"
    with _get_conn() as conn:
        cur = _cursor(conn)
        cur.execute(sql, [user_id, scenario, total_now, total_pred, monthly_extra, *vals])
        if _USE_PG:
            return cur.fetchone()["id"]
        return cur.lastrowid


def get_history(user_id: int, limit: int = 20) -> list:
    with _get_conn() as conn:
        cur = _cursor(conn)
        cur.execute(
            f"""SELECT * FROM living_cost_history
                WHERE user_id = {_PH}
                ORDER BY recorded_at DESC LIMIT {_PH}""",
            (user_id, limit),
        )
        return cur.fetchall()


def delete_history(record_id: int, user_id: int) -> bool:
    with _get_conn() as conn:
        cur = _cursor(conn)
        cur.execute(
            f"DELETE FROM living_cost_history WHERE id = {_PH} AND user_id = {_PH}",
            (record_id, user_id),
        )
        return cur.rowcount > 0


# ── user_settings CRUD ───────────────────────────────────────────────────────
def get_settings(user_id: int):
    with _get_conn() as conn:
        cur = _cursor(conn)
        cur.execute(
            f"SELECT * FROM user_settings WHERE user_id = {_PH}", (user_id,)
        )
        return cur.fetchone()


def update_settings(user_id: int, budgets: dict) -> None:
    ts_expr = "NOW()" if _USE_PG else "datetime('now','localtime')"
    set_clauses = ", ".join(f'"budget_{item}" = {_PH}' for item in ITEM_KR)
    vals = [budgets.get(item, 0) for item in ITEM_KR]
    with _get_conn() as conn:
        cur = _cursor(conn)
        cur.execute(
            f"UPDATE user_settings SET {set_clauses}, updated_at = {ts_expr} WHERE user_id = {_PH}",
            [*vals, user_id],
        )


# ── 직접 실행 시 DB 초기화 ───────────────────────────────────────────────────
if __name__ == "__main__":
    init_db()
    mode = "PostgreSQL" if _USE_PG else f"SQLite ({_DB_PATH})"
    print(f"DB 초기화 완료: {mode}")
