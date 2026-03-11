"""
7회(2018) + 8회(2022) 지방선거 전체 선거종류 수집
sgTypecode: 3(시도지사) 4(기초단체장) 5(광역의원지역구) 6(기초의원지역구) 8(광역비례) 9(기초비례)
"""
import requests, time, pandas as pd
from pathlib import Path

API_KEY = "RiAaBZbt50knIT+Uus9cHXFD/l4yN2k20stJJeQ3d4a1foUM6GquI3zXMOrTsjqHJAeAogag7wSVxSvKFzq5GA=="
BASE = "https://apis.data.go.kr/9760000/VoteXmntckInfoInqireService2"
OUT_DIR = Path("data/raw/elections")
OUT_DIR.mkdir(parents=True, exist_ok=True)

SIDO_BY_ELECTION = {
    "20180613": [
        "서울특별시","부산광역시","대구광역시","인천광역시",
        "광주광역시","대전광역시","울산광역시","세종특별자치시",
        "경기도","강원도","충청북도","충청남도",
        "전라북도","전라남도","경상북도","경상남도","제주특별자치도"
    ],
    "20220601": [
        "서울특별시","부산광역시","대구광역시","인천광역시",
        "광주광역시","대전광역시","울산광역시","세종특별자치시",
        "경기도","강원도","충청북도","충청남도",
        "전라북도","전라남도","경상북도","경상남도","제주특별자치도"
    ],
}

ELECTIONS = [
    # 7회 지방선거 추가 종류 (3번은 이미 수집)
    ("20180613", "4", "7회지방선거_기초단체장"),
    ("20180613", "5", "7회지방선거_광역의원지역구"),
    ("20180613", "6", "7회지방선거_기초의원지역구"),
    ("20180613", "8", "7회지방선거_광역의원비례"),
    ("20180613", "9", "7회지방선거_기초의원비례"),
    # 8회 지방선거 추가 종류 (3번은 이미 수집)
    ("20220601", "4", "8회지방선거_기초단체장"),
    ("20220601", "5", "8회지방선거_광역의원지역구"),
    ("20220601", "6", "8회지방선거_기초의원지역구"),
    ("20220601", "8", "8회지방선거_광역의원비례"),
    ("20220601", "9", "8회지방선거_기초의원비례"),
]

def fetch_page(sg_id, sg_typecode, sd_name, page=1, rows=100, retries=4):
    for attempt in range(retries):
        try:
            params = {
                "serviceKey": API_KEY,
                "sgId": sg_id, "sgTypecode": sg_typecode,
                "sdName": sd_name,
                "numOfRows": str(rows), "pageNo": str(page),
                "resultType": "json"
            }
            r = requests.get(f"{BASE}/getXmntckSttusInfoInqire", params=params, timeout=15)
            r.raise_for_status()
            body = r.json()["response"]["body"]
            items = body["items"].get("item", [])
            if isinstance(items, dict):
                items = [items]
            total = int(body.get("totalCount", 0))
            return items, total
        except Exception as e:
            wait = 2 ** attempt
            time.sleep(wait)
    return [], 0

def parse_row(item, sg_id, sg_typecode, label):
    sgg = item.get("sggName", "").strip()
    wiw = item.get("wiwName", "").strip()
    # 합계 행 제외
    if wiw == "합계" or sgg == "합계":
        return None

    votes = {}
    for i in range(1, 51):
        party = item.get(f"jd{i:02d}", "").strip()
        dugsu = item.get(f"dugsu{i:02d}", "0")
        if party and dugsu and str(dugsu) != "0":
            try:
                votes[party] = int(dugsu)
            except ValueError:
                pass

    if not votes:  # 정당 득표 없는 행 제외 (교육감 등)
        return None

    row = {
        "sg_id": sg_id,
        "sg_typecode": sg_typecode,
        "election_name": label,
        "sido": item.get("sdName", "").strip(),
        "sigungu": wiw,
        "sgg_name": sgg,
        "total_voters": int(item.get("sunsu", 0) or 0),
        "total_voted": int(item.get("tusu", 0) or 0),
        "valid_votes": int(item.get("yutusu", 0) or 0),
        "invalid_votes": int(item.get("mutusu", 0) or 0),
    }
    for party, cnt in votes.items():
        row[f"party_{party}"] = cnt
    return row

def collect(sg_id, sg_typecode, label):
    sido_list = SIDO_BY_ELECTION[sg_id]
    all_rows = []

    print(f"\n[{label}]")
    for sido in sido_list:
        print(f"  {sido} ...", end=" ", flush=True)
        page = 1
        sido_rows = []
        while True:
            items, total = fetch_page(sg_id, sg_typecode, sido, page=page)
            if not items:
                break
            for item in items:
                row = parse_row(item, sg_id, sg_typecode, label)
                if row:
                    sido_rows.append(row)
            if page * 100 >= total:
                break
            page += 1
            time.sleep(0.1)
        print(f"{len(sido_rows)}건")
        all_rows.extend(sido_rows)
        time.sleep(0.3)

    if not all_rows:
        print("  → 데이터 없음")
        return

    df = pd.DataFrame(all_rows).fillna(0)
    out_path = OUT_DIR / f"{sg_id}_{label}.csv"
    df.to_csv(out_path, index=False, encoding="utf-8-sig")

    party_cols = [c for c in df.columns if c.startswith("party_")]
    parties = {c.replace("party_",""):int(df[c].sum()) for c in party_cols if df[c].sum()>0}
    top3 = sorted(parties.items(), key=lambda x:-x[1])[:3]
    print(f"  → {len(df)}행 저장 | 상위정당: {top3}")

def main():
    for sg_id, sg_typecode, label in ELECTIONS:
        collect(sg_id, sg_typecode, label)

    print("\n\n=== 전체 수집 현황 ===")
    for f in sorted(OUT_DIR.glob("*.csv")):
        df = pd.read_csv(f)
        print(f"  {f.stem}: {len(df)}행, 시도 {df['sido'].nunique()}개")

if __name__ == "__main__":
    main()
