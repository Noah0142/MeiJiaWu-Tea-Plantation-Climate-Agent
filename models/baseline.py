"""L0 基线(必须被打败的地板):
- persist  持续预报: y(t+h) = 实况(t)
- lapse    持续 + 海拔递减率订正: y = 实况(t) + Δ海拔 × 递减率
- direct   背景场直用: y = 背景场(t+h)(即"完美预报"下不做任何订正)

用法: python models/baseline.py --config config.yaml
产物: models/artifacts/baseline_metrics.csv
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
import pandas as pd
import yaml


def _metrics(y: np.ndarray, pred: np.ndarray) -> dict:
    err = pred - y
    return {
        "mae": float(np.nanmean(np.abs(err))),
        "rmse": float(np.sqrt(np.nanmean(err ** 2))),
        "bias": float(np.nanmean(err)),
        "n": int(np.sum(~np.isnan(err))),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--split", choices=["val", "test"], default="test")
    args = ap.parse_args()

    with open(args.config, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    ds = pd.read_parquet(cfg["data"]["processed"])
    test = ds[ds["split"] == args.split].copy()
    lapse = float(cfg["model"]["lapse_rate_c_per_100m"]) / 100.0  # ℃/m

    rows = []
    for h, g in test.groupby("horizon"):
        y = g["y_t2m"].to_numpy()
        for name, pred in (
            ("persist", g["obs_t2m"].to_numpy()),
            ("lapse", g["obs_t2m"].to_numpy() + g["elev_delta"].to_numpy() * lapse),
        ):
            m = _metrics(y, pred)
            m.update({"horizon": int(h), "baseline": name})
            rows.append(m)
        if "bg_t2m_plus_h" in g.columns:  # 仅当注入背景场 t+h(误差订正模式)时可用
            m = _metrics(y, g["bg_t2m_plus_h"].to_numpy())
            m.update({"horizon": int(h), "baseline": "direct"})
            rows.append(m)

    out = pd.DataFrame(rows)
    outdir = Path(cfg["model"]["output_dir"])
    outdir.mkdir(parents=True, exist_ok=True)
    out.to_csv(outdir / "baseline_metrics.csv", index=False)
    print("[baseline] 各基线分时效 MAE(℃):")
    print(out.pivot(index="horizon", columns="baseline", values="mae").round(3))
    print(f"[baseline] 已保存 {outdir / 'baseline_metrics.csv'}")


if __name__ == "__main__":
    main()
