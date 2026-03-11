"""
선거 데이터 소스 탐색 및 수집 스크립트
"""
import requests
import re
import json

headers = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
}

API_KEY_ENC = "RiAaBZbt50knIT%2BUus9cHXFD%2Fl4yN2k20stJJeQ3d4a1foUM6GquI3zXMOrTsjqHJAeAogag7wSVxSvKFzq5GA%3D%3D"
API_KEY_DEC = "RiAaBZbt50knIT+Uus9cHXFD/l4yN2k20stJJeQ3d4a1foUM6GquI3zXMOrTsjqHJAeAogag7wSVxSvKFzq5GA=="
BASE = "https://apis.data.go.kr/9760000/VoteXmntckInfoInqireService2"

# ── 1. NEC 열린데이터 포털 ──────────────────────────────
print("=== 1. NEC 열린데이터 포털 ===")
try:
    r = requests.get("https://open.nec.go.kr/portal/mainPage.do", headers=headers, timeout=10)
    print(f"Status: {r.status_code}")
    links = re.findall(r'href=["\']([^"\']*)["\']', r.text)
    election_links = [l for l in links if any(k in l for k in ['선거', 'election', 'xlsx', 'csv', 'xls', 'download'])]
    for l in election_links[:10]:
        print(f"  {l}")
except Exception as e:
    print(f"  Error: {e}")

# ── 2. VoteXmntck API 오퍼레이션 탐색 ─────────────────
print("\n=== 2. VoteXmntck API 오퍼레이션 탐색 ===")
# 서비스명에서 파생 가능한 패턴들
candidates = [
    "getVoteXmntckInfoInqire",
    "getVoteXmntckInfo",
    "getSggVoteXmntckInfo",
    "getVoteXmntckSggInfo",
    "getVoteXmntckPcInfo",
    "getVoteXmntckSidoInfo",
    "getVoteXmntckNationalInfo",
    "getVoteXmntckTotalInfo",
]
for op in candidates:
    url = f"{BASE}/{op}"
    params = {"serviceKey": API_KEY_DEC, "sgId": "20220601", "sgTypecode": "2", "numOfRows": "3", "pageNo": "1"}
    try:
        r = requests.get(url, params=params, timeout=5)
        content = r.text[:100]
        print(f"  {op}: [{r.status_code}] {content}")
    except Exception as e:
        print(f"  {op}: Error - {e}")

# ── 3. 다른 NEC API 서비스 (같은 키로) ─────────────────
print("\n=== 3. 다른 NEC API 서비스 시도 ===")
other_services = [
    ("WinnerInfoInqireService2", "getWinnerInfoInqire"),
    ("ElectionInfoInqireService2", "getElectionInfoInqire"),
    ("VoteResultInqireService", "getVoteResultInqire"),
    ("PoliticalPartyVoteInqireService2", "getPoliticalPartyVoteInqire"),
    ("GvrnmntEltnInfoInqireService2", "getGvrnmntEltnInfoInqire"),
]
for svc, op in other_services:
    url = f"https://apis.data.go.kr/9760000/{svc}/{op}"
    params = {"serviceKey": API_KEY_DEC, "sgId": "20220601", "sgTypecode": "2", "numOfRows": "3", "pageNo": "1"}
    try:
        r = requests.get(url, params=params, timeout=5)
        print(f"  {svc}/{op}: [{r.status_code}] {r.text[:80]}")
    except Exception as e:
        print(f"  Error: {e}")

print("\n완료")
