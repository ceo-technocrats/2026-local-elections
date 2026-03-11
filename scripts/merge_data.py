"""
선거 결과 + 인구 데이터 병합
- 지역명 정합 (공백 제거, 특수 케이스 처리)
- 선거별 정당 득표율 계산
- 인구 피처와 병합
"""
import re
import pandas as pd
import numpy as np
from pathlib import Path

ELECTIONS_DIR  = Path("data/raw/elections")
POPULATION_DIR = Path("data/raw/population")
OUT_DIR        = Path("data/merged")
OUT_DIR.mkdir(parents=True, exist_ok=True)

# ── 선거 → 해당 인구 연도 매핑 ──────────────────────────
ELECTION_POP_YEAR = {
    "20170509": "2017",  # 19대 대선
    "20180613": "2017",  # 7회 지방선거
    "20220601": "2022",  # 8회 지방선거
    "20220309": "2022",  # 20대 대선
    "20200415": "2017",  # 21대 총선 (2017이 가장 근접)
    "20240410": "2024",  # 22대 총선
    "20250603": "2024",  # 21대 대선 (2024가 가장 최근)
}

# 주요 정당 통일 매핑 (당명 변경 이력 반영)
# 모든 비주요 정당 → "기타"로 통합
PARTY_ALIAS = {
    # 보수 계열
    "자유한국당":    "국민의힘",
    "미래통합당":    "국민의힘",
    "새누리당":      "국민의힘",
    # 민주 계열
    "열린민주당":    "더불어민주당",
    "더불어시민당":  "더불어민주당",
    # 모두 기타로 통합
    "국민의당":      "기타",
    "바른미래당":    "기타",
    "바른정당":      "기타",
    "민주평화당":    "기타",
    "민생당":        "기타",
    "정의당":        "기타",
    "진보당":        "기타",
    "개혁신당":      "기타",
    "새로운미래":    "기타",
    "국가혁명당":    "기타",
    "조국혁신당":    "기타",
    "민주노동당":    "기타",
    "무소속":        "기타",
}

# 2023~2024년 행정구역 명칭 변경 → 인구 데이터 기준 명칭으로 통일
SIDO_RENAME = {
    "강원특별자치도": "강원도",
    "전북특별자치도": "전라북도",
}

# 시군구 이름 변경 이력 (선거 당시 이름 → SGIS 이름)
# 인천 남구: 2018년 미추홀구로 개명, 하지만 SGIS 2017 데이터도 이미 미추홀구로 표기
SIGUNGU_RENAME = {
    ("인천광역시", "남구"): "미추홀구",
}

# 국회의원 선거구 → 행정 시군구 명시적 매핑
# 부천시: 2016년 구 폐지, but 선거구 이름에는 여전히 구명 사용
DISTRICT_TO_SIGUNGU = {
    "부천시오정구": "부천시",
    "부천시원미구": "부천시",
    "부천시소사구": "부천시",
}

MAJOR_PARTIES = ["더불어민주당", "국민의힘"]


# ── 1. 인구 데이터 정규화 ──────────────────────────────
def normalize_pop(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    # 시군구명 공백 제거
    df["sigungu_norm"] = df["sigungu"].str.replace(" ", "", regex=False)

    # 세종시 → 세종특별자치시
    df["sido"] = df["sido"].replace("세종특별자치시", "세종특별자치시")
    df.loc[df["sigungu_norm"] == "세종시", "sigungu_norm"] = "세종특별자치시"

    # 부천시 3개 구 → 1개로 합산
    bucheon_mask = df["sigungu_norm"].str.startswith("부천시") & df["sido"].str.contains("경기")
    if bucheon_mask.sum() > 0:
        bucheon = df[bucheon_mask].copy()
        num_cols = df.select_dtypes(include="number").columns
        bucheon_sum = bucheon[num_cols].sum()
        # 비율 컬럼은 재계산
        ratio_cols = [c for c in num_cols if c.startswith("ratio_")]
        for col in ratio_cols:
            bucheon_sum[col] = np.nan  # 나중에 재계산

        new_row = df[bucheon_mask].iloc[0].copy()
        for col in num_cols:
            new_row[col] = bucheon_sum[col]
        new_row["sigungu"] = "부천시"
        new_row["sigungu_norm"] = "부천시"

        # 비율 재계산
        total = new_row["total_pop"]
        if total > 0:
            for col in ratio_cols:
                base_col = col.replace("ratio_", "age_").replace("ratio_female", "female_pop")
                # 비율 컬럼 재계산
                pass
        new_row["ratio_20s"]    = new_row["age_20_29"] / total if total else 0
        new_row["ratio_30s"]    = new_row["age_30_39"] / total if total else 0
        new_row["ratio_40s"]    = new_row["age_40_49"] / total if total else 0
        new_row["ratio_50s"]    = new_row["age_50_59"] / total if total else 0
        new_row["ratio_60s"]    = new_row["age_60_69"] / total if total else 0
        new_row["ratio_70plus"] = (new_row["age_70_79"] + new_row["age_80_89"] + new_row["age_90plus"]) / total if total else 0
        new_row["ratio_elderly"]= new_row["age_65plus"] / total if total else 0
        new_row["ratio_working"]= new_row["age_15_64"] / total if total else 0
        new_row["ratio_female"] = new_row["female_pop"] / total if total else 0

        df = df[~bucheon_mask]
        df = pd.concat([df, new_row.to_frame().T], ignore_index=True)

    # 군위군: 2022 이전 데이터는 경상북도, 2024는 대구광역시 → 경상북도로 통일
    df.loc[(df["sigungu_norm"] == "군위군") & (df["sido"] == "대구광역시"), "sido"] = "경상북도"

    return df


# ── 2. 선거 데이터 정규화 ──────────────────────────────
def normalize_election(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["sigungu_norm"] = df["sigungu"].str.replace(" ", "", regex=False)

    # election_name에서 sgId 접두사 제거 (중복 수집으로 인한 불일치 정규화)
    df["election_name"] = df["election_name"].str.replace(r'^\d{8}_', '', regex=True)

    # 세종 통일
    df.loc[df["sigungu_norm"] == "세종특별자치시", "sigungu_norm"] = "세종특별자치시"

    # 시군구 이름 변경 이력 적용 (남구 → 미추홀구 등)
    for (sido_val, old_name), new_name in SIGUNGU_RENAME.items():
        mask = (df["sido"] == sido_val) & (df["sigungu_norm"] == old_name)
        df.loc[mask, "sigungu_norm"] = new_name

    # 명시적 선거구 → 행정구역 매핑 (부천시 구들)
    for district, sigungu in DISTRICT_TO_SIGUNGU.items():
        df.loc[df["sigungu_norm"] == district, "sigungu_norm"] = sigungu

    # 국회의원 선거구 갑/을/병/정/무 접미사 제거
    # 예: 화성시갑 → 화성시, 수원시갑 → 수원시
    df["sigungu_norm"] = df["sigungu_norm"].str.replace(r'(갑|을|병|정|무)$', '', regex=True)

    # 군위군: 2023년 대구광역시 편입, 인구는 경상북도로 통일
    df.loc[(df["sigungu_norm"] == "군위군") & (df["sido"] == "대구광역시"), "sido"] = "경상북도"

    # 시도 명칭 변경 정규화 (강원특별자치도 → 강원도 등)
    df["sido"] = df["sido"].replace(SIDO_RENAME)

    # 정당 컬럼 당명 통일
    party_cols = [c for c in df.columns if c.startswith("party_")]
    alias_map = {}
    for col in party_cols:
        party = col.replace("party_", "")
        canonical = PARTY_ALIAS.get(party, party)
        if canonical != party:
            alias_map[col] = f"party_{canonical}"

    for old_col, new_col in alias_map.items():
        if new_col not in df.columns:
            df[new_col] = 0
        df[new_col] = df[new_col] + df[old_col]
        df = df.drop(columns=[old_col])

    # 같은 (sido, sigungu_norm)으로 집계 (선거구 → 행정구역 통합 후 중복 행 합산)
    id_cols = ["sg_id", "sg_typecode", "election_name", "sido", "sigungu_norm"]
    id_cols = [c for c in id_cols if c in df.columns]
    num_cols = df.select_dtypes(include="number").columns.tolist()
    str_cols = [c for c in df.columns if c not in id_cols and c not in num_cols]

    agg_dict = {col: "sum" for col in num_cols}
    for col in str_cols:
        agg_dict[col] = "first"

    df = df.groupby(id_cols, as_index=False).agg(agg_dict)

    # 득표율 계산
    updated_party_cols = [c for c in df.columns if c.startswith("party_")]
    total_votes = df[updated_party_cols].sum(axis=1)
    total_votes = total_votes.replace(0, np.nan)

    for col in updated_party_cols:
        party = col.replace("party_", "")
        df[f"ratio_{party}"] = df[col] / total_votes

    # 기타 정당 비율 보정 (민주+국힘 외 나머지, 합이 1이 되도록)
    r_민주 = df.get("ratio_더불어민주당", pd.Series(0.0, index=df.index)).fillna(0)
    r_국힘 = df.get("ratio_국민의힘",     pd.Series(0.0, index=df.index)).fillna(0)
    if "ratio_기타" not in df.columns:
        df["ratio_기타"] = (1 - r_민주 - r_국힘).clip(0, 1)
    else:
        df["ratio_기타"] = df["ratio_기타"].fillna((1 - r_민주 - r_국힘).clip(0, 1))

    return df


# ── 3. 병합 ───────────────────────────────────────────
def merge_election_population(elec_df, pop_df, label):
    elec_n = normalize_election(elec_df)
    pop_n  = normalize_pop(pop_df)

    merged = elec_n.merge(
        pop_n,
        on=["sido", "sigungu_norm"],
        how="left",
        suffixes=("_elec", "_pop")
    )

    # 매칭 확인
    matched   = merged["total_pop"].notna().sum()
    unmatched = merged["total_pop"].isna().sum()
    print(f"    매칭: {matched}/{len(merged)}  미매칭: {unmatched}")

    if unmatched > 0:
        # merge 후 sigungu가 sigungu_elec으로 바뀔 수 있음
        sgg_col = "sigungu_elec" if "sigungu_elec" in merged.columns else "sigungu"
        miss = merged[merged["total_pop"].isna()][[
            "sido", sgg_col, "sigungu_norm"
        ]].drop_duplicates().rename(columns={sgg_col: "sigungu"})
        for _, r in miss.iterrows():
            print(f"      미매칭: [{r['sido']}] '{r['sigungu']}' (norm: '{r['sigungu_norm']}')")

    return merged


# ── 4. 전체 실행 ──────────────────────────────────────
def main():
    print("=== 데이터 병합 시작 ===\n")

    # 인구 데이터 로드
    pop_dfs = {}
    for year in ["2017", "2022", "2024"]:
        pop_dfs[year] = pd.read_csv(POPULATION_DIR / f"population_{year}.csv")
        pop_dfs[year] = normalize_pop(pop_dfs[year])
    print("인구 데이터 로드 완료\n")

    all_merged = []

    for elec_file in sorted(ELECTIONS_DIR.glob("*.csv")):
        sg_id = elec_file.stem.split("_")[0]
        label = elec_file.stem
        pop_year = ELECTION_POP_YEAR.get(sg_id, "2022")

        print(f"[{label}]  인구연도={pop_year}")

        elec_df = pd.read_csv(elec_file)
        pop_df  = pop_dfs[pop_year]

        merged = merge_election_population(elec_df, pop_df, label)
        merged["pop_year"] = pop_year

        out_path = OUT_DIR / f"{label}_merged.csv"
        merged.to_csv(out_path, index=False, encoding="utf-8-sig")
        all_merged.append(merged)
        print()

    # 전체 통합 파일 (모델 학습용)
    combined = pd.concat(all_merged, ignore_index=True)
    combined.to_csv(OUT_DIR / "all_merged.csv", index=False, encoding="utf-8-sig")
    print(f"전체 통합: {len(combined)}행 → data/merged/all_merged.csv")

    return combined


if __name__ == "__main__":
    df = main()

    # 샘플 확인
    print("\n=== 병합 결과 샘플 ===")
    sgg_col = "sigungu_elec" if "sigungu_elec" in df.columns else "sigungu"
    sample = df[df["election_name"] == "8회지방선거_시도지사"][
        ["sido", sgg_col, "ratio_더불어민주당", "ratio_국민의힘",
         "ratio_20s", "ratio_30s", "ratio_50s", "ratio_elderly"]
    ].dropna().head(8)
    pd.set_option("display.float_format", "{:.3f}".format)
    pd.set_option("display.max_columns", 20)
    pd.set_option("display.width", 120)
    print(sample.to_string(index=False))
