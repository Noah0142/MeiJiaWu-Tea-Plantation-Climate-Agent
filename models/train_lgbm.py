"""训练: LightGBM 分位数回归(P10/P50/P90)/ 随机森林(RF 快速基线)。

建模范式(对标绍兴御茶村"粗网格 + 实况 -> AI 误差订正"):
- target_mode: "error"(默认)= 学 (实况 - 格点背景值) 的残差; 最终预报 = 格点值 + 残差。
  残差映射在站点间更可迁移, 是"锚点传感器 + 迁移学习"的基础。
- target_mode: "direct" = 直接学实况值。

迁移学习: --finetune-station S 用已训好的全站点模型做 init_model,
在站点 S 的训练数据上继续训练(对应"跨站点预训练 + 本地微调")。

用法:
  python models/train_lgbm.py --config config.yaml                 # 全量训练
  python models/train_lgbm.py --config config.yaml --algo rf        # RF 快速基线
  python models/train_lgbm.py --config config.yaml --finetune-station s1
产物(models/artifacts/): lgbm_t2m_p{10,50,90}.joblib / rf_t2m_p50.joblib /
  lgbm_t2m_p50_ft_{S}.joblib / features.json / train_report.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import joblib
import numpy as np
import pandas as pd
import yaml
import lightgbm as lgb
from lightgbm import LGBMRegressor
from sklearn.ensemble import RandomForestRegressor

ID_COLS = {"time", "split", "t_plus_h", "station"}  # horizon 保留为特征: 多时效模型必须知道预测时效


def load_dataset(cfg: dict) -> tuple[pd.DataFrame, list[str], list[str]]:
    ds = pd.read_parquet(cfg["data"]["processed"])
    targets = [c for c in ds.columns if c.startswith("y_")]
    feat_cols = [c for c in ds.columns if c not in ID_COLS and c not in targets]
    return ds, feat_cols, targets


def make_target(ds: pd.DataFrame, cfg: dict) -> pd.Series:
    mode = cfg["model"].get("target_mode", "error")
    if mode == "error" and "bg_t2m_plus_h" in ds.columns:
        return ds["y_t2m"] - ds["bg_t2m_plus_h"]
    return ds["y_t2m"]


def quick_mae(model, X, y) -> float:
    return float(np.mean(np.abs(model.predict(X) - y)))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--algo", choices=["lgbm", "rf"], default="lgbm")
    ap.add_argument("--finetune-station", default=None, help="站点 ID, 在预训练模型上微调")
    ap.add_argument("--init-dir", default=None, help="预训练产物目录(默认与 output_dir 相同)")
    args = ap.parse_args()

    with open(args.config, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    params = cfg["model"]["lgbm"]
    outdir = Path(cfg["model"]["output_dir"])
    outdir.mkdir(parents=True, exist_ok=True)
    mode = cfg["model"].get("target_mode", "error")

    ds, feat_cols, targets = load_dataset(cfg)
    train = ds[ds["split"] == "train"].copy()
    test = ds[ds["split"] == "test"].copy()
    val = ds[ds["split"] == "val"].copy() if "val" in set(ds["split"]) else None
    has_val = val is not None and len(val) > 0

    suffix = ""
    init_models = {}
    if args.finetune_station:
        st = args.finetune_station
        if "station" not in ds.columns or st not in set(ds["station"]):
            raise SystemExit(f"[train] 数据集里没有站点 {st}, 可用: {sorted(set(ds['station']))}")
        init_dir = Path(args.init_dir) if args.init_dir else outdir
        init_models = {q: joblib.load(init_dir / f"lgbm_t2m_p{int(q * 100)}.joblib") for q in (0.10, 0.50, 0.90)}
        train = train[train["station"] == st]
        test = test[test["station"] == st]
        suffix = f"_ft_{st}"
        print(f"[train] 微调站点 {st}: 训练 {len(train)} 行 / 验证 {len(test)} 行(init_model=全站点预训练)")

    y_train = make_target(train, cfg)
    y_test = make_target(test, cfg)
    print(f"[train] target_mode={mode}, 特征 {len(feat_cols)} 个")

    report = {"features": feat_cols, "targets": targets, "target_mode": mode,
              "finetune_station": args.finetune_station, "per_horizon": {}}

    if args.algo == "rf":
        mdl = RandomForestRegressor(n_estimators=200, min_samples_leaf=5, n_jobs=-1, random_state=42)
        mdl.fit(train[feat_cols], y_train)
        joblib.dump(mdl, outdir / f"rf_t2m_p50{suffix}.joblib")
        print(f"[train] RF 验证 MAE(残差): {quick_mae(mdl, test[feat_cols], y_test):.3f}℃")
    else:
        for alpha in (0.10, 0.50, 0.90):
            mdl = LGBMRegressor(objective="quantile", alpha=alpha, random_state=42, **params)
            fit_kw = {}
            if args.finetune_station:
                fit_kw["init_model"] = init_models[alpha].booster_
            elif has_val:
                # 严格协议: 早停只允许看验证集, 测试集在训练全程不可见
                fit_kw["eval_set"] = [(val[feat_cols], make_target(val, cfg))]
                fit_kw["eval_metric"] = "mae"
                fit_kw["callbacks"] = [lgb.early_stopping(50, verbose=False)]
            mdl.fit(train[feat_cols], y_train, **fit_kw)
            joblib.dump(mdl, outdir / f"lgbm_t2m_p{int(alpha * 100)}{suffix}.joblib")
            print(f"[train] 已保存 lgbm_t2m_p{int(alpha * 100)}{suffix}.joblib"
                  + (f" (best_iter={mdl.best_iteration_})" if hasattr(mdl, "best_iteration_") else ""))

        if "y_rh" in train.columns and not args.finetune_station:
            mask = train["y_rh"].notna()
            mdl_rh = LGBMRegressor(random_state=42, **params)
            mdl_rh.fit(train.loc[mask, feat_cols], train.loc[mask, "y_rh"])
            joblib.dump(mdl_rh, outdir / "lgbm_rh_p50.joblib")
            print("[train] 已保存 lgbm_rh_p50.joblib")

    # ---- 快速验证(分时效, 残差口径)。严格协议: 有验证集时只看验证集, 测试集不参与 ----
    p50 = joblib.load(outdir / f"lgbm_t2m_p50{suffix}.joblib") if args.algo == "lgbm" \
        else joblib.load(outdir / f"rf_t2m_p50{suffix}.joblib")
    quick = val if has_val else test
    quick = quick.assign(pred_res=p50.predict(quick[feat_cols]))
    per_h = {}
    for h, g in quick.groupby("horizon"):
        per_h[int(h)] = round(float(np.mean(np.abs(g["pred_res"] - make_target(g, cfg)))), 3)
    print(f"[train] {'验证' if has_val else '测试'}集分时效 MAE(残差, ℃):", per_h)

    if args.algo == "lgbm":
        imp = pd.Series(p50.feature_importances_, index=feat_cols).sort_values(ascending=False)
        print("[train] 特征重要度 Top 10:", dict(imp.head(10).round(0)))
        report["importance_top30"] = {k: float(v) for k, v in imp.head(30).items()}

    with open(outdir / "features.json", "w") as f:
        json.dump(feat_cols, f)
    report["per_horizon"] = per_h
    with open(outdir / "train_report.json", "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"[train] 完成, 产物在 {outdir}")


if __name__ == "__main__":
    main()
