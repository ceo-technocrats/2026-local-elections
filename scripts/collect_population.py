"""
SGIS 센서스 API - 시군구별 연령대별 인구 수집
수집 연도: 2017(7회지방선거), 2022(8회지방선거), 2024(9회예측)
"""
import requests, time, pandas as pd
from pathlib import Path

CONSUMER_KEY    = "baebbecd2a1a4bffa2d1"
CONSUMER_SECRET = "720bd2a1840b4167a7eb"
BASE = "https://sgisapi.mods.go.kr/OpenAPI3"
OUT_DIR = Path("data/raw/population")
OUT_DIR.mkdir(parents=True, exist_ok=True)

# 시도 코드 (행정구역 코드 2자리)
SIDO_CODES = {
    "11": "서울특별시",  "21": "부산광역시",  "22": "대구광역시",
    "23": "인천광역시",  "24": "광주광역시",  "25": "대전광역시",
    "26": "울산광역시",  "29": "세종특별자치시",
    "31": "경기도",      "32": "강원도",      "33": "충청북도",
    "34": "충청남도",    "35": "전라북도",    "36": "전라남도",
    "37": "경상북도",    "38": "경상남도",    "39": "제주특별자치도",
}

# age_type 코드 → 연령대
AGE_TYPES = {
    "30": "age_0_9",   "31": "age_10_19", "32": "age_20_29",
    "33": "age_30_39", "34": "age_40_49", "35": "age_50_59",
    "36": "age_60_69", "37": "age_70_79", "38": "age_80_89",
    "39": "age_90plus",
    # 요약 지표
    "22": "age_0_14",   "23": "age_15_64",  "24": "age_65plus",
}

COLLECT_YEARS = ["2017", "2022", "2024"]


def get_token():
    r = requests.get(
        f"{BASE}/auth/authentication.json",
        params={"consumer_key": CONSUMER_KEY, "consumer_secret": CONSUMER_SECRET},
        timeout=10
    )
    return r.json()["result"]["accessToken"]


def fetch_population(token, year, adm_cd, age_type=None, gender="0", retries=3):
    params = {"accessToken": token, "year": year, "adm_cd": adm_cd,
              "low_search": "1", "gender": gender}
    if age_type:
        params["age_type"] = age_type
    for attempt in range(retries):
        try:
            r = requests.get(f"{BASE}/stats/searchpopulation.json",
                             params=params, timeout=10)
            data = r.json()
            if data.get("errCd") == 0:
                return data["result"]
            return []
        except Exception:
            time.sleep(2 ** attempt)
    return []


def collect_year(year, token):
    print(f"\n  [{year}년]")
    all_rows = []

    for sido_cd, sido_nm in SIDO_CODES.items():
        print(f"    {sido_nm} ...", end=" ", flush=True)

        # 1) 총인구 (성별 포함)
        total_items = fetch_population(token, year, sido_cd)
        male_items  = fetch_population(token, year, sido_cd, gender="1")
        female_items= fetch_population(token, year, sido_cd, gender="2")

        # adm_cd → row dict 매핑
        rows_by_code = {}
        for item in total_items:
            cd = item["adm_cd"]
            rows_by_code[cd] = {
                "year": year, "sido": sido_nm,
                "adm_cd": cd, "sigungu": item["adm_nm"],
                "total_pop": int(item.get("population", 0) or 0),
            }
        for item in male_items:
            cd = item["adm_cd"]
            if cd in rows_by_code:
                rows_by_code[cd]["male_pop"] = int(item.get("population", 0) or 0)
        for item in female_items:
            cd = item["adm_cd"]
            if cd in rows_by_code:
                rows_by_code[cd]["female_pop"] = int(item.get("population", 0) or 0)

        # 2) 연령대별 인구
        for age_code, col_name in AGE_TYPES.items():
            age_items = fetch_population(token, year, sido_cd, age_type=age_code)
            for item in age_items:
                cd = item["adm_cd"]
                if cd in rows_by_code:
                    rows_by_code[cd][col_name] = int(item.get("population", 0) or 0)
            time.sleep(0.05)

        print(f"{len(rows_by_code)}건")
        all_rows.extend(rows_by_code.values())
        time.sleep(0.3)

    df = pd.DataFrame(all_rows).fillna(0)

    # 비율 컬럼 추가
    df["ratio_20s"]   = df["age_20_29"]  / df["total_pop"].replace(0, 1)
    df["ratio_30s"]   = df["age_30_39"]  / df["total_pop"].replace(0, 1)
    df["ratio_40s"]   = df["age_40_49"]  / df["total_pop"].replace(0, 1)
    df["ratio_50s"]   = df["age_50_59"]  / df["total_pop"].replace(0, 1)
    df["ratio_60s"]   = df["age_60_69"]  / df["total_pop"].replace(0, 1)
    df["ratio_70plus"]= (df["age_70_79"] + df["age_80_89"] + df["age_90plus"]) / df["total_pop"].replace(0, 1)
    df["ratio_elderly"]= df["age_65plus"] / df["total_pop"].replace(0, 1)
    df["ratio_working"]= df["age_15_64"] / df["total_pop"].replace(0, 1)
    df["ratio_female"] = df["female_pop"] / df["total_pop"].replace(0, 1)

    out = OUT_DIR / f"population_{year}.csv"
    df.to_csv(out, index=False, encoding="utf-8-sig")
    print(f"    → {len(df)}행 저장: {out}")
    return df


def main():
    print("SGIS 인구 데이터 수집 시작")
    token = get_token()
    print(f"Token 발급 완료\n")

    for year in COLLECT_YEARS:
        # 토큰은 약 24시간 유효하지만 안전하게 매 연도마다 재발급
        token = get_token()
        collect_year(year, token)

    # 전체 병합 확인
    print("\n=== 수집 완료 ===")
    for f in sorted(OUT_DIR.glob("*.csv")):
        df = pd.read_csv(f)
        print(f"  {f.name}: {len(df)}행, 컬럼 {len(df.columns)}개")


if __name__ == "__main__":
    main()
