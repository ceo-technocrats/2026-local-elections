"""
예측 데이터를 GeoJSON features에 주입
- web/public/map_data.geojson  (시군구 레벨)
- web/public/sido_data.geojson (시도 레벨, shapely unary_union)
"""
import pandas as pd
import numpy as np
import json
from pathlib import Path
from shapely.geometry import shape, mapping
from shapely.ops import unary_union, transform
import pyproj

# EPSG:5179 (Korean TM) → EPSG:4326 (WGS84) transformer
_transformer = pyproj.Transformer.from_crs("EPSG:5179", "EPSG:4326", always_xy=True)

def reproject_geometry(geom):
    """shapely geometry를 EPSG:5179에서 WGS84로 변환"""
    return transform(_transformer.transform, geom)

PRED_PATH   = Path("data/predictions/prediction_2026.csv")
GEO_PATH    = Path("web/public/sigungu.geojson")
OUT_SGG     = Path("web/public/map_data.geojson")
OUT_SIDO    = Path("web/public/sido_data.geojson")
MERGED_PATH = Path("data/merged/all_merged.csv")

# 시도 코드 → 시도 이름
SIDO_CODE_MAP = {
    "11": "서울특별시",   "21": "부산광역시",   "22": "대구광역시",
    "23": "인천광역시",   "24": "광주광역시",   "25": "대전광역시",
    "26": "울산광역시",   "29": "세종특별자치시",
    "31": "경기도",       "32": "강원도",        "33": "충청북도",
    "34": "충청남도",     "35": "전라북도",      "36": "전라남도",
    "37": "경상북도",     "38": "경상남도",      "39": "제주특별자치도",
}


def pct(v):
    """float → 소수점 1자리 퍼센트, None if NaN"""
    try:
        f = float(v)
        return None if np.isnan(f) else round(f * 100, 1)
    except (TypeError, ValueError):
        return None


def main():
    pred = pd.read_csv(PRED_PATH)
    pred["adm_cd"] = pred["adm_cd"].astype(str).str.zfill(5)

    # 역대 선거 실적 추가
    merged = pd.read_csv(MERGED_PATH)
    for etype, prefix in [
        ("7회지방선거_시도지사",  "r7"),
        ("8회지방선거_시도지사",  "r8"),
        ("21대대통령선거",        "r21pres"),
    ]:
        sub = merged[merged["election_name"] == etype][
            ["sido", "sigungu_norm", "ratio_더불어민주당", "ratio_국민의힘", "ratio_기타"]
        ].rename(columns={
            "ratio_더불어민주당": f"{prefix}_민주",
            "ratio_국민의힘":     f"{prefix}_국힘",
            "ratio_기타":         f"{prefix}_기타",
        })
        pred = pred.merge(sub, on=["sido", "sigungu_norm"], how="left")

    pred_map = {row["adm_cd"]: row.to_dict() for _, row in pred.iterrows()}

    # ── 시군구 GeoJSON ────────────────────────────────
    with open(GEO_PATH, encoding="utf-8") as f:
        gj = json.load(f)

    matched = 0
    for feature in gj["features"]:
        adm_cd = str(feature["properties"].get("adm_cd", "")).zfill(5)
        if adm_cd not in pred_map:
            continue

        row = pred_map[adm_cd]
        p = feature["properties"]

        p["sido"]      = row.get("sido", "")
        p["sigungu"]   = row.get("sigungu", row.get("sigungu_norm", ""))
        p["total_pop"] = int(row.get("total_pop", 0) or 0)

        # 단체장 예측
        p["pred_민주"]   = pct(row.get("pred_단체장_민주_norm"))
        p["pred_국힘"]   = pct(row.get("pred_단체장_국힘_norm"))
        p["pred_기타"]   = pct(row.get("pred_단체장_기타_norm"))
        p["pred_winner"] = row.get("pred_winner", "")
        p["pred_margin"] = pct(row.get("pred_margin"))

        # 광역의원비례 예측
        p["pred_광역_민주"] = pct(row.get("pred_광역_민주_norm"))
        p["pred_광역_국힘"] = pct(row.get("pred_광역_국힘_norm"))
        p["pred_광역_기타"] = pct(row.get("pred_광역_기타_norm"))

        # 기초의원비례 예측
        p["pred_기초_민주"] = pct(row.get("pred_기초_민주_norm"))
        p["pred_기초_국힘"] = pct(row.get("pred_기초_국힘_norm"))
        p["pred_기초_기타"] = pct(row.get("pred_기초_기타_norm"))

        # 역대 실적
        p["r7_민주"]      = pct(row.get("r7_민주"))
        p["r7_국힘"]      = pct(row.get("r7_국힘"))
        p["r8_민주"]      = pct(row.get("r8_민주"))
        p["r8_국힘"]      = pct(row.get("r8_국힘"))
        p["r21pres_민주"] = pct(row.get("r21pres_민주"))
        p["r21pres_국힘"] = pct(row.get("r21pres_국힘"))
        p["r21pres_기타"] = pct(row.get("r21pres_기타"))

        # 인구 구성
        for col in ["ratio_20s", "ratio_30s", "ratio_40s", "ratio_50s",
                    "ratio_60s", "ratio_70plus", "ratio_elderly", "ratio_female"]:
            p[col] = pct(row.get(col))

        # 광역의회 의석 (시도 집계)
        for col in ["est_광역_민주_비례", "est_광역_국힘_비례", "est_광역_기타_비례",
                    "sido_광역_민주_share", "sido_광역_국힘_share", "sido_광역_기타_share"]:
            v = row.get(col)
            p[col] = int(v) if col.startswith("est_") and v == v else (
                pct(v) if col.startswith("sido_") else None
            )

        # 좌표계 변환: EPSG:5179 → WGS84
        try:
            geom_wgs = reproject_geometry(shape(feature["geometry"]))
            feature["geometry"] = mapping(geom_wgs)
        except Exception:
            pass

        matched += 1

    print(f"시군구 매칭: {matched}/{len(gj['features'])} features")
    with open(OUT_SGG, "w", encoding="utf-8") as f:
        json.dump(gj, f, ensure_ascii=False)
    print(f"저장 → {OUT_SGG}")

    # ── 시도 GeoJSON ─────────────────────────────────
    sido_features_map: dict = {}  # sido_code → {geoms, properties}

    for feature in gj["features"]:
        adm_cd = str(feature["properties"].get("adm_cd", "")).zfill(5)
        sido_code = adm_cd[:2]
        if sido_code not in SIDO_CODE_MAP:
            continue

        if sido_code not in sido_features_map:
            sido_features_map[sido_code] = {"geoms": [], "rows": []}
        sido_features_map[sido_code]["geoms"].append(shape(feature["geometry"]))

        row = pred_map.get(adm_cd, {})
        if row:
            sido_features_map[sido_code]["rows"].append(row)

    sido_features = []
    for sido_code, data in sorted(sido_features_map.items()):
        sido_nm = SIDO_CODE_MAP[sido_code]
        rows = data["rows"]
        if not rows:
            continue

        # 인구 가중 평균
        pops = np.array([float(r.get("total_pop", 0) or 0) for r in rows])
        w = pops if pops.sum() > 0 else np.ones(len(rows))

        def wavg(col):
            vals = np.array([float(r.get(col, 0) or 0) for r in rows])
            return float(np.average(vals, weights=w))

        # 단체장 예측 집계
        m = wavg("pred_단체장_민주_norm")
        k = wavg("pred_단체장_국힘_norm")
        g = wavg("pred_단체장_기타_norm")
        total_mkge = m + k + g
        if total_mkge > 0:
            m, k, g = m/total_mkge, k/total_mkge, g/total_mkge

        # 승자 카운트
        민주_wins = sum(1 for r in rows if r.get("pred_winner") == "더불어민주당")
        국힘_wins = sum(1 for r in rows if r.get("pred_winner") == "국민의힘")

        try:
            sido_geom = unary_union(data["geoms"])
            sido_geo = mapping(sido_geom)
        except Exception:
            continue

        # 광역의회 의석 집계
        first_row = rows[0] if rows else {}

        props = {
            "sido_code":    sido_code,
            "sido":         sido_nm,
            "total_pop":    int(sum(pops)),
            "민주_wins":    민주_wins,
            "국힘_wins":    국힘_wins,
            "total_sgg":    len(rows),
            # 도 평균 단체장 예측
            "pred_민주":    round(m * 100, 1),
            "pred_국힘":    round(k * 100, 1),
            "pred_기타":    round(g * 100, 1),
            "pred_winner":  "더불어민주당" if m > k else "국민의힘",
            # 광역의원비례 시도 평균
            "pred_광역_민주": round(wavg("pred_광역_민주_norm") * 100, 1),
            "pred_광역_국힘": round(wavg("pred_광역_국힘_norm") * 100, 1),
            "pred_광역_기타": round(wavg("pred_광역_기타_norm") * 100, 1),
            # 의석 추정 (첫 번째 행에서 — 시도 레벨로 집계됨)
            "est_광역_민주_비례": int(first_row.get("est_광역_민주_비례", 0) or 0),
            "est_광역_국힘_비례": int(first_row.get("est_광역_국힘_비례", 0) or 0),
            "est_광역_기타_비례": int(first_row.get("est_광역_기타_비례", 0) or 0),
            # 21대 대선 평균
            "r21pres_민주": round(wavg("r21pres_민주") * 100, 1),
            "r21pres_국힘": round(wavg("r21pres_국힘") * 100, 1),
        }

        sido_features.append({
            "type": "Feature",
            "properties": props,
            "geometry": sido_geo,
        })

    sido_gj = {"type": "FeatureCollection", "features": sido_features}
    with open(OUT_SIDO, "w", encoding="utf-8") as f:
        json.dump(sido_gj, f, ensure_ascii=False)
    print(f"시도 GeoJSON: {len(sido_features)}개 시도 → {OUT_SIDO}")


if __name__ == "__main__":
    main()
