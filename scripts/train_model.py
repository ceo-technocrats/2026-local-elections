"""
9회 지방선거 예측 모델 v2
- 타겟: 더불어민주당/국민의힘/기타 (3-way), 단체장 + 광역/기초의원비례
- 피처: 인구 구성 + 역대 대선/총선/지방선거 실적 이력
- 모델: XGBoost with sample_weight (최신·유사 선거 가중치 높음)
"""
import pandas as pd
import numpy as np
import json
import warnings
from pathlib import Path
from sklearn.model_selection import cross_val_score
import xgboost as xgb

warnings.filterwarnings("ignore")

DATA_PATH = Path("data/merged/all_merged.csv")
POP_2024  = Path("data/raw/population/population_2024.csv")
OUT_DIR   = Path("data/predictions")
OUT_DIR.mkdir(parents=True, exist_ok=True)

# ── 선거별 학습 가중치 ────────────────────────────────
ELECTION_WEIGHTS = {
    "8회지방선거_시도지사":     3.0,
    "8회지방선거_기초단체장":   3.0,
    "8회지방선거_광역의원비례": 3.0,
    "8회지방선거_기초의원비례": 3.0,
    "21대대통령선거":           2.5,
    "22대국회의원선거_지역구":  2.0,
    "20대대통령선거":           1.5,
    "21대국회의원선거_지역구":  1.0,
    "7회지방선거_시도지사":     1.0,
    "7회지방선거_기초단체장":   1.0,
    "7회지방선거_광역의원비례": 1.0,
    "7회지방선거_기초의원비례": 1.0,
    "19대대통령선거":           0.8,
}

# ── 학습 선거 목록 ────────────────────────────────────
MAIN_ELECTION_TYPES = [
    "7회지방선거_시도지사",   "8회지방선거_시도지사",
    "7회지방선거_기초단체장", "8회지방선거_기초단체장",
    "19대대통령선거", "20대대통령선거", "21대대통령선거",
    "21대국회의원선거_지역구", "22대국회의원선거_지역구",
]
COUNCIL_광역_TYPES = ["7회지방선거_광역의원비례", "8회지방선거_광역의원비례"]
COUNCIL_기초_TYPES = ["7회지방선거_기초의원비례", "8회지방선거_기초의원비례"]

# ── 피처 정의 ─────────────────────────────────────────
POP_FEATURES = [
    "ratio_20s", "ratio_30s", "ratio_40s", "ratio_50s",
    "ratio_60s", "ratio_70plus", "ratio_elderly", "ratio_working",
    "ratio_female", "total_pop",
]

TARGET_PARTIES = ["더불어민주당", "국민의힘", "기타"]

# 역대 선거 실적 (피처명 prefix)
HIST_SOURCES = [
    ("19대대통령선거",          "prev19대선"),
    ("20대대통령선거",          "prev20대선"),
    ("21대대통령선거",          "prev21대선"),
    ("22대국회의원선거_지역구", "prev22총선"),
    ("7회지방선거_시도지사",    "prev7지선"),
    ("8회지방선거_시도지사",    "prev8지선"),
]

# 광역의회 의석수 (9회 기준 — 8회와 동일 가정)
SIDO_COUNCIL_SEATS = {
    "서울특별시":     {"지역구": 96,  "비례": 16},
    "부산광역시":     {"지역구": 40,  "비례": 7},
    "대구광역시":     {"지역구": 26,  "비례": 5},
    "인천광역시":     {"지역구": 31,  "비례": 6},
    "광주광역시":     {"지역구": 19,  "비례": 3},
    "대전광역시":     {"지역구": 19,  "비례": 3},
    "울산광역시":     {"지역구": 19,  "비례": 3},
    "세종특별자치시": {"지역구": 14,  "비례": 3},
    "경기도":         {"지역구": 134, "비례": 22},
    "강원도":         {"지역구": 38,  "비례": 7},
    "충청북도":       {"지역구": 26,  "비례": 5},
    "충청남도":       {"지역구": 34,  "비례": 6},
    "전라북도":       {"지역구": 28,  "비례": 5},
    "전라남도":       {"지역구": 44,  "비례": 8},
    "경상북도":       {"지역구": 45,  "비례": 7},
    "경상남도":       {"지역구": 47,  "비례": 8},
    "제주특별자치도": {"지역구": 38,  "비례": 5},
}


# ── 인구 데이터 정규화 ────────────────────────────────
def _normalize_pop(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["sigungu_norm"] = df["sigungu"].str.replace(" ", "", regex=False)
    df.loc[df["sigungu_norm"] == "세종시", "sigungu_norm"] = "세종특별자치시"

    bucheon_mask = df["sigungu_norm"].str.startswith("부천시") & df["sido"].str.contains("경기")
    if bucheon_mask.sum() > 0:
        num_cols = df.select_dtypes(include="number").columns
        new_row = df[bucheon_mask].iloc[0].copy()
        for col in num_cols:
            new_row[col] = df[bucheon_mask][col].sum()
        new_row["sigungu"] = "부천시"
        new_row["sigungu_norm"] = "부천시"
        total = new_row.get("total_pop", 0)
        if total > 0:
            src_map = {
                "ratio_20s": "age_20_29", "ratio_30s": "age_30_39",
                "ratio_40s": "age_40_49", "ratio_50s": "age_50_59",
                "ratio_60s": "age_60_69", "ratio_70plus": None,
                "ratio_elderly": "age_65plus", "ratio_working": "age_15_64",
                "ratio_female": "female_pop",
            }
            for attr, src in src_map.items():
                if src and src in new_row:
                    new_row[attr] = new_row[src] / total
        df = pd.concat([df[~bucheon_mask], new_row.to_frame().T], ignore_index=True)

    df.loc[(df["sigungu_norm"] == "군위군") & (df["sido"] == "대구광역시"), "sido"] = "경상북도"
    return df


# ── 역대 선거 실적 피처 추출 ─────────────────────────
def extract_historical(df_all: pd.DataFrame) -> pd.DataFrame:
    result = None
    for etype, prefix in HIST_SOURCES:
        sub = df_all[df_all["election_name"] == etype]
        if len(sub) == 0:
            continue
        ratio_cols = [c for c in ["ratio_더불어민주당", "ratio_국민의힘", "ratio_기타"]
                      if c in sub.columns]
        agg = sub.groupby(["sido", "sigungu_norm"])[ratio_cols].mean().reset_index()
        rename = {
            "ratio_더불어민주당": f"{prefix}_민주",
            "ratio_국민의힘":     f"{prefix}_국힘",
            "ratio_기타":         f"{prefix}_기타",
        }
        agg = agg.rename(columns={k: v for k, v in rename.items() if k in agg.columns})

        if result is None:
            result = agg
        else:
            result = result.merge(agg, on=["sido", "sigungu_norm"], how="outer")

    return result if result is not None else pd.DataFrame(columns=["sido", "sigungu_norm"])


# ── 피처 준비 ─────────────────────────────────────────
def prepare_features(df: pd.DataFrame, election_types: list, hist_df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for etype in election_types:
        sub = df[df["election_name"] == etype].copy()
        if len(sub) == 0:
            continue

        feat_cols = [c for c in POP_FEATURES if c in sub.columns]
        sub = sub.dropna(subset=feat_cols + ["ratio_더불어민주당", "ratio_국민의힘"])
        if len(sub) == 0:
            continue

        if "ratio_기타" not in sub.columns:
            sub["ratio_기타"] = (1 - sub["ratio_더불어민주당"] - sub["ratio_국민의힘"]).clip(0, 1)

        if "total_voters" in sub.columns and "total_voted" in sub.columns:
            sub["turnout"] = sub["total_voted"] / sub["total_voters"].replace(0, np.nan)
        else:
            sub["turnout"] = np.nan

        sub["election_round"] = sub["election_name"].str.extract(r'(\d+)').astype(float)
        sub["sample_weight"]  = ELECTION_WEIGHTS.get(etype, 1.0)
        rows.append(sub)

    if not rows:
        return pd.DataFrame()

    combined = pd.concat(rows, ignore_index=True)
    if len(hist_df) > 0:
        combined = combined.merge(hist_df, on=["sido", "sigungu_norm"], how="left")
    return combined


# ── 모델 학습 ─────────────────────────────────────────
def train_predict(df: pd.DataFrame, target: str) -> dict:
    hist_cols = [c for c in df.columns if c.startswith("prev")]
    all_feat = POP_FEATURES + ["turnout", "election_round"] + hist_cols
    feat_cols = [c for c in all_feat if c in df.columns]

    X = df[feat_cols].fillna(df[feat_cols].median())
    y = df[target]
    weights = df["sample_weight"] if "sample_weight" in df.columns else pd.Series(1.0, index=df.index)

    valid = y.notna() & X.notna().all(axis=1)
    X, y, weights = X[valid], y[valid], weights[valid]

    if len(X) < 10:
        return {"mae": None, "model": None, "feat_cols": feat_cols}

    model = xgb.XGBRegressor(
        n_estimators=300, max_depth=4, learning_rate=0.05,
        subsample=0.8, colsample_bytree=0.8,
        random_state=42, verbosity=0
    )

    cv_scores = cross_val_score(model, X, y, cv=5, scoring="neg_mean_absolute_error")
    mae = -cv_scores.mean()

    model.fit(X, y, sample_weight=weights)

    importances = dict(zip(feat_cols, model.feature_importances_))
    top3 = [k for k, _ in sorted(importances.items(), key=lambda x: -x[1])[:3]]
    print(f"    [{target}] MAE={mae:.4f}  top: {top3}")

    return {"mae": mae, "model": model, "feat_cols": feat_cols}


# ── 예측 실행 ─────────────────────────────────────────
def run_predictions(models: dict, pop: pd.DataFrame, prefix: str) -> pd.DataFrame:
    pop = pop.copy()
    for party in TARGET_PARTIES:
        m = models.get(party)
        if m is None or m["model"] is None:
            pop[f"{prefix}_{party}"] = np.nan
            continue

        feat_cols = m["feat_cols"]
        X = pd.DataFrame(index=pop.index)
        for c in feat_cols:
            X[c] = pop[c] if c in pop.columns else 0.0
        X = X.fillna(X.median())

        pop[f"{prefix}_{party}"] = m["model"].predict(X).clip(0, 1)

    # 3-way 정규화
    c민주 = f"{prefix}_더불어민주당"
    c국힘  = f"{prefix}_국민의힘"
    c기타  = f"{prefix}_기타"
    if all(c in pop.columns for c in [c민주, c국힘, c기타]):
        total = pop[c민주] + pop[c국힘] + pop[c기타]
        total = total.replace(0, np.nan)
        pop[f"{prefix}_민주_norm"] = (pop[c민주] / total).clip(0, 1)
        pop[f"{prefix}_국힘_norm"]  = (pop[c국힘]  / total).clip(0, 1)
        pop[f"{prefix}_기타_norm"]  = (pop[c기타]  / total).clip(0, 1)

    return pop


# ── 광역의회 의석 추정 ────────────────────────────────
def estimate_council_seats(pred_df: pd.DataFrame) -> pd.DataFrame:
    seat_rows = []
    for sido, seats in SIDO_COUNCIL_SEATS.items():
        sido_data = pred_df[pred_df["sido"] == sido]
        if len(sido_data) == 0:
            continue

        w = sido_data["total_pop"].fillna(1).values
        row = {"sido": sido}
        for short, col in [("민주", "pred_광역_민주_norm"),
                           ("국힘",  "pred_광역_국힘_norm"),
                           ("기타",  "pred_광역_기타_norm")]:
            if col not in sido_data.columns:
                continue
            share = float(np.average(sido_data[col].fillna(0).values, weights=w))
            row[f"sido_광역_{short}_share"] = round(share, 4)
            row[f"est_광역_{short}_비례"]   = max(0, round(share * seats["비례"]))
        seat_rows.append(row)

    if seat_rows:
        pred_df = pred_df.merge(pd.DataFrame(seat_rows), on="sido", how="left")
    return pred_df


# ── 메인 ──────────────────────────────────────────────
def main():
    print("=== 9회 지방선거 예측 모델 v2 ===\n")

    df_all = pd.read_csv(DATA_PATH)
    pop_2024_raw = pd.read_csv(POP_2024)

    print(f"전체 병합 데이터: {len(df_all)}행, 선거종류: {df_all['election_name'].nunique()}개")
    print(f"선거명: {sorted(df_all['election_name'].unique())}\n")

    # 역대 선거 실적 추출
    hist_df = extract_historical(df_all)
    hist_cols = [c for c in hist_df.columns if c not in ["sido", "sigungu_norm"]]
    print(f"역대 선거 실적 피처({len(hist_cols)}개): {hist_cols}\n")

    # ── 단체장 모델 ─────────────────────────────────────
    print("── [단체장/시도지사] 모델 학습 ──")
    df_main = prepare_features(df_all, MAIN_ELECTION_TYPES, hist_df)
    print(f"학습 샘플: {len(df_main)}행\n")
    models_main = {}
    for party in TARGET_PARTIES:
        col = f"ratio_{party}"
        if col in df_main.columns:
            models_main[party] = train_predict(df_main, col)

    # ── 광역의원비례 모델 ─────────────────────────────────
    print("\n── [광역의원비례] 모델 학습 ──")
    df_광역 = prepare_features(df_all, COUNCIL_광역_TYPES, hist_df)
    print(f"학습 샘플: {len(df_광역)}행\n")
    models_광역 = {}
    for party in TARGET_PARTIES:
        col = f"ratio_{party}"
        if col in df_광역.columns:
            models_광역[party] = train_predict(df_광역, col)

    # ── 기초의원비례 모델 ─────────────────────────────────
    print("\n── [기초의원비례] 모델 학습 ──")
    df_기초 = prepare_features(df_all, COUNCIL_기초_TYPES, hist_df)
    print(f"학습 샘플: {len(df_기초)}행\n")
    models_기초 = {}
    for party in TARGET_PARTIES:
        col = f"ratio_{party}"
        if col in df_기초.columns:
            models_기초[party] = train_predict(df_기초, col)

    # ── 2026 예측 ──────────────────────────────────────
    print("\n── 2026년 9회 지방선거 예측 ──")
    pop = _normalize_pop(pop_2024_raw)
    pop["election_round"] = 9
    pop["turnout"]        = 0.62

    pop = pop.merge(hist_df, on=["sido", "sigungu_norm"], how="left")

    pop = run_predictions(models_main, pop, "pred_단체장")
    pop = run_predictions(models_광역, pop, "pred_광역")
    pop = run_predictions(models_기초, pop, "pred_기초")
    pop = estimate_council_seats(pop)

    # 예측 승자
    if "pred_단체장_민주_norm" in pop.columns and "pred_단체장_국힘_norm" in pop.columns:
        pop["pred_winner"] = np.where(
            pop["pred_단체장_민주_norm"] > pop["pred_단체장_국힘_norm"],
            "더불어민주당", "국민의힘"
        )
        pop["pred_margin"] = (pop["pred_단체장_민주_norm"] - pop["pred_단체장_국힘_norm"]).abs()

    # 저장
    base_cols = ["sido", "sigungu", "sigungu_norm", "adm_cd", "total_pop"]
    pop_feat_cols = [c for c in POP_FEATURES if c in pop.columns]
    hist_out_cols = [c for c in pop.columns if c.startswith("prev")]
    pred_cols = [c for c in pop.columns if c.startswith("pred_")]
    seat_cols = [c for c in pop.columns if c.startswith("est_") or c.startswith("sido_광역")]

    output_cols = base_cols + pop_feat_cols + hist_out_cols + pred_cols + seat_cols
    output_cols = [c for c in dict.fromkeys(output_cols) if c in pop.columns]

    pred_out = pop[output_cols].copy()
    pred_out.to_csv(OUT_DIR / "prediction_2026.csv", index=False, encoding="utf-8-sig")

    if "pred_winner" in pred_out.columns:
        summary = pred_out["pred_winner"].value_counts()
        print(f"\n[예상 승자 분포 - 단체장]")
        for party, cnt in summary.items():
            print(f"  {party}: {cnt}개 지역 ({cnt/len(pred_out)*100:.1f}%)")

    if "pred_margin" in pred_out.columns:
        close = pred_out[pred_out["pred_margin"] < 0.05].sort_values("pred_margin")
        print(f"\n[박빙 지역 (±5%p): {len(close)}곳]")
        for _, r in close.head(8).iterrows():
            민주 = r.get("pred_단체장_민주_norm", 0)
            국힘 = r.get("pred_단체장_국힘_norm", 0)
            print(f"  {r['sido']} {r.get('sigungu', r['sigungu_norm'])}: "
                  f"민주 {민주:.1%} / 국힘 {국힘:.1%} (차이 {r['pred_margin']:.1%})")

    json_data = pred_out.fillna(0).to_dict(orient="records")
    with open(OUT_DIR / "prediction_2026.json", "w", encoding="utf-8") as f:
        json.dump(json_data, f, ensure_ascii=False)

    print(f"\n예측 결과: {len(pred_out)}개 지역")
    print(f"→ 저장: {OUT_DIR}/prediction_2026.csv, prediction_2026.json")

    return pred_out


if __name__ == "__main__":
    result = main()
