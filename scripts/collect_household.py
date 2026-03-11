"""
SGIS 가구 통계 수집 - 시군구별 1인가구 비율, 평균 가구원수
SGIS searchpopulation에서 가구원수별 통계 조회
"""
import requests, time, pandas as pd
from pathlib import Path

CONSUMER_KEY    = "baebbecd2a1a4bffa2d1"
CONSUMER_SECRET = "720bd2a1840b4167a7eb"
BASE = "https://sgisapi.mods.go.kr/OpenAPI3"
OUT_DIR = Path("data/raw/population")
OUT_DIR.mkdir(parents=True, exist_ok=True)

SIDO_CODES = {
    "11": "서울특별시",  "21": "부산광역시",  "22": "대구광역시",
    "23": "인천광역시",  "24": "광주광역시",  "25": "대전광역시",
    "26": "울산광역시",  "29": "세종특별자치시",
    "31": "경기도",      "32": "강원도",      "33": "충청북도",
    "34": "충청남도",    "35": "전라북도",    "36": "전라남도",
    "37": "경상북도",    "38": "경상남도",    "39": "제주특별자치도",
}

# 가구원수별 통계 코드 (SGIS household type codes)
# 1: 1인가구, 2: 2인가구, 3: 3인가구, 4: 4인가구, 5: 5인이상
HOUSEHOLD_TYPES = {
    "1": "hh_1person",
    "2": "hh_2person",
    "3": "hh_3person",
    "4": "hh_4person",
    "5": "hh_5plus",
}

COLLECT_YEARS = ["2020", "2024"]  # 인구총조사 기준


def get_token():
    r = requests.get(
        f"{BASE}/auth/authentication.json",
        params={"consumer_key": CONSUMER_KEY, "consumer_secret": CONSUMER_SECRET},
        timeout=10
    )
    return r.json()["result"]["accessToken"]


def fetch_household(token, year, adm_cd, hh_type=None, retries=3):
    """가구원수별 가구 통계"""
    params = {
        "accessToken": token,
        "year": year,
        "adm_cd": adm_cd,
        "low_search": "1",
    }
    if hh_type:
        params["house_type"] = hh_type

    for attempt in range(retries):
        try:
            r = requests.get(
                f"{BASE}/stats/searchhousehold.json",
                params=params,
                timeout=10
            )
            data = r.json()
            if data.get("errCd") == 0:
                return data.get("result", [])
            # API 오류 시 빈 목록 반환
            return []
        except Exception:
            time.sleep(2 ** attempt)
    return []


def fetch_total_household(token, year, adm_cd, retries=3):
    """총 가구수 조회"""
    params = {
        "accessToken": token,
        "year": year,
        "adm_cd": adm_cd,
        "low_search": "1",
    }
    for attempt in range(retries):
        try:
            r = requests.get(
                f"{BASE}/stats/searchhousehold.json",
                params=params,
                timeout=10
            )
            data = r.json()
            if data.get("errCd") == 0:
                return data.get("result", [])
            return []
        except Exception:
            time.sleep(2 ** attempt)
    return []


def collect_year(year, token):
    print(f"\n  [{year}년 가구 통계]")
    all_rows = []

    for sido_cd, sido_nm in SIDO_CODES.items():
        print(f"    {sido_nm} ...", end=" ", flush=True)

        # 총 가구 수
        total_items = fetch_total_household(token, year, sido_cd)

        rows_by_code = {}
        for item in total_items:
            cd = item.get("adm_cd", "")
            nm = item.get("adm_nm", "")
            rows_by_code[cd] = {
                "year": year,
                "sido": sido_nm,
                "adm_cd": cd,
                "sigungu": nm,
                "total_households": int(item.get("household", 0) or 0),
            }

        if not rows_by_code:
            print("데이터 없음")
            continue

        # 가구원수별 통계
        for hh_type, col_name in HOUSEHOLD_TYPES.items():
            items = fetch_household(token, year, sido_cd, hh_type=hh_type)
            for item in items:
                cd = item.get("adm_cd", "")
                if cd in rows_by_code:
                    rows_by_code[cd][col_name] = int(item.get("household", 0) or 0)
            time.sleep(0.05)

        print(f"{len(rows_by_code)}건")
        all_rows.extend(rows_by_code.values())
        time.sleep(0.3)

    if not all_rows:
        print(f"  [{year}] 가구 데이터 없음 - API 미지원일 수 있음")
        return None

    df = pd.DataFrame(all_rows).fillna(0)

    # 비율 계산
    total = df["total_households"].replace(0, 1)
    df["ratio_1person"] = df.get("hh_1person", 0) / total
    df["ratio_2person"] = df.get("hh_2person", 0) / total

    # 평균 가구원수 추정 (총인구 / 총가구수는 별도 merge에서 계산)
    # 여기선 저장만
    out = OUT_DIR / f"household_{year}.csv"
    df.to_csv(out, index=False, encoding="utf-8-sig")
    print(f"    → {len(df)}행 저장: {out}")
    return df


def main():
    print("SGIS 가구 통계 수집 시작")
    try:
        token = get_token()
        print("Token 발급 완료\n")
    except Exception as e:
        print(f"Token 발급 실패: {e}")
        return

    success = False
    for year in COLLECT_YEARS:
        token = get_token()
        df = collect_year(year, token)
        if df is not None:
            success = True

    if not success:
        print("\n⚠️  SGIS 가구 통계 API를 지원하지 않습니다.")
        print("   대신 인구 데이터에서 proxy 피처를 사용합니다.")
        print("   (ratio_elderly, ratio_working 등 기존 피처 활용)")

    print("\n=== 수집 완료 ===")
    for f in sorted(OUT_DIR.glob("household_*.csv")):
        df = pd.read_csv(f)
        print(f"  {f.name}: {len(df)}행")


if __name__ == "__main__":
    main()
