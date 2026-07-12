"""
SQLite 데이터베이스 초기화 및 헬퍼 함수
- users              : 회원 정보
- living_cost_history: 생활비 계산 이력
- user_settings      : 품목별 기본 예산 설정
"""

import sqlite3
import hashlib
import os
from datetime import datetime
from pathlib import Path

try:
    import bcrypt
    _BCRYPT = True
except ImportError:
    _BCRYPT = False

DB_PATH = Path(__file__).parent / "iran_oil.db"


# ── 연결 헬퍼 ──────────────────────────────────────────────────────────────
def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


# ── 테이블 생성 ────────────────────────────────────────────────────────────
def init_db() -> None:
    with get_conn() as conn:
        conn.executescript("""
        -- 1. 회원 테이블
        CREATE TABLE IF NOT EXISTS users (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            name        TEXT    NOT NULL,
            email       TEXT    NOT NULL UNIQUE,
            password    TEXT    NOT NULL,          -- bcrypt 해시
            created_at  TEXT    NOT NULL DEFAULT (datetime('now', 'localtime'))
        );

        -- 2. 생활비 계산 이력
        CREATE TABLE IF NOT EXISTS living_cost_history (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id         INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            recorded_at     TEXT    NOT NULL DEFAULT (datetime('now', 'localtime')),
            scenario        TEXT    NOT NULL,       -- local | hormuz | fullwar

            -- 합계
            total_now       INTEGER NOT NULL,       -- 현재 월 생활비 (원)
            total_pred      INTEGER NOT NULL,       -- 예측 월 생활비 (원)
            monthly_extra   INTEGER NOT NULL,       -- 월 추가 부담 (원)

            -- 품목별 예산 입력값 (원)
            budget_라면     INTEGER NOT NULL DEFAULT 0,
            budget_달걀     INTEGER NOT NULL DEFAULT 0,
            budget_우유     INTEGER NOT NULL DEFAULT 0,
            budget_식용유   INTEGER NOT NULL DEFAULT 0,
            budget_생수     INTEGER NOT NULL DEFAULT 0,
            budget_샴푸     INTEGER NOT NULL DEFAULT 0,
            budget_택배비   INTEGER NOT NULL DEFAULT 0,
            budget_휘발유   INTEGER NOT NULL DEFAULT 0,
            budget_전기요금 INTEGER NOT NULL DEFAULT 0,
            budget_가스요금 INTEGER NOT NULL DEFAULT 0
        );

        -- 3. 품목별 기본 예산 설정 (user당 1행)
        CREATE TABLE IF NOT EXISTS user_settings (
            user_id         INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
            updated_at      TEXT    NOT NULL DEFAULT (datetime('now', 'localtime')),

            -- 기본 예산 (원) — 앱 기본값과 동일하게 초기화
            budget_라면     INTEGER NOT NULL DEFAULT 5000,
            budget_달걀     INTEGER NOT NULL DEFAULT 6500,
            budget_우유     INTEGER NOT NULL DEFAULT 8800,
            budget_식용유   INTEGER NOT NULL DEFAULT 1500,
            budget_생수     INTEGER NOT NULL DEFAULT 4800,
            budget_샴푸     INTEGER NOT NULL DEFAULT 2500,
            budget_택배비   INTEGER NOT NULL DEFAULT 10000,
            budget_휘발유   INTEGER NOT NULL DEFAULT 80000,
            budget_전기요금 INTEGER NOT NULL DEFAULT 45000,
            budget_가스요금 INTEGER NOT NULL DEFAULT 55000
        );
        """)


# ── 비밀번호 유틸 ──────────────────────────────────────────────────────────
def hash_password(plain: str) -> str:
    if _BCRYPT:
        return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()
    # bcrypt 미설치 시 sha256 폴백 (개발 전용)
    return hashlib.sha256(plain.encode()).hexdigest()


def verify_password(plain: str, hashed: str) -> bool:
    if _BCRYPT:
        try:
            return bcrypt.checkpw(plain.encode(), hashed.encode())
        except Exception:
            return False
    return hashlib.sha256(plain.encode()).hexdigest() == hashed


# ── users CRUD ────────────────────────────────────────────────────────────
def create_user(name: str, email: str, plain_password: str) -> int:
    """신규 회원 생성. 생성된 user_id 반환. 이메일 중복 시 ValueError."""
    pw_hash = hash_password(plain_password)
    with get_conn() as conn:
        try:
            cur = conn.execute(
                "INSERT INTO users (name, email, password) VALUES (?, ?, ?)",
                (name, email, pw_hash),
            )
            user_id = cur.lastrowid
            # 기본 설정 행 자동 생성
            conn.execute(
                "INSERT INTO user_settings (user_id) VALUES (?)", (user_id,)
            )
            return user_id
        except sqlite3.IntegrityError:
            raise ValueError(f"이미 사용 중인 이메일입니다: {email}")


def get_user_by_email(email: str) -> sqlite3.Row | None:
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM users WHERE email = ?", (email,)
        ).fetchone()


def get_user_by_id(user_id: int) -> sqlite3.Row | None:
    with get_conn() as conn:
        return conn.execute(
            "SELECT id, name, email, created_at FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()


# ── living_cost_history CRUD ──────────────────────────────────────────────
BUDGET_COLS = [
    "budget_라면", "budget_달걀", "budget_우유", "budget_식용유",
    "budget_생수", "budget_샴푸", "budget_택배비",
    "budget_휘발유", "budget_전기요금", "budget_가스요금",
]

ITEM_KR = ["라면", "달걀", "우유", "식용유", "생수", "샴푸", "택배비", "휘발유", "전기요금", "가스요금"]


def save_history(
    user_id: int,
    scenario: str,
    total_now: int,
    total_pred: int,
    monthly_extra: int,
    budgets: dict,          # {"라면": 5000, ...}
) -> int:
    """계산 결과를 이력에 저장. 생성된 id 반환."""
    vals = [budgets.get(item, 0) for item in ITEM_KR]
    cols = ", ".join(BUDGET_COLS)
    placeholders = ", ".join(["?"] * len(BUDGET_COLS))
    with get_conn() as conn:
        cur = conn.execute(
            f"""INSERT INTO living_cost_history
                (user_id, scenario, total_now, total_pred, monthly_extra, {cols})
                VALUES (?, ?, ?, ?, ?, {placeholders})""",
            [user_id, scenario, total_now, total_pred, monthly_extra, *vals],
        )
        return cur.lastrowid


def get_history(user_id: int, limit: int = 20) -> list[sqlite3.Row]:
    """최근 이력 조회 (최신순)."""
    with get_conn() as conn:
        return conn.execute(
            """SELECT * FROM living_cost_history
               WHERE user_id = ?
               ORDER BY recorded_at DESC LIMIT ?""",
            (user_id, limit),
        ).fetchall()


def delete_history(record_id: int, user_id: int) -> bool:
    """본인 이력만 삭제 가능. 삭제 성공 여부 반환."""
    with get_conn() as conn:
        cur = conn.execute(
            "DELETE FROM living_cost_history WHERE id = ? AND user_id = ?",
            (record_id, user_id),
        )
        return cur.rowcount > 0


# ── user_settings CRUD ────────────────────────────────────────────────────
def get_settings(user_id: int) -> sqlite3.Row | None:
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM user_settings WHERE user_id = ?", (user_id,)
        ).fetchone()


def update_settings(user_id: int, budgets: dict) -> None:
    """품목별 기본 예산 설정 갱신."""
    set_clauses = ", ".join(f"budget_{item} = ?" for item in ITEM_KR)
    vals = [budgets.get(item, 0) for item in ITEM_KR]
    with get_conn() as conn:
        conn.execute(
            f"""UPDATE user_settings
                SET {set_clauses}, updated_at = datetime('now','localtime')
                WHERE user_id = ?""",
            [*vals, user_id],
        )


# ── 진입점: 직접 실행 시 DB 초기화 ───────────────────────────────────────
if __name__ == "__main__":
    init_db()
    print(f"DB 초기화 완료: {DB_PATH}")

    # 테스트 계정 생성
    try:
        uid = create_user("테스트유저", "test@example.com", "test1234")
        print(f"테스트 계정 생성: user_id={uid}")
    except ValueError as e:
        print(f"(이미 존재: {e})")

    # 스키마 확인
    with get_conn() as conn:
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
        for t in tables:
            print(f"\n[{t['name']}]")
            cols = conn.execute(f"PRAGMA table_info({t['name']})").fetchall()
            for c in cols:
                print(f"  {c['name']:20s} {c['type']}")
