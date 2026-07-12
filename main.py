# -*- coding: utf-8 -*-
from fastapi import FastAPI, HTTPException, Depends
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, EmailStr
import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime, timedelta, timezone
import os
import warnings
warnings.filterwarnings("ignore")

try:
    import jwt as pyjwt
    _JWT_AVAILABLE = True
except ImportError:
    _JWT_AVAILABLE = False

import database as db

try:
    import yfinance as yf
    _YF_AVAILABLE = True
except ImportError:
    _YF_AVAILABLE = False

try:
    from sklearn.linear_model import LinearRegression
    _SK_AVAILABLE = True
except ImportError:
    _SK_AVAILABLE = False

app = FastAPI(title="이란전쟁 유가 분석")

# ── JWT 설정 ──
_SECRET = os.environ.get("SECRET_KEY", "iran-oil-dev-secret-change-in-prod")
_ALGO   = "HS256"
_TOKEN_HOURS = 24 * 7   # 7일

_bearer = HTTPBearer(auto_error=False)


def _make_token(user_id: int) -> str:
    payload = {
        "sub": str(user_id),
        "exp": datetime.now(timezone.utc) + timedelta(hours=_TOKEN_HOURS),
    }
    return pyjwt.encode(payload, _SECRET, algorithm=_ALGO)


def _parse_token(token: str) -> int:
    """토큰 검증 후 user_id 반환. 유효하지 않으면 HTTPException 401."""
    try:
        payload = pyjwt.decode(token, _SECRET, algorithms=[_ALGO])
        return int(payload["sub"])
    except pyjwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="토큰이 만료되었습니다.")
    except Exception:
        raise HTTPException(status_code=401, detail="유효하지 않은 토큰입니다.")


def get_current_user(creds: HTTPAuthorizationCredentials = Depends(_bearer)) -> dict:
    """Authorization: Bearer <token> 헤더 필수 의존성."""
    if not creds:
        raise HTTPException(status_code=401, detail="로그인이 필요합니다.")
    user_id = _parse_token(creds.credentials)
    row = db.get_user_by_id(user_id)
    if not row:
        raise HTTPException(status_code=401, detail="존재하지 않는 사용자입니다.")
    return dict(row)


def get_optional_user(creds: HTTPAuthorizationCredentials = Depends(_bearer)) -> dict | None:
    """토큰이 없거나 유효하지 않으면 None 반환 (선택적 인증)."""
    if not creds:
        return None
    try:
        user_id = _parse_token(creds.credentials)
        row = db.get_user_by_id(user_id)
        return dict(row) if row else None
    except HTTPException:
        return None


# DB 초기화 (테이블 없으면 생성)
db.init_db()

BASE_DIR = Path(__file__).parent
STATIC_DIR = BASE_DIR / "static"

# ── 현재 기준가격 (탭3, 탭4 계산용) ──
BASE_PRICES = {
    "라면":     {"price": 950,   "unit": "원/봉",     "elasticity": 0.15},
    "달걀":     {"price": 6500,  "unit": "원/30구",   "elasticity": 0.08},
    "우유":     {"price": 2200,  "unit": "원/L",      "elasticity": 0.08},
    "식용유":   {"price": 4500,  "unit": "원/900ml",  "elasticity": 0.30},
    "생수":     {"price": 1200,  "unit": "원/2L",     "elasticity": 0.12},
    "샴푸":     {"price": 8000,  "unit": "원/개",     "elasticity": 0.25},
    "택배비":   {"price": 2500,  "unit": "원/건",     "elasticity": 0.35},
    "휘발유":   {"price": 2011,  "unit": "원/L",      "elasticity": 0.70},
    "전기요금": {"price": 45000, "unit": "원/월",     "elasticity": 0.15},
    "가스요금": {"price": 55000, "unit": "원/월",     "elasticity": 0.20},
}

# 시나리오별 유가 상승률
SCENARIOS = {
    "local":   {"name": "⚡ 국지전",       "oil_rise": 0.25},
    "hormuz":  {"name": "🚢 호르무즈 봉쇄", "oil_rise": 0.60},
    "fullwar": {"name": "💥 전면전",       "oil_rise": 1.10},
}

# BASE_PRICES 키 → 생활물가지수 품목명 매핑 (회귀분석용)
ITEM_INDEX_MAP = {
    "휘발유":   "휘발유",
    "택배비":   "택배이용료",
    "라면":     "라면",
    "달걀":     "달걀",
    "우유":     "우유",
    "식용유":   "식용유",
    "생수":     "생수",
    "샴푸":     "샴푸",
    "가스요금": "도시가스",
    "전기요금": "전기료",
}

# 생활물가지수 대상 품목과 행 인덱스
ITEM_ROW_MAP = {
    "라면":     6,
    "두부":     7,
    "우유":     20,
    "달걀":     22,
    "식용유":   24,
    "생수":     63,
    "전기료":   102,
    "도시가스": 103,
    "휘발유":   119,
    "택배이용료": 125,
    "샴푸":     144,
    "화장지":   145,
}

# ── 데이터 캐시 ──
_cache: dict = {}


def _parse_month_col(v) -> str:
    """Excel float 컬럼헤더 → 'YYYY-MM' 문자열"""
    year = int(v)
    month = round((float(v) - year) * 100)
    return f"{year}-{month:02d}"


def fetch_realtime_brent() -> dict | None:
    """yfinance로 브렌트유 실시간 가격 수집 (BZ=F 선물)"""
    if not _YF_AVAILABLE:
        return None
    try:
        ticker = yf.Ticker("BZ=F")
        hist = ticker.history(period="5d")
        if not hist.empty:
            price = float(hist["Close"].iloc[-1])
            date  = str(hist.index[-1].date())
            prev  = float(hist["Close"].iloc[-2]) if len(hist) >= 2 else price
            chg   = round((price - prev) / prev * 100, 2)
            return {
                "price":  round(price, 2),
                "date":   date,
                "change": chg,
                "source": "Yahoo Finance / BZ=F",
            }
    except Exception:
        pass
    return None


def compute_elasticities(oil_data: dict, price_data: dict) -> dict:
    """브렌트유 월별 등락률 vs 소비자물가 월별 등락률 선형회귀 → 탄성계수 산출"""
    if not _SK_AVAILABLE:
        return {}

    oil_months = oil_data["months"]
    oil_prices = np.array(oil_data["prices"], dtype=float)
    price_months = price_data["months"]

    # 겹치는 월만 사용
    month_set = set(price_months)
    common = [m for m in oil_months if m in month_set]

    results = {}

    for bp_name, idx_name in ITEM_INDEX_MAP.items():
        item_vals = price_data["items"].get(idx_name, [])
        if not item_vals:
            continue

        oil_seq, item_seq = [], []
        for m in common:
            oi = oil_months.index(m)
            pi = price_months.index(m)
            o = oil_prices[oi] if oi < len(oil_prices) else np.nan
            p = item_vals[pi] if pi < len(item_vals) else np.nan
            if np.isfinite(o) and o > 0 and p is not None and np.isfinite(p) and p > 0:
                oil_seq.append(o)
                item_seq.append(p)

        if len(oil_seq) < 8:
            continue

        o_arr = np.array(oil_seq, dtype=float)
        p_arr = np.array(item_seq, dtype=float)

        # 월별 % 변화율
        o_pct = np.diff(o_arr) / o_arr[:-1]
        p_pct = np.diff(p_arr) / p_arr[:-1]

        mask = np.isfinite(o_pct) & np.isfinite(p_pct)
        n = int(mask.sum())
        if n < 6:
            continue

        x = o_pct[mask].reshape(-1, 1)
        y = p_pct[mask]

        model = LinearRegression(fit_intercept=True)
        model.fit(x, y)

        raw_coef = float(model.coef_[0])
        r2       = float(model.score(x, y))
        original = BASE_PRICES[bp_name]["elasticity"]

        # R² 낮으면 원래 추정치 유지
        if r2 < 0.05:
            final = original
            used  = False
        else:
            final = float(np.clip(raw_coef, 0.01, 1.5))
            used  = True

        results[bp_name] = {
            "elasticity":      round(final, 4),
            "r_squared":       round(r2, 4),
            "n_samples":       n,
            "used_regression": used,
            "original":        original,
            "raw_coef":        round(raw_coef, 4),
        }

    return results


def _get_elasticity(name: str) -> float:
    """캐시된 회귀 탄성계수 반환 (없으면 BASE_PRICES 추정치)"""
    computed = _cache.get("elasticities", {}).get(name)
    if computed:
        return computed["elasticity"]
    return BASE_PRICES[name]["elasticity"]


def _load_data():
    global _cache
    if _cache:
        return

    # 브렌트유 CSV
    df = pd.read_csv(BASE_DIR / "chart_20260607T031456.csv")
    df["Date"] = pd.to_datetime(df["Date"], format="%m/%d/%Y")
    df = df[df["Date"] >= "2022-01-01"].copy()
    df["month"] = df["Date"].dt.to_period("M").astype(str)
    df_monthly = df.groupby("month")["Value"].last().reset_index()
    _cache["oil"] = {
        "months": df_monthly["month"].tolist(),
        "prices": df_monthly["Value"].tolist(),
    }

    # 생활물가지수 Excel
    xl = pd.read_excel(
        BASE_DIR / "생활물가지수_2020100__20260607122851.xlsx", header=None
    )
    month_cols = list(range(2, 55))  # col 2~54 = 2022.01~2026.05
    months = [_parse_month_col(xl.iloc[0, c]) for c in month_cols]

    price_items = {}
    for item, row_idx in ITEM_ROW_MAP.items():
        vals = [
            float(xl.iloc[row_idx, c]) if pd.notna(xl.iloc[row_idx, c]) else None
            for c in month_cols
        ]
        price_items[item] = vals

    # 연도별 평균 (col 55~59 = 2021~2025)
    annual_cols = {
        "2021": 55, "2022": 56, "2023": 57, "2024": 58, "2025": 59
    }
    annual = {}
    for item, row_idx in ITEM_ROW_MAP.items():
        annual[item] = {
            yr: float(xl.iloc[row_idx, ci])
            if pd.notna(xl.iloc[row_idx, ci]) else None
            for yr, ci in annual_cols.items()
        }

    _cache["prices"] = {"months": months, "items": price_items, "annual": annual}

    # 소비자물가지수 Excel
    xl2 = pd.read_excel(
        BASE_DIR / "소비자물가지수_2020100__20260607123034.xlsx", header=None
    )
    cpi_months = [_parse_month_col(xl2.iloc[0, c]) for c in range(1, xl2.shape[1])]
    cpi_vals = [
        float(xl2.iloc[1, c]) if pd.notna(xl2.iloc[1, c]) else None
        for c in range(1, xl2.shape[1])
    ]
    _cache["cpi"] = {"months": cpi_months, "values": cpi_vals}

    # ── 회귀분석으로 탄성계수 계산 ──
    _cache["elasticities"] = compute_elasticities(_cache["oil"], _cache["prices"])

    # ── yfinance 실시간 가격 ──
    _cache["realtime"] = fetch_realtime_brent()


@app.on_event("startup")
def startup():
    _load_data()


# ══════════════════════════════════════════
# 인증 API
# ══════════════════════════════════════════

class RegisterRequest(BaseModel):
    name: str
    email: str
    password: str


class LoginRequest(BaseModel):
    email: str
    password: str


class CalcRequest(BaseModel):
    budgets: dict   # {품목명: 월_예산_원}
    scenario: str = "local"


class SettingsUpdateRequest(BaseModel):
    budgets: dict   # {"라면": 5000, ...}


@app.post("/api/auth/register", status_code=201)
def register(body: RegisterRequest):
    """회원가입. 이메일 중복 시 409 반환."""
    name = body.name.strip()
    email = body.email.strip().lower()
    password = body.password

    if not name or len(name) > 50:
        raise HTTPException(status_code=422, detail="이름은 1~50자여야 합니다.")
    if not email or "@" not in email:
        raise HTTPException(status_code=422, detail="유효한 이메일을 입력하세요.")
    if len(password) < 6:
        raise HTTPException(status_code=422, detail="비밀번호는 6자 이상이어야 합니다.")

    try:
        user_id = db.create_user(name, email, password)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))

    return {
        "user_id": user_id,
        "name": name,
        "email": email,
        "token": _make_token(user_id),
    }


@app.post("/api/auth/login")
def login(body: LoginRequest):
    """로그인. 이메일/비밀번호 불일치 시 401 반환."""
    email = body.email.strip().lower()
    row = db.get_user_by_email(email)
    if not row or not db.verify_password(body.password, row["password"]):
        raise HTTPException(status_code=401, detail="이메일 또는 비밀번호가 올바르지 않습니다.")

    return {
        "user_id": row["id"],
        "name": row["name"],
        "email": row["email"],
        "token": _make_token(row["id"]),
    }


@app.get("/api/auth/me")
def me(user: dict = Depends(get_current_user)):
    """현재 로그인 유저 정보 + 기본 설정값 반환."""
    settings = db.get_settings(user["id"])
    return {
        "user_id": user["id"],
        "name": user["name"],
        "email": user["email"],
        "created_at": user["created_at"],
        "settings": dict(settings) if settings else {},
    }


@app.post("/api/auth/logout")
def logout():
    """로그아웃 (클라이언트에서 토큰 삭제). 서버는 stateless."""
    return {"ok": True}


# ── 이력 API (로그인 필요) ──

@app.get("/api/history")
def get_history(user: dict = Depends(get_current_user)):
    """최근 계산 이력 20건 조회."""
    rows = db.get_history(user["id"], limit=20)
    return {"items": [dict(r) for r in rows]}


@app.post("/api/history", status_code=201)
def save_history(body: CalcRequest, user: dict = Depends(get_current_user)):
    """계산 결과를 이력에 저장. /api/calculate 와 같은 body 사용."""
    scenario_type = body.scenario if body.scenario in SCENARIOS else "local"
    oil_rise = SCENARIOS[scenario_type]["oil_rise"]

    total_now = 0
    total_pred = 0
    for name, info in BASE_PRICES.items():
        budget = float(body.budgets.get(name, 0))
        if budget <= 0:
            continue
        elasticity = _get_elasticity(name)
        total_now  += budget
        total_pred += round(budget * (1 + oil_rise * elasticity))

    record_id = db.save_history(
        user_id=user["id"],
        scenario=scenario_type,
        total_now=round(total_now),
        total_pred=round(total_pred),
        monthly_extra=round(total_pred - total_now),
        budgets={k: int(v) for k, v in body.budgets.items()},
    )
    return {"id": record_id, "monthly_extra": round(total_pred - total_now)}


@app.delete("/api/history/{record_id}")
def delete_history(record_id: int, user: dict = Depends(get_current_user)):
    """본인 이력 삭제."""
    deleted = db.delete_history(record_id, user["id"])
    if not deleted:
        raise HTTPException(status_code=404, detail="이력을 찾을 수 없습니다.")
    return {"ok": True}


# ── 설정 API (로그인 필요) ──

@app.get("/api/settings")
def get_settings(user: dict = Depends(get_current_user)):
    """내 기본 예산 설정 조회."""
    row = db.get_settings(user["id"])
    return dict(row) if row else {}


@app.put("/api/settings")
def update_settings(body: SettingsUpdateRequest, user: dict = Depends(get_current_user)):
    """내 기본 예산 설정 갱신."""
    db.update_settings(user["id"], body.budgets)
    return {"ok": True}


# ── API ──

@app.get("/api/oil")
def get_oil():
    _load_data()
    data = _cache["oil"]
    current = data["prices"][-1]
    war_start_idx = next(
        (i for i, m in enumerate(data["months"]) if m >= "2026-02"), None
    )
    pre_war = data["prices"][war_start_idx - 1] if war_start_idx else current
    rise_pct = round((current - pre_war) / pre_war * 100, 1) if pre_war else 0

    russia_start_idx = next(
        (i for i, m in enumerate(data["months"]) if m >= "2022-02"), 0
    )
    russia_peak = max(data["prices"][russia_start_idx: russia_start_idx + 6])

    # 실시간 가격이 있으면 KPI에 반영
    rt = _cache.get("realtime")
    display_price = rt["price"] if rt else current

    return {
        "months": data["months"],
        "prices": data["prices"],
        "kpi": {
            "current_brent":      display_price,
            "iran_war_rise_pct":  rise_pct,
            "gasoline_price":     2011,
            "russia_peak":        russia_peak,
        },
        "realtime": rt,
        "war_zones": {
            "russia": {"start": "2022-02", "end": "2022-06"},
            "iran":   {"start": "2026-02", "end": data["months"][-1]},
        },
    }


@app.get("/api/prices")
def get_prices():
    _load_data()
    data = _cache["prices"]
    items = data["items"]
    months = data["months"]

    # KPI: 2022-01 대비 현재 변화율
    kpi = {}
    for item in ["라면", "달걀", "우유", "식용유", "두부"]:
        vals = items.get(item, [])
        if vals and vals[0] and vals[-1]:
            kpi[item] = round((vals[-1] - vals[0]) / vals[0] * 100, 1)
        else:
            kpi[item] = 0

    return {
        "months": months,
        "items": items,
        "annual": data["annual"],
        "kpi": kpi,
    }


@app.get("/api/cpi")
def get_cpi():
    _load_data()
    return _cache["cpi"]


@app.get("/api/scenario/{scenario_type}")
def get_scenario(scenario_type: str):
    if scenario_type not in SCENARIOS:
        raise HTTPException(status_code=404, detail=f"Unknown scenario: {scenario_type}")

    sc = SCENARIOS[scenario_type]
    oil_rise = sc["oil_rise"]

    items = []
    for name, info in BASE_PRICES.items():
        price_now  = info["price"]
        elasticity = _get_elasticity(name)          # 회귀 탄성계수 우선
        price_pred = round(price_now * (1 + oil_rise * elasticity))
        diff = price_pred - price_now
        items.append({
            "name":       name,
            "unit":       info["unit"],
            "price_now":  price_now,
            "price_pred": price_pred,
            "diff":       diff,
            "diff_pct":   round(diff / price_now * 100, 1),
            "elasticity": round(elasticity, 4),
        })

    # 한달 추가 생활비 (기본 소비량 가정)
    default_qty = {
        "휘발유": 40,    # L/월
        "택배비": 4,     # 건/월
        "라면": 8,       # 봉/월
        "달걀": 1,       # 30구/월
        "우유": 4,       # L/월
        "식용유": 0.3,   # 병/월
        "생수": 4,       # 병/월
        "샴푸": 0.3,     # 개/월
        "가스요금": 1,   # 월/월
        "전기요금": 1,   # 월/월
    }
    total_now = sum(BASE_PRICES[n]["price"] * qty for n, qty in default_qty.items())
    total_pred = sum(
        next(it["price_pred"] for it in items if it["name"] == n) * qty
        for n, qty in default_qty.items()
    )

    return {
        "scenario": sc["name"],
        "oil_rise_pct": round(oil_rise * 100),
        "items": items,
        "summary": {
            "total_now": total_now,
            "total_pred": total_pred,
            "monthly_extra": total_pred - total_now,
            "yearly_extra": (total_pred - total_now) * 12,
        },
    }


@app.post("/api/calculate")
def calculate(body: CalcRequest):
    scenario_type = body.scenario if body.scenario in SCENARIOS else "local"
    oil_rise = SCENARIOS[scenario_type]["oil_rise"]

    results = []
    total_now = 0
    total_pred = 0

    for name, info in BASE_PRICES.items():
        budget = float(body.budgets.get(name, 0))
        if budget <= 0:
            continue
        elasticity = _get_elasticity(name)          # 회귀 탄성계수 우선
        rise_rate = oil_rise * elasticity
        budget_pred = round(budget * (1 + rise_rate))
        extra = budget_pred - budget
        total_now += budget
        total_pred += budget_pred
        results.append({
            "name": name,
            "unit": info["unit"],
            "budget_now": round(budget),
            "budget_pred": budget_pred,
            "extra": extra,
            "rise_pct": round(rise_rate * 100, 1),
        })

    monthly_extra = total_pred - total_now
    return {
        "items": results,
        "total_now": round(total_now),
        "total_pred": round(total_pred),
        "monthly_extra": round(monthly_extra),
        "yearly_extra": round(monthly_extra * 12),
    }


@app.get("/api/realtime")
def get_realtime():
    """yfinance 실시간 브렌트유 가격 (앱 시작 후 캐시, 필요 시 재수집)"""
    _load_data()
    rt = _cache.get("realtime")
    if not rt:
        # 캐시 미스 시 재시도
        rt = fetch_realtime_brent()
        _cache["realtime"] = rt
    return rt or {"error": "실시간 데이터를 가져올 수 없습니다 (yfinance 오류)"}


@app.get("/api/analysis")
def get_analysis():
    """scikit-learn 회귀분석 결과 반환 (탄성계수·R²·샘플 수)"""
    _load_data()
    elasticities = _cache.get("elasticities", {})
    rows = []
    for bp_name, info in BASE_PRICES.items():
        reg = elasticities.get(bp_name)
        rows.append({
            "name":            bp_name,
            "elasticity_used": reg["elasticity"]      if reg else info["elasticity"],
            "r_squared":       reg["r_squared"]        if reg else None,
            "n_samples":       reg["n_samples"]        if reg else None,
            "used_regression": reg["used_regression"]  if reg else False,
            "original":        info["elasticity"],
            "raw_coef":        reg["raw_coef"]         if reg else None,
        })
    return {
        "method": "월별 % 변화율 OLS 회귀 (브렌트유 → 소비자물가지수)",
        "r2_threshold": 0.05,
        "sklearn_available": _SK_AVAILABLE,
        "items": rows,
    }


# 정적 파일 서빙: /static 경로에 마운트하고 "/" 는 FileResponse로 직접 제공
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/")
async def serve_index():
    return FileResponse(
        str(STATIC_DIR / "index.html"),
        headers={"Cache-Control": "no-cache, no-store, must-revalidate", "Pragma": "no-cache"},
    )
