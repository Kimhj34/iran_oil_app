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

# ── KOSIS Open API 설정 ──────────────────────────────────────────────────────
_KOSIS_KEY        = os.environ.get("KOSIS_API_KEY", "")
_KOSIS_PRICES_ORG = os.environ.get("KOSIS_PRICES_ORG", "101")
_KOSIS_PRICES_TBL = os.environ.get("KOSIS_PRICES_TBL", "DT_1J22003")  # 생활물가지수(2020=100)
_KOSIS_CPI_ORG    = os.environ.get("KOSIS_CPI_ORG",    "101")
_KOSIS_CPI_TBL    = os.environ.get("KOSIS_CPI_TBL",    "DT_1J22001")  # 소비자물가지수(2020=100)

# KOSIS 응답 품목명 → 내부 품목명 매핑
# 통계청은 '계란' 표기 사용, '달걀'과 동일
_KOSIS_NAME_MAP = {
    "라면": "라면", "두부": "두부", "우유": "우유",
    "달걀": "달걀", "계란": "달걀",        # 통계청은 '계란' 표기
    "식용유": "식용유",
    "생수": "생수",
    "전기료": "전기료", "전기요금": "전기료",
    "도시가스": "도시가스", "가스요금": "도시가스",
    "휘발유": "휘발유",
    "택배이용료": "택배이용료", "택배": "택배이용료",
    "샴푸": "샴푸", "화장지": "화장지",
}
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


# 이란 전쟁 시나리오 앱 기준 브렌트유 월별 기준 데이터 (2022-01 ~ 2026-06)
# CSV 없을 때와 yfinance 실패 시 폴백으로 사용
_OIL_FALLBACK = {
    "2022-01": 83.0,  "2022-02": 95.0,  "2022-03": 117.0, "2022-04": 104.0,
    "2022-05": 111.0, "2022-06": 113.0, "2022-07": 101.0, "2022-08": 95.0,
    "2022-09": 90.0,  "2022-10": 92.0,  "2022-11": 88.0,  "2022-12": 80.0,
    "2023-01": 83.0,  "2023-02": 83.0,  "2023-03": 77.0,  "2023-04": 82.0,
    "2023-05": 72.0,  "2023-06": 74.0,  "2023-07": 80.0,  "2023-08": 84.0,
    "2023-09": 92.0,  "2023-10": 87.0,  "2023-11": 82.0,  "2023-12": 77.0,
    "2024-01": 79.0,  "2024-02": 82.0,  "2024-03": 86.0,  "2024-04": 89.0,
    "2024-05": 83.0,  "2024-06": 83.0,  "2024-07": 84.0,  "2024-08": 79.0,
    "2024-09": 74.0,  "2024-10": 74.0,  "2024-11": 73.0,  "2024-12": 73.0,
    "2025-01": 79.0,  "2025-02": 75.0,  "2025-03": 72.0,  "2025-04": 66.0,
    "2025-05": 64.0,  "2025-06": 68.0,  "2025-07": 75.0,  "2025-08": 76.0,
    "2025-09": 72.0,  "2025-10": 70.0,  "2025-11": 72.0,  "2025-12": 74.0,
    "2026-01": 74.0,  "2026-02": 80.0,  "2026-03": 89.0,  "2026-04": 95.0,
    "2026-05": 102.0, "2026-06": 108.0,
}


def _load_oil_data() -> dict:
    """브렌트유 월별 데이터를 로드한다. CSV → yfinance → 하드코딩 순으로 폴백."""
    csv_path = BASE_DIR / "chart_20260607T031456.csv"

    # 1) CSV 파일이 있으면 그대로 사용
    if csv_path.exists():
        try:
            df = pd.read_csv(csv_path)
            df["Date"] = pd.to_datetime(df["Date"], format="%m/%d/%Y")
            df = df[df["Date"] >= "2022-01-01"].copy()
            df["month"] = df["Date"].dt.to_period("M").astype(str)
            df_monthly = df.groupby("month")["Value"].last().reset_index()
            if not df_monthly.empty:
                return {
                    "months": df_monthly["month"].tolist(),
                    "prices": df_monthly["Value"].tolist(),
                }
        except Exception:
            pass

    # 2) yfinance로 2022-01-01 이후 월별 데이터 다운로드
    if _YF_AVAILABLE:
        try:
            ticker = yf.Ticker("BZ=F")
            hist = ticker.history(start="2022-01-01", interval="1mo")
            if not hist.empty:
                hist.index = hist.index.tz_localize(None) if hist.index.tz else hist.index
                months = hist.index.to_period("M").astype(str).tolist()
                prices = [round(float(v), 2) for v in hist["Close"].tolist()]
                # 하드코딩 데이터로 누락 월 보완 (특히 이란 전쟁 이후 구간)
                month_map = dict(zip(months, prices))
                for m, p in _OIL_FALLBACK.items():
                    if m not in month_map:
                        month_map[m] = p
                sorted_months = sorted(month_map.keys())
                return {
                    "months": sorted_months,
                    "prices": [month_map[m] for m in sorted_months],
                }
        except Exception:
            pass

    # 3) 완전 폴백: 하드코딩 데이터 사용
    sorted_months = sorted(_OIL_FALLBACK.keys())
    return {
        "months": sorted_months,
        "prices": [_OIL_FALLBACK[m] for m in sorted_months],
    }


# ── 생활물가지수 하드코딩 폴백 (2020=100, 2022-01~2026-05, 53개월) ──
def _lp(anchors: list) -> list:
    """(month_idx, value) 앵커 → 53개월 선형보간 리스트"""
    out = [0.0] * 53
    for i in range(len(anchors) - 1):
        i0, v0 = anchors[i];  i1, v1 = anchors[i + 1]
        for j in range(i0, i1 + 1):
            t = (j - i0) / (i1 - i0) if i1 != i0 else 0
            out[j] = round(v0 + t * (v1 - v0), 1)
    for j in range(anchors[-1][0] + 1, 53):
        out[j] = anchors[-1][1]
    return out

# 2022-01=0, 2022-06=5, 2022-12=11, 2023-06=17, 2023-12=23,
# 2024-06=29, 2024-12=35, 2025-06=41, 2025-12=47, 2026-02=49, 2026-05=52
_PRICES_MONTHS_FB = [
    f"{y}-{m:02d}"
    for y in range(2022, 2027)
    for m in range(1, 13)
    if (y, m) <= (2026, 5)
]  # 53개월
_PRICES_ITEMS_FB = {
    "라면":      _lp([(0,105),(5,113),(11,121),(23,128),(35,131),(47,133),(52,138)]),
    "두부":      _lp([(0,103),(11,112),(23,117),(35,120),(47,122),(52,126)]),
    "우유":      _lp([(0,105),(11,116),(23,120),(35,123),(47,125),(52,129)]),
    "달걀":      _lp([(0,108),(5,118),(11,120),(23,124),(35,127),(47,129),(52,133)]),
    "식용유":    _lp([(0,113),(5,152),(11,145),(17,135),(23,128),(35,125),(47,125),(52,131)]),
    "생수":      _lp([(0,103),(11,108),(23,112),(35,115),(47,117),(52,121)]),
    "전기료":    _lp([(0,100),(11,112),(17,122),(23,124),(35,128),(47,130),(52,137)]),
    "도시가스":  _lp([(0,103),(5,122),(11,130),(17,133),(23,132),(35,130),(47,131),(52,139)]),
    "휘발유":    _lp([(0,110),(5,148),(11,130),(23,118),(35,118),(47,118),(49,119),(52,141)]),
    "택배이용료":_lp([(0,108),(11,116),(23,121),(35,126),(47,130),(52,135)]),
    "샴푸":      _lp([(0,103),(11,110),(23,116),(35,120),(47,122),(52,126)]),
    "화장지":    _lp([(0,103),(11,112),(23,115),(35,118),(47,120),(52,123)]),
}
_PRICES_ANNUAL_FB = {
    "라면":      {"2021":102,"2022":113,"2023":127,"2024":130,"2025":133},
    "두부":      {"2021":101,"2022":108,"2023":116,"2024":120,"2025":122},
    "우유":      {"2021":103,"2022":111,"2023":119,"2024":122,"2025":125},
    "달걀":      {"2021":105,"2022":115,"2023":122,"2024":126,"2025":129},
    "식용유":    {"2021":108,"2022":139,"2023":131,"2024":126,"2025":125},
    "생수":      {"2021":101,"2022":106,"2023":111,"2024":115,"2025":117},
    "전기료":    {"2021": 99,"2022":107,"2023":123,"2024":127,"2025":130},
    "도시가스":  {"2021":101,"2022":118,"2023":133,"2024":130,"2025":131},
    "휘발유":    {"2021":104,"2022":134,"2023":120,"2024":119,"2025":118},
    "택배이용료":{"2021":106,"2022":112,"2023":120,"2024":125,"2025":130},
    "샴푸":      {"2021":101,"2022":107,"2023":115,"2024":120,"2025":122},
    "화장지":    {"2021":101,"2022":108,"2023":114,"2024":117,"2025":120},
}

# ── 소비자물가지수 하드코딩 폴백 (2020=100) ──
_CPI_MONTHS_FB = _PRICES_MONTHS_FB
_CPI_VALUES_FB = _lp([(0,104),(5,107),(11,110),(23,113),(35,116),(47,118),(52,123)])


# ── KOSIS API 헬퍼 ──────────────────────────────────────────────────────────

def _kosis_raw(endpoint: str, params: dict) -> list | None:
    """KOSIS API 호출 공통 유틸. 성공 시 list, 실패/오류 시 None."""
    import urllib.request, urllib.parse, json as _json
    try:
        url = f"{endpoint}?{urllib.parse.urlencode(params)}"
        req = urllib.request.Request(url, headers={"User-Agent": "iran-oil-app/1.0"})
        with urllib.request.urlopen(req, timeout=20) as r:
            data = _json.loads(r.read().decode("utf-8"))
        if isinstance(data, dict):
            return None
        if isinstance(data, list) and data and "err" in data[0]:
            return None
        return data if isinstance(data, list) and data else None
    except Exception:
        return None


def _kosis_get_meta(org_id: str, tbl_id: str) -> dict:
    """KOSIS 통계메타 조회 → 유효한 itmId·objL1 코드 반환."""
    import urllib.request, urllib.parse, json as _json
    result: dict = {"itmIds": [], "objL1s": []}
    base = {"apiKey": _KOSIS_KEY, "orgId": org_id, "tblId": tbl_id,
            "format": "json", "jsonVD": "Y"}
    # 방법1: statisticsMeta.do (항목 목록)
    for meta_url, method_param in [
        ("https://kosis.kr/openapi/statisticsMeta.do", "getList"),
        ("https://kosis.kr/openapi/statisticsList.do",  "getStatsMeta"),
    ]:
        params = {**base, "method": method_param}
        rows = _kosis_raw(meta_url, params)
        if rows:
            result["raw_meta"] = rows[:5]
            result["itmIds"]   = list({r.get("ITM_ID","") for r in rows if r.get("ITM_ID")})[:10]
            result["objL1s"]   = list({r.get("OBJ_ID","") for r in rows if r.get("OBJ_ID")})[:10]
            break
    return result


def _kosis_get(org_id: str, tbl_id: str, start: str = "202101") -> tuple[list | None, str]:
    """KOSIS Open API 단순 조회. (row 리스트 또는 None, 상태 메시지) 반환."""
    import urllib.parse

    end = datetime.now().strftime("%Y%m")
    base = {"method": "getList", "apiKey": _KOSIS_KEY, "objL1": "ALL",
            "format": "json", "jsonVD": "Y", "prdSe": "M",
            "startPrdDe": start, "endPrdDe": end, "orgId": org_id, "tblId": tbl_id}

    last_err = f"{tbl_id} 모든 시도 실패"

    # 1) Param API — itmId 후보 순서대로 시도
    param_ep = "https://kosis.kr/openapi/Param/statisticsParameterData.do"
    for itm_id in ("T10", "T", "ALL", "T20", "T30"):
        rows = _kosis_raw(param_ep, {**base, "itmId": itm_id})
        if rows is not None:
            return rows, f"OK Param/{tbl_id} itmId={itm_id} ({len(rows)}행)"
        last_err = f"Param API 오류(itmId={itm_id}) for {tbl_id}"

    # 2) Share API 엔드포인트 (statisticsData.do) — Param API 실패 시 대안
    share_ep = "https://kosis.kr/openapi/statisticsData.do"
    for itm_id in ("T10", "T", "ALL"):
        rows = _kosis_raw(share_ep, {**base, "itmId": itm_id})
        if rows is not None:
            return rows, f"OK Share/{tbl_id} itmId={itm_id} ({len(rows)}행)"
        last_err = f"Share API 오류(itmId={itm_id}) for {tbl_id}"

    # 3) 메타데이터 조회로 실제 itmId 확인 후 재시도
    meta = _kosis_get_meta(org_id, tbl_id)
    _cache[f"kosis_meta_{tbl_id}"] = meta
    for itm_id in meta.get("itmIds", []):
        for ep in (param_ep, share_ep):
            rows = _kosis_raw(ep, {**base, "itmId": itm_id})
            if rows is not None:
                return rows, f"OK meta/{tbl_id} itmId={itm_id} ({len(rows)}행)"
        last_err = f"meta 시도 실패(itmId={itm_id}) for {tbl_id}"

    return None, last_err


def _kosis_item_name(row: dict) -> str:
    """KOSIS 응답 row에서 품목명 추출 (테이블마다 필드명이 다름)."""
    return (row.get("C1_NM") or row.get("objNm1") or
            row.get("ITM_NM") or row.get("itmNm") or "")


def _kosis_browse(parent_id: str, vw_cd: str = "MT_ZTITLE") -> list[dict]:
    """KOSIS 통계목록 API에서 특정 parentListId의 자식 노드 조회."""
    import urllib.request, urllib.parse, json as _json

    params: dict = {"method": "getList", "apiKey": _KOSIS_KEY,
                    "vwCd": vw_cd, "format": "json", "jsonVD": "Y"}
    if parent_id:
        params["parentListId"] = parent_id
    try:
        url = f"https://kosis.kr/openapi/statisticsList.do?{urllib.parse.urlencode(params)}"
        req = urllib.request.Request(url, headers={"User-Agent": "iran-oil-app/1.0"})
        with urllib.request.urlopen(req, timeout=10) as r:
            data = _json.loads(r.read().decode("utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _kosis_list_price_tables() -> list[str]:
    """KOSIS 통계목록 트리를 탐색해 생활물가/소비자물가 품목별 테이블 ID 목록 반환."""
    found_tbls: list[str] = []
    found_nodes: list[str] = []

    # 1단계: 최상위 카테고리 조회 (parentListId 없음)
    roots = _kosis_browse("")
    if not roots:
        roots = _kosis_browse("0")

    # 물가 관련 최상위 노드 찾기
    price_roots: list[dict] = []
    for node in roots:
        nm  = node.get("TBL_NM", "") or node.get("LIST_NM", "") or node.get("NM", "")
        lid = node.get("LIST_ID", "") or node.get("TBL_ID", "")
        if any(kw in nm for kw in ("물가", "가격")):
            price_roots.append(node)
            found_nodes.append(f"{lid}:{nm}")

    # 2단계: 물가 노드 아래 탐색 (최대 2레벨)
    for root in price_roots:
        lid = root.get("LIST_ID", "") or root.get("TBL_ID", "")
        if not lid:
            continue
        children = _kosis_browse(lid)
        for child in children:
            cnm  = child.get("TBL_NM", "") or child.get("LIST_NM", "") or child.get("NM", "")
            ctid = child.get("TBL_ID", "")
            clid = child.get("LIST_ID", "")
            found_nodes.append(f"{ctid or clid}:{cnm}")
            if ctid and any(kw in cnm for kw in ("생활물가", "품목")):
                found_tbls.append(ctid)
            # 3레벨 탐색
            if clid and not ctid:
                grandchildren = _kosis_browse(clid)
                for gc in grandchildren:
                    gnm  = gc.get("TBL_NM", "") or gc.get("LIST_NM", "")
                    gtid = gc.get("TBL_ID", "")
                    if gtid:
                        found_nodes.append(f"{gtid}:{gnm}")
                        if any(kw in gnm for kw in ("생활물가", "품목")):
                            found_tbls.append(gtid)

    _cache["kosis_browse_nodes"] = found_nodes[:30]
    return found_tbls


def _load_prices_from_kosis() -> dict | None:
    """KOSIS API로 생활물가지수/소비자물가지수 품목별 월별 데이터 수집.
    C1_NM에 품목명(라면·달걀 등)이 있는 테이블을 찾는다."""
    if not _KOSIS_KEY:
        return None

    # 1순위: 환경변수로 직접 지정한 테이블
    # 2순위: 통계목록 API로 탐색한 테이블들
    # 3순위: DT_1J22003 인근 번호 일괄 시도 (DT_1J22003 = 시도별이므로 제외)
    # 통계목록 탐색으로 확인된 정확한 테이블 ID 목록 (2026-07 기준)
    # DT_1J22005 = 생활물가지수(2020=100)  ← 첫 번째 시도
    # DT_1J22112 = 품목별 소비자물가지수(품목성질별: 2020=100)
    # DT_1J22001 = 지출목적별 소비자물가지수(품목포함, 2020=100)
    env_tbl  = _KOSIS_PRICES_TBL if _KOSIS_PRICES_TBL not in (
        "DT_1J22003", "DT_1J22017") else ""
    api_tbls = _kosis_list_price_tables()
    confirmed_tbls = ["DT_1J22005", "DT_1J22112", "DT_1J22001"]

    tbl_candidates = list(dict.fromkeys(
        ([env_tbl] if env_tbl else []) + confirmed_tbls + api_tbls
    ))
    _cache["kosis_list_found_tbls"] = api_tbls

    rows, msg = None, ""
    for tbl in tbl_candidates:
        candidate_rows, candidate_msg = _kosis_get(_KOSIS_PRICES_ORG, tbl, "202101")
        if candidate_rows is None:
            msg = candidate_msg
            continue
        # 이 테이블에 품목명(라면·달걀·계란 등)이 실제로 있는지 확인
        sample_names = {_kosis_item_name(r) for r in candidate_rows[:100]}
        matched_keys = [k for k in _KOSIS_NAME_MAP if any(k in nm for nm in sample_names)]
        if len(matched_keys) >= 3:  # 최소 3개 키워드 매칭
            rows = candidate_rows
            _cache["kosis_prices_tbl_used"] = tbl
            _cache["kosis_prices_sample_names"] = list(sample_names)[:15]
            _cache["kosis_prices_matched_keys"] = matched_keys
            break
        else:
            msg = f"{tbl} 품목 불일치 (매칭={matched_keys}, 샘플={list(sample_names)[:5]})"

    if rows is None:
        _cache["kosis_prices_err"] = msg
        return None

    item_month: dict[str, dict[str, float]] = {}
    for row in rows:
        nm  = _kosis_item_name(row)
        prd = row.get("PRD_DE", "")
        if len(prd) != 6:
            continue
        month = f"{prd[:4]}-{prd[4:]}"
        try:
            val = float(row.get("DT", ""))
        except (ValueError, TypeError):
            continue
        matched = next((v for k, v in _KOSIS_NAME_MAP.items() if k in nm), None)
        if matched:
            item_month.setdefault(matched, {})[month] = val

    if len(item_month) < 5:  # 품목 5개 미만이면 잘못된 응답
        _cache["kosis_prices_err"] = f"품목 매칭 {len(item_month)}개만 성공 (5개 이상 필요)"
        return None

    months = sorted({m for d in item_month.values() for m in d})
    if len(months) < 12:
        return None

    items = {name: [d.get(m) for m in months] for name, d in item_month.items()}
    annual = {
        name: {
            yr: round(
                sum(v for m, v in d.items() if m.startswith(yr)) /
                max(1, sum(1 for m in d if m.startswith(yr))), 1
            )
            for yr in ["2021", "2022", "2023", "2024", "2025"]
            if any(m.startswith(yr) for m in d)
        }
        for name, d in item_month.items()
    }
    return {"months": months, "items": items, "annual": annual}


def _load_cpi_from_kosis() -> dict | None:
    """KOSIS API로 소비자물가지수 총지수(전국) 월별 데이터 수집.
    DT_1J22003 = 소비자물가지수(2020=100) 시도별 → 전국 행만 필터."""
    if not _KOSIS_KEY:
        return None

    # DT_1J22003이 소비자물가지수 시도별 테이블임을 확인 완료
    tbl_candidates = list(dict.fromkeys([
        "DT_1J22003",
        _KOSIS_CPI_TBL if _KOSIS_CPI_TBL != "DT_1J22003" else "",
        "DT_1J22001", "DT_1400078", "DT_1400079",
    ]))
    tbl_candidates = [t for t in tbl_candidates if t]

    rows, msg = None, ""
    for tbl in tbl_candidates:
        rows, msg = _kosis_get(_KOSIS_CPI_ORG, tbl, "202101")
        if rows is not None:
            _cache["kosis_cpi_tbl_used"] = tbl
            break

    if rows is None:
        _cache["kosis_cpi_err"] = msg
        return None

    month_vals: dict[str, float] = {}
    for row in rows:
        prd = row.get("PRD_DE", "")
        if len(prd) != 6:
            continue
        # 시도별 테이블: 전국(C1_NM='전국') 행만 사용
        area = row.get("C1_NM", "")
        if area and area not in ("전국", ""):
            continue
        month = f"{prd[:4]}-{prd[4:]}"
        try:
            val = float(row.get("DT", ""))
        except (ValueError, TypeError):
            continue
        if month not in month_vals:
            month_vals[month] = val

    if len(month_vals) < 12:
        return None

    months = sorted(month_vals.keys())
    return {"months": months, "values": [month_vals[m] for m in months]}


# ── 데이터 로더 (KOSIS → Excel → 하드코딩 순 폴백) ──────────────────────────

def _load_prices_data() -> tuple[dict, str]:
    """생활물가지수: KOSIS API → Excel → 하드코딩 순으로 시도. (데이터, 출처) 반환."""
    # 1) KOSIS API
    result = _load_prices_from_kosis()
    if result:
        return result, "kosis"

    # 2) 로컬 Excel
    xl_path = BASE_DIR / "생활물가지수_2020100__20260607122851.xlsx"
    if xl_path.exists():
        try:
            xl = pd.read_excel(xl_path, header=None)
            month_cols = list(range(2, 55))
            months = [_parse_month_col(xl.iloc[0, c]) for c in month_cols]
            price_items = {}
            for item, row_idx in ITEM_ROW_MAP.items():
                price_items[item] = [
                    float(xl.iloc[row_idx, c]) if pd.notna(xl.iloc[row_idx, c]) else None
                    for c in month_cols
                ]
            annual_cols = {"2021": 55, "2022": 56, "2023": 57, "2024": 58, "2025": 59}
            annual = {
                item: {
                    yr: float(xl.iloc[row_idx, ci]) if pd.notna(xl.iloc[row_idx, ci]) else None
                    for yr, ci in annual_cols.items()
                }
                for item, row_idx in ITEM_ROW_MAP.items()
            }
            return {"months": months, "items": price_items, "annual": annual}, "excel"
        except Exception:
            pass

    # 3) 하드코딩 폴백
    return {"months": _PRICES_MONTHS_FB, "items": _PRICES_ITEMS_FB, "annual": _PRICES_ANNUAL_FB}, "fallback"


def _load_cpi_data() -> tuple[dict, str]:
    """소비자물가지수: KOSIS API → Excel → 하드코딩 순으로 시도. (데이터, 출처) 반환."""
    # 1) KOSIS API
    result = _load_cpi_from_kosis()
    if result:
        return result, "kosis"

    # 2) 로컬 Excel
    xl_path = BASE_DIR / "소비자물가지수_2020100__20260607123034.xlsx"
    if xl_path.exists():
        try:
            xl2 = pd.read_excel(xl_path, header=None)
            cpi_months = [_parse_month_col(xl2.iloc[0, c]) for c in range(1, xl2.shape[1])]
            cpi_vals = [
                float(xl2.iloc[1, c]) if pd.notna(xl2.iloc[1, c]) else None
                for c in range(1, xl2.shape[1])
            ]
            return {"months": cpi_months, "values": cpi_vals}, "excel"
        except Exception:
            pass

    # 3) 하드코딩 폴백
    return {"months": _CPI_MONTHS_FB, "values": _CPI_VALUES_FB}, "fallback"


def _load_data():
    global _cache
    if _cache:
        return

    prices_data, prices_src = _load_prices_data()
    cpi_data,    cpi_src    = _load_cpi_data()

    _cache["oil"]          = _load_oil_data()
    _cache["prices"]       = prices_data
    _cache["cpi"]          = cpi_data
    _cache["elasticities"] = compute_elasticities(_cache["oil"], prices_data)
    _cache["realtime"]     = fetch_realtime_brent()
    _cache["sources"]      = {
        "oil":    "csv" if (BASE_DIR / "chart_20260607T031456.csv").exists() else
                  ("yfinance" if _YF_AVAILABLE else "fallback"),
        "prices": prices_src,
        "cpi":    cpi_src,
    }


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


@app.get("/api/data-source")
def get_data_source():
    """현재 사용 중인 데이터 출처 및 KOSIS API 연결 상태 반환."""
    _load_data()
    sources = _cache.get("sources", {})

    # KOSIS 연결 테스트 (키가 있을 때만, 최근 1개월만 조회)
    kosis_status = "no_key"
    kosis_detail = ""
    kosis_sample = None
    if _KOSIS_KEY:
        rows, msg = _kosis_get(_KOSIS_PRICES_ORG, _KOSIS_PRICES_TBL, "202601")
        if rows is not None:
            kosis_status = "ok"
            kosis_detail = msg
            kosis_sample = rows[:2]  # 응답 구조 확인용 앞 2행
        else:
            kosis_status = "error"
            kosis_detail = msg

    return {
        "kosis_api_key_set": bool(_KOSIS_KEY),
        "kosis_status":      kosis_status,
        "kosis_detail":      kosis_detail,
        "kosis_prices_tbl":  f"{_KOSIS_PRICES_ORG}/{_KOSIS_PRICES_TBL}",
        "kosis_cpi_tbl":     f"{_KOSIS_CPI_ORG}/{_KOSIS_CPI_TBL}",
        "kosis_sample":           kosis_sample,
        "kosis_prices_tbl_used":      _cache.get("kosis_prices_tbl_used"),
        "kosis_cpi_tbl_used":         _cache.get("kosis_cpi_tbl_used"),
        "kosis_prices_sample_names":  _cache.get("kosis_prices_sample_names"),
        "kosis_prices_matched_keys":  _cache.get("kosis_prices_matched_keys"),
        "kosis_list_found_tbls":      _cache.get("kosis_list_found_tbls"),
        "kosis_browse_nodes":         _cache.get("kosis_browse_nodes"),
        "kosis_prices_err":           _cache.get("kosis_prices_err"),
        "kosis_cpi_err":              _cache.get("kosis_cpi_err"),
        "kosis_meta_DT_1J22005":      _cache.get("kosis_meta_DT_1J22005"),
        "data_sources": {
            "oil":    sources.get("oil",    "unknown"),
            "prices": sources.get("prices", "unknown"),
            "cpi":    sources.get("cpi",    "unknown"),
        },
        "source_labels": {
            "kosis":    "KOSIS Open API (통계청 실시간)",
            "excel":    "로컬 Excel 파일 (통계청 다운로드)",
            "yfinance": "Yahoo Finance API",
            "csv":      "로컬 CSV 파일",
            "fallback": "하드코딩 추정값 (폴백)",
        },
    }


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
