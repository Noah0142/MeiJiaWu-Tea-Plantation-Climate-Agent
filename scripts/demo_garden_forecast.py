"""外部部署测试(严格协议之外的独立检验): 模型训练全程未见过 Open-Meteo 茶园序列。

场景模拟: 茶园传感器只提供最近 52 小时实况(Open-Meteo 2026-10-06~10-08),
模型据此预测未来 72h(10-09 ~ 10-11), 与 Open-Meteo 实际值对比。

注意: 模型训练于 ERA5-Land 格点, Open-Meteo 茶园数据源/海拔不同 —— 这是
"格点训练 + 茶园部署"的真实域偏移检验, 报告里同时给出原始 MAE 与去偏差 MAE。

用法: python scripts/demo_garden_forecast.py
产物: data/processed/demo_forecast.json, models/artifacts/demo_forecast.png
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import joblib
import numpy as np
import pandas as pd
import yaml

from features.build_dataset import load_static, make_station_wide
from features.features import build_features

OM_SRC = "training_data/open-meteo-30.19N120.11E180m.csv"
OM_COLS = {
    "t2m": "temperature_2m (°C)",
    "d2m": "dew_point_2m (°C)",
    "tp": "precipitation (mm)",
    "stl1": "soil_temperature_0cm (°C)",
    "stl2": "soil_temperature_6cm (°C)",
    "stl3": "soil_temperature_18cm (°C)",
    "swvl1": "soil_moisture_1_to_3cm (m³/m³)",
    "swvl2": "soil_moisture_3_to_9cm (m³/m³)",
    "obs_t2m": "temperature_2m (°C)",
    "obs_rh": "relative_humidity_2m (%)",
}


def main() -> None:
    with open("config.yaml", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    outdir = Path(cfg["model"]["output_dir"])

    om = pd.read_csv(OM_SRC, skiprows=3, parse_dates=["time"]).set_index("time").sort_index()
    print(f"[demo] Open-Meteo 茶园序列: {len(om)} 小时, {om.index.min()} ~ {om.index.max()}(北京时间)")

    bg = pd.DataFrame({std: om[raw] for std, raw in OM_COLS.items()
                       if not std.startswith("obs_") and raw in om.columns})
    lab = pd.DataFrame({std: om[raw] for std, raw in OM_COLS.items()
                        if std.startswith("obs_") and raw in om.columns})
    static = load_static(cfg["data"].get("static") or "")
    wide = make_station_wide(bg, lab, cfg, "s1", False, ["s1"], static, 0)

    with open(outdir / "climatology.json") as f:
        clim = pd.Series({int(k): v for k, v in json.load(f).items()})
    feats = build_features(wide, cfg, clim=clim)
    feat_list = json.loads((outdir / "features.json").read_text())
    models = {f"p{int(q * 100)}": joblib.load(outdir / f"lgbm_t2m_p{int(q * 100)}.joblib")
              for q in (0.10, 0.50, 0.90)}

    def forecast_from(t0: pd.Timestamp) -> pd.DataFrame:
        base = feats.loc[t0]
        rows = []
        for h in range(1, 73):
            x = base.to_dict()
            x["horizon"] = h
            X = pd.DataFrame([x]).reindex(columns=feat_list)
            rows.append({q: float(m.predict(X)[0]) for q, m in models.items()})
        fc = pd.DataFrame(rows, index=[t0 + pd.Timedelta(hours=h) for h in range(1, 73)])
        return fc

    # ---- 部署校准: 用第一段 72h 预报误差按 12h 时效分箱估计系统偏差 LUT ----
    t0_cal = pd.Timestamp("2026-10-06 23:00:00")
    w1 = forecast_from(t0_cal)
    lut = (lab["obs_t2m"].reindex(w1.index) - w1["p50"]).dropna()
    lut = lut.groupby((lut.index - t0_cal - pd.Timedelta(hours=1)).total_seconds() // 43200).mean()
    print(f"[demo] 偏差订正表(12h 分箱, ℃): {dict(zip(lut.index.astype(int), lut.round(2)))}")

    t0 = pd.Timestamp("2026-10-08 23:00:00")  # 用 10-06~10-08 共 52h 实况作为"传感器历史"
    fc = forecast_from(t0)
    fc["p50_cal"] = fc["p50"] + fc.index.to_series().apply(
        lambda t: lut.get(int((t - t0 - pd.Timedelta(hours=1)).total_seconds() // 43200), 0.0)).values
    actual = lab["obs_t2m"].reindex(fc.index)
    err, err_cal = fc["p50"] - actual, fc["p50_cal"] - actual

    # ---- 指标 ----
    print("[demo] 外部部署测试(模型从没见过 Open-Meteo 数据源):")
    for lo, hi in ((0, 24), (24, 48), (48, 72)):
        e, ec = err.iloc[lo:hi].dropna(), err_cal.iloc[lo:hi].dropna()
        print(f"  {lo:>2}-{hi:>2}h: 原始 MAE={np.mean(np.abs(e)):.2f}℃ (bias {np.mean(e):+.2f})"
              f"  -> 订正后 MAE={np.mean(np.abs(ec)):.2f}℃ (bias {np.mean(ec):+.2f})")
    e = err.dropna()
    print(f"  总计: 原始 MAE={np.mean(np.abs(e)):.2f}℃ -> 订正后 MAE={np.mean(np.abs(err_cal.dropna())):.2f}℃")
    daily = pd.DataFrame({"pred": fc["p50_cal"].resample("1D").min(),
                          "obs": actual.resample("1D").min()}).dropna()
    for b in (1.0, 2.0):
        acc = float(np.mean(np.abs(daily["pred"] - daily["obs"]) <= b))
        print(f"  日最低温准确率(订正后, ±{b:.0f}℃, {len(daily)} 天): {acc:.0%}")

    # ---- 产物 ----
    Path("data/processed").mkdir(parents=True, exist_ok=True)
    fc_out = fc.reset_index().to_json(orient="records")
    with open("data/processed/demo_forecast.json", "w", encoding="utf-8") as f:
        json.dump({"issued_at": str(t0), "hourly": json.loads(fc_out),
                   "actual_source": OM_SRC, "bias_lut": {str(k): round(float(v), 2) for k, v in lut.items()}},
                  f, ensure_ascii=False, indent=2)

    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        fig, ax = plt.subplots(figsize=(10, 5))
        ax.plot(fc.index, fc["p50"], "r-", lw=2, label="Model P50")
        ax.plot(fc.index, fc["p50_cal"], "b-", lw=2, label="Model P50 (bias-corrected)")
        ax.fill_between(fc.index, fc["p10"], fc["p90"], color="r", alpha=0.15, label="P10-P90")
        ax.plot(actual.index, actual, "k--", lw=1.5, label="Open-Meteo actual")
        ax.axvline(t0, color="gray", ls=":", label=f"Issued at {t0}")
        ax.set_title("Meijiawu tea garden 72h microclimate forecast - external deployment test")
        ax.set_ylabel("Temperature (C)"); ax.legend(); ax.grid(alpha=0.3)
        plt.tight_layout()
        plt.savefig(outdir / "demo_forecast.png", dpi=130)
        plt.close()
        print(f"[demo] 图已存 {outdir / 'demo_forecast.png'}")
    except Exception as ex:  # noqa: BLE001
        print(f"[demo] 绘图跳过: {ex}")


if __name__ == "__main__":
    main()
