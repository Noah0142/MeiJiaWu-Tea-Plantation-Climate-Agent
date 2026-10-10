"""评估: 分时效回归指标 + 最低/最高气温预报准确率(对标御茶村 52%->64%)+
霜冻/高温事件预警指标(POD/FAR/CSI)+ 与基线对比。

用法:
  python models/evaluate.py --config config.yaml
  python models/evaluate.py --config config.yaml --model-suffix _ft_s1   # 评估微调模型
产物(models/artifacts/): metrics.csv / metrics_summary.json /
  tmin_accuracy.csv / metrics_mae_by_horizon.png
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

ID_COLS = {"time", "horizon", "split", "t_plus_h", "station"}


def _err(y, pred):
    err = pred - y
    return float(np.mean(np.abs(err))), float(np.sqrt(np.mean(err ** 2))), float(np.mean(err))


def _event_stats(obs_event: np.ndarray, warn: np.ndarray) -> dict:
    tp = int(np.sum(obs_event & warn))
    fp = int(np.sum(~obs_event & warn))
    fn = int(np.sum(obs_event & ~warn))
    return {"n_events": int(np.sum(obs_event)), "n_warnings": int(np.sum(warn)),
            "pod": round(tp / max(tp + fn, 1), 3),
            "far": round(fp / max(tp + fp, 1), 3),
            "csi": round(tp / max(tp + fp + fn, 1), 3)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--model-suffix", default="", help="如 _ft_s1 评估微调模型")
    ap.add_argument("--split", choices=["val", "test"], default="test",
                    help="评估哪个留出集(严格协议: 调参期用 val, 最终报告只跑一次 test)")
    args = ap.parse_args()

    with open(args.config, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    mode = cfg["model"].get("target_mode", "error")
    suffix = args.model_suffix
    outdir = Path(cfg["model"]["output_dir"])
    r = cfg["risk"]

    ds = pd.read_parquet(cfg["data"]["processed"])
    test = ds[ds["split"] == args.split].copy()
    # 微调模型只在对应站点上评估
    if suffix.startswith("_ft_") and "station" in test.columns:
        st = suffix.replace("_ft_", "")
        test = test[test["station"] == st]
        print(f"[eval] 仅评估站点 {st}(微调模型)")
    feat_cols = json.loads((outdir / "features.json").read_text())
    X = test[feat_cols]

    p50_path = outdir / ("rf_t2m_p50" + suffix + ".joblib")
    use_rf = p50_path.exists()
    if use_rf:
        models = {"p50": joblib.load(p50_path)}
    else:
        models = {f"p{int(q * 100)}": joblib.load(outdir / f"lgbm_t2m_p{int(q * 100)}{suffix}.joblib")
                  for q in (0.10, 0.50, 0.90)}
    has_grid = "bg_t2m_plus_h" in test.columns
    grid = test["bg_t2m_plus_h"].to_numpy() if has_grid else None

    def final(pred: np.ndarray) -> np.ndarray:
        return grid + pred if (mode == "error" and has_grid) else pred

    for q, mdl in models.items():
        test[f"pred_{q}"] = final(mdl.predict(X))
    print(f"[eval] model={'rf' if use_rf else 'lgbm'} target_mode={mode} split={args.split} suffix='{suffix}'")

    # ---- 1. 回归指标(实况口径): 模型 vs 基线 ----
    rows = []
    for h, g in test.groupby("horizon"):
        for q, mdl in models.items():
            mae, rmse, bias = _err(g["y_t2m"], g[f"pred_{q}"])
            rows.append({"horizon": int(h), "model": f"{'rf' if use_rf else 'lgbm'}_{q}",
                         "mae": round(mae, 3), "rmse": round(rmse, 3), "bias": round(bias, 3)})
    metrics = pd.DataFrame(rows)
    base_csv = outdir / "baseline_metrics.csv"
    if base_csv.exists():
        bm = pd.read_csv(base_csv).rename(columns={"baseline": "model"})[
            ["horizon", "model", "mae", "rmse", "bias"]]
        metrics = pd.concat([metrics, bm], ignore_index=True)
    metrics.to_csv(outdir / f"metrics{suffix}.csv", index=False)

    model_col = f"{'rf' if use_rf else 'lgbm'}_p50"
    m50 = metrics[metrics["model"] == model_col].set_index("horizon")["mae"]
    persist = metrics[metrics["model"] == "persist"].set_index("horizon")["mae"]
    print("[eval] 分时效 MAE(℃, 实况口径):")
    print(metrics.pivot(index="horizon", columns="model", values="mae").round(3))
    print("[eval] 相对持续预报 skill:", dict((1 - m50 / persist).round(3)))

    # ---- 2. 最低/最高气温预报准确率(对标御茶村 52%->64%) ----
    acc_rows = []
    for h in (24, 48, 72):
        g = test[test["horizon"] == h]
        daily = g.groupby(g["t_plus_h"].dt.date).agg(
            obs_tmin=("y_t2m", "min"), pred_tmin=("pred_p50", "min"),
            obs_tmax=("y_t2m", "max"), pred_tmax=("pred_p50", "max"))
        for bound in (1.0, 2.0):
            acc_rows.append({"horizon": h, "variable": "tmin", "bound_c": bound,
                             "accuracy": round(float(np.mean(np.abs(daily["pred_tmin"] - daily["obs_tmin"]) <= bound)), 3),
                             "n_days": len(daily)})
            acc_rows.append({"horizon": h, "variable": "tmax", "bound_c": bound,
                             "accuracy": round(float(np.mean(np.abs(daily["pred_tmax"] - daily["obs_tmax"]) <= bound)), 3),
                             "n_days": len(daily)})
    acc = pd.DataFrame(acc_rows)
    acc.to_csv(outdir / f"tmin_accuracy{suffix}.csv", index=False)
    tmin24 = acc[(acc["horizon"] == 24) & (acc["variable"] == "tmin")]
    print("[eval] 24h 最低气温预报准确率(±1℃ / ±2℃):",
          tmin24.set_index("bound_c")["accuracy"].to_dict(),
          "(御茶村案例: 52% -> 64%)")

    # ---- 3. 日尺度事件预警: 霜冻 / 高温 ----
    daily = test.groupby(test["t_plus_h"].dt.date).agg(
        obs_tmin=("y_t2m", "min"), obs_tmax=("y_t2m", "max"),
        pred_tmin_p50=("pred_p50", "min"),
        pred_tmax=("pred_p50", "max"),
        **({"pred_tmin_p10": ("pred_p10", "min")} if "p10" in models else {}))
    daily.index = pd.to_datetime(daily.index)
    frost_t, heat_tmax = float(r["frost_tmin"]), float(r["heat_tmax"])

    frost_event = (daily["obs_tmin"] <= frost_t).to_numpy()
    heat_event = (daily["obs_tmax"] >= heat_tmax).to_numpy()
    frost_stats = {"standard(P50 阈值)": _event_stats(
        frost_event, (daily["pred_tmin_p50"] <= frost_t).to_numpy())}
    if "p10" in models:
        frost_stats["conservative(P10 阈值)"] = _event_stats(
            frost_event, (daily["pred_tmin_p10"] <= frost_t).to_numpy())
    heat_stats = _event_stats(heat_event, (daily["pred_tmax"] >= heat_tmax).to_numpy())

    spring = daily[(daily.index.month >= 2) & (daily.index.month <= 4)]
    if len(spring):
        fe = (spring["obs_tmin"] <= frost_t).to_numpy()
        frost_stats["春季窗口(2-4月)"] = _event_stats(fe, (spring["pred_tmin_p50"] <= frost_t).to_numpy())

    print("[eval] 霜冻事件预警:", json.dumps(frost_stats, ensure_ascii=False))
    print("[eval] 高温事件预警:", json.dumps(heat_stats, ensure_ascii=False))

    summary = {
        "model": model_col, "target_mode": mode,
        "overall_mae_p50": round(float(m50.mean()), 3),
        "overall_mae_persist": round(float(persist.mean()), 3),
        "skill_vs_persist": round(float((1 - m50 / persist).mean()), 3),
        "tmin24_accuracy_pm2c": float(acc[(acc["horizon"] == 24) & (acc["variable"] == "tmin") & (acc["bound_c"] == 2.0)]["accuracy"].iloc[0]),
        "frost": frost_stats, "heat": heat_stats,
    }
    if "p10" in models:
        summary["interval_coverage_p10_p90"] = round(
            float(np.mean((test["y_t2m"] >= test["pred_p10"]) & (test["y_t2m"] <= test["pred_p90"]))), 3)
    with open(outdir / f"metrics_summary{suffix}.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    # ---- 4. 图 ----
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        ax = metrics[metrics["model"].isin([model_col, "persist", "direct"])].pivot(
            index="horizon", columns="model", values="mae").plot(marker="o")
        ax.set_ylabel("MAE (℃)"); ax.set_xlabel("时效 (h)")
        ax.set_title("梅家坞茶园 0–72h 气温预报 MAE")
        ax.grid(alpha=0.3)
        plt.tight_layout()
        plt.savefig(outdir / f"metrics_mae_by_horizon{suffix}.png", dpi=150)
        plt.close()
    except Exception as e:  # noqa: BLE001
        print(f"[eval] 绘图跳过: {e}")

    print(f"[eval] 完成, 产物在 {outdir}")


if __name__ == "__main__":
    main()
