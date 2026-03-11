"""
선관위 API - 역대 선거 개표결과 수집
getXmntckSttusInfoInqire: 정당명 + 득표수 + 지역별 결과
"""
import requests
import json
import time
import os
import pandas as pd
from pathlib import Path

API_KEY = "RiAaBZbt50knIT+Uus9cHXFD/l4yN2k20stJJeQ3d4a1foUM6GquI3zXMOrTsjqHJAeAogag7wSVxSvKFzq5GA=="
BASE = "https://apis.data.go.kr/9760000/VoteXmntckInfoInqireService2"
OUT_DIR = Path("data/raw/elections")
OUT_DIR.mkdir(parents=True, exist_ok=True)

# 수집 대상 선거
ELECTIONS = [
    # (sgId,         sgTypecode, 선거명)
    ("20170509",    "1",        "19대대통령선거"),
    ("20180613",    "3",        "7회지방선거_시도지사"),
    ("20200415",    "2",        "21대국회의원선거_지역구"),
    ("20220309",    "1",        "20대대통령선거"),
    ("20220601",    "3",        "8회지방선거_시도지사"),
    ("20240410",    "2",        "22대국회의원선거_지역구"),
    ("20250603",    "1",        "21대대통령선거"),
]

# 17개 시도 목록 (구 명칭 + 2023~2024년 변경된 신 명칭 포함)
SIDO_LIST = [
    "서울특별시", "부산광역시", "대구광역시", "인천광역시",
    "광주광역시", "대전광역시", "울산광역시", "세종특별자치시",
    "경기도",
    "강원도", "강원특별자치도",        # 2023년 명칭 변경
    "충청북도", "충청남도",
    "전라북도", "전북특별자치도",       # 2024년 명칭 변경
    "전라남도", "경상북도", "경상남도", "제주특별자치도"
]

def fetch_election_data(sg_id, sg_typecode, sd_name=None, page=1, rows=100):
    params = {
        "serviceKey": API_KEY,
        "sgId": sg_id,
        "sgTypecode": sg_typecode,
        "numOfRows": str(rows),
        "pageNo": str(page),
        "resultType": "json"
    }
    if sd_name:
        params["sdName"] = sd_name

    r = requests.get(
        f"{BASE}/getXmntckSttusInfoInqire",
        params=params,
        timeout=15
    )
    r.raise_for_status()
    return r.json()

def parse_items(data):
    try:
        items = data["response"]["body"]["items"]["item"]
        if isinstance(items, dict):
            items = [items]
        return items
    except (KeyError, TypeError):
        return []

def parse_party_votes(item):
    """jd01~jd50, dugsu01~dugsu50 파싱 → {정당명: 득표수}"""
    votes = {}
    for i in range(1, 51):
        party = item.get(f"jd{i:02d}", "").strip()
        dugsu = item.get(f"dugsu{i:02d}", "0")
        if party and dugsu and dugsu != "0":
            try:
                votes[party] = int(dugsu)
            except ValueError:
                pass
    return votes

def collect_election(sg_id, sg_typecode, label):
    print(f"\n{'='*60}")
    print(f"수집 시작: {label} (sgId={sg_id}, typecode={sg_typecode})")
    all_rows = []

    for sido in SIDO_LIST:
        print(f"  {sido} ...", end=" ", flush=True)
        page = 1
        sido_rows = []

        while True:
            try:
                data = fetch_election_data(sg_id, sg_typecode, sido, page=page, rows=100)
                items = parse_items(data)
                if not items:
                    break

                for item in items:
                    wiw = item.get("wiwName", "").strip()
                    if not wiw or wiw == "합계":
                        continue  # 소계 행 제외, 구시군 단위만

                    votes = parse_party_votes(item)
                    total_valid = int(item.get("yutusu", 0) or 0)
                    total_voters = int(item.get("sunsu", 0) or 0)
                    total_voted = int(item.get("tusu", 0) or 0)

                    row = {
                        "sg_id": sg_id,
                        "sg_typecode": sg_typecode,
                        "election_name": label,
                        "sido": item.get("sdName", sido),
                        "sigungu": wiw,
                        "sgg_name": item.get("sggName", ""),
                        "total_voters": total_voters,
                        "total_voted": total_voted,
                        "valid_votes": total_valid,
                        "invalid_votes": int(item.get("mutusu", 0) or 0),
                    }
                    # 정당별 득표수 추가
                    for party, cnt in votes.items():
                        row[f"party_{party}"] = cnt

                    sido_rows.append(row)

                total_count = int(data["response"]["body"].get("totalCount", 0))
                if page * 100 >= total_count:
                    break
                page += 1
                time.sleep(0.1)

            except Exception as e:
                print(f"[오류: {e}]", end=" ")
                break

        print(f"{len(sido_rows)}건")
        all_rows.extend(sido_rows)
        time.sleep(0.2)

    if not all_rows:
        print(f"  → 데이터 없음")
        return None

    df = pd.DataFrame(all_rows).fillna(0)
    out_path = OUT_DIR / f"{sg_id}_{label}.csv"
    df.to_csv(out_path, index=False, encoding="utf-8-sig")
    print(f"  → 저장: {out_path} ({len(df)}행)")
    return df

def main():
    all_dfs = {}
    for sg_id, sg_typecode, label in ELECTIONS:
        df = collect_election(sg_id, sg_typecode, label)
        if df is not None:
            all_dfs[label] = df

    print(f"\n\n수집 완료: {len(all_dfs)}개 선거")
    for label, df in all_dfs.items():
        party_cols = [c for c in df.columns if c.startswith("party_")]
        print(f"  {label}: {len(df)}행, 정당 {len(party_cols)}개")

if __name__ == "__main__":
    main()
