"""
SGIS API - 시군구 행정구역 경계 GeoJSON 수집
"""
import requests, json, time
from pathlib import Path

CONSUMER_KEY    = "baebbecd2a1a4bffa2d1"
CONSUMER_SECRET = "720bd2a1840b4167a7eb"
BASE = "https://sgisapi.mods.go.kr/OpenAPI3"

SIDO_CODES = {
    "11": "서울특별시",  "21": "부산광역시",  "22": "대구광역시",
    "23": "인천광역시",  "24": "광주광역시",  "25": "대전광역시",
    "26": "울산광역시",  "29": "세종특별자치시",
    "31": "경기도",      "32": "강원도",      "33": "충청북도",
    "34": "충청남도",    "35": "전라북도",    "36": "전라남도",
    "37": "경상북도",    "38": "경상남도",    "39": "제주특별자치도",
}

OUT_DIR = Path("web/public")
OUT_DIR.mkdir(parents=True, exist_ok=True)


def get_token():
    r = requests.get(
        f"{BASE}/auth/authentication.json",
        params={"consumer_key": CONSUMER_KEY, "consumer_secret": CONSUMER_SECRET},
        timeout=10
    )
    return r.json()["result"]["accessToken"]


def fetch_boundary(token, adm_cd, year="2024", retries=3):
    for attempt in range(retries):
        try:
            r = requests.get(
                f"{BASE}/boundary/hadmarea.geojson",
                params={
                    "accessToken": token,
                    "year": year,
                    "adm_cd": adm_cd,
                    "low_search": "1",
                },
                timeout=30
            )
            if r.status_code == 200:
                return r.json()
        except Exception as e:
            print(f"  [오류] {e}")
            time.sleep(2 ** attempt)
    return None


def main():
    print("GeoJSON 경계 데이터 수집 시작\n")
    token = get_token()

    all_features = []

    for sido_cd, sido_nm in SIDO_CODES.items():
        print(f"  {sido_nm} ...", end=" ", flush=True)
        gj = fetch_boundary(token, sido_cd)

        if gj is None:
            print("실패")
            continue

        # 응답 구조 확인
        if isinstance(gj, dict) and "features" in gj:
            features = gj["features"]
        elif isinstance(gj, dict) and "result" in gj:
            # SGIS 래핑 응답
            features = gj["result"].get("features", [])
        else:
            print(f"알 수 없는 응답: {str(gj)[:100]}")
            continue

        print(f"{len(features)}개 피처")
        all_features.extend(features)
        time.sleep(0.5)

    if not all_features:
        print("\n경계 데이터 수집 실패")
        return

    combined_geojson = {
        "type": "FeatureCollection",
        "features": all_features
    }

    # 저장
    out_path = OUT_DIR / "sigungu.geojson"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(combined_geojson, f, ensure_ascii=False)

    print(f"\n총 {len(all_features)}개 피처 저장 → {out_path}")

    # 첫 피처 구조 확인
    if all_features:
        print("\n[첫 피처 properties]")
        print(json.dumps(all_features[0].get("properties", {}), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
