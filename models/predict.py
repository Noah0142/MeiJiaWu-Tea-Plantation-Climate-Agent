"""模型调用: 近期传感器/线上数据历史 -> 0-72h 茶园微气候预报。

CLI 用法:
  python models/predict.py --obs data/raw/labels.csv --hours 72 --out data/processed/pred.json
  python models/predict.py --source open-meteo --obs training_data/open-meteo-30.19N120.11E180m.csv
  python models/predict.py --source open-meteo --obs xxx.csv --lut data/processed/bias_lut.json
  python models/predict.py --source open-meteo --obs xxx.csv --format sensor-network

Python 复用(Web 服务/Agent 后端):
  from models.predict import load_predictor, run_forecast, read_inputs
  predictor = load_predictor(cfg)
  bg, lab = read_inputs(cfg, csv_path, "open-meteo")
  fc, t0 = run_forecast(cfg, predictor, bg, lab, hours=72, lut=lut)
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

from features.build_dataset import load_static, make_station_wide
from features.features import build_features
from models.risk import risk_card

OM_COLS = {
    "t2m": "temperature_2m (°C)",
    "d2m": "dew_point_2m (°C)",
    "tp": "precipitation (mm)",
    "stl1": "soil_temperature_0cm (°C)",
    "stl2": "soil_temperature_6cm (°C)",
    "stl3": "soil_temperature_18cm (°C)",
    "swvl1": "soil_moisture_1_to_3cm (m³/m³)",
    "swvl2": "soil_moisture_3_to_9cm (m³/m³)",
    "ap_temp": "apparent_temperature (°C)",
    "et0": "evapotranspiration (mm)",
    "obs_t2m": "temperature_2m (°C)",
    "obs_rh": "relative_humidity_2m (%)",
}


def read_inputs(cfg: dict, src: str, source: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """读输入 CSV -> (背景场表 bg, 实况表 lab), 均为标准列名 + DatetimeIndex。"""
    if source == "open-meteo":
        df = pd.read_csv(src, skiprows=3, parse_dates=["time"]).set_index("time").sort_index()
        bg = pd.DataFrame({std: df[raw] for std, raw in OM_COLS.items()
                           if not std.startswith("obs_") and raw in df.columns})
        lab = pd.DataFrame({std: df[raw] for std, raw in OM_COLS.items()
                            if std.startswith("obs_") and raw in df.columns})
        return bg, lab

    df = pd.read_csv(src)
    df[cfg["columns"]["time"]] = pd.to_datetime(df[cfg["columns"]["time"]], errors="coerce")
    df = df.dropna(subset=[cfg["columns"]["time"]]).set_index(cfg["columns"]["time"]).sort_index()
    bmap, lmap = cfg["columns"]["background"], cfg["columns"]["labels"]
    bg = pd.DataFrame({std: pd.to_numeric(df[raw], errors="coerce").to_numpy()
                       for std, raw in bmap.items() if raw in df.columns}, index=df.index)
    lab = pd.DataFrame({std: pd.to_numeric(df[raw], errors="coerce").to_numpy()
                        for std, raw in lmap.items() if raw in df.columns}, index=df.index)
    return bg, lab


def load_predictor(cfg: dict) -> dict:
    """加载模型产物(气候态/特征清单/分位数模型/湿度模型/静态表)。"""
    outdir = Path(cfg["model"]["output_dir"])
    clim = pd.Series({int(k): float(v) for k, v in json.load(open(outdir / "climatology.json")).items()})
    feat_list = json.loads((outdir / "features.json").read_text())
    models = {f"p{int(q * 100)}": joblib.load(outdir / f"lgbm_t2m_p{int(q * 100)}.joblib")
              for q in (0.10, 0.50, 0.90)}
    rh_mdl = joblib.load(outdir / "lgbm_rh_p50.joblib") if (outdir / "lgbm_rh_p50.joblib").exists() else None
    static = load_static(cfg["data"].get("static") or "")
    return {"clim": clim, "feat_list": feat_list, "models": models,
            "rh_mdl": rh_mdl, "static": static}


def run_forecast(cfg: dict, predictor: dict, bg: pd.DataFrame, lab: pd.DataFrame,
                 hours: int = 72, lut: dict | None = None, t0: pd.Timestamp | None = None
                 ) -> tuple[pd.DataFrame, pd.Timestamp]:
    """构造特征并在 t0 起报 1..hours 小时。返回 (预报表, 起报时刻)。"""
    if bg.empty:
        bg = pd.DataFrame({"t2m": np.nan}, index=lab.index)
    wide = make_station_wide(bg, lab, cfg, "s1", False, ["s1"], predictor["static"], 0)
    feats = build_features(wide, cfg, clim=predictor["clim"])
    t0 = t0 or lab.index[-1]
    if t0 not in feats.index:
        raise SystemExit(f"[predict] t0={t0} 特征缺失, 请确认历史长度(建议 ≥48h)。")
    base = feats.loc[t0]
    feat_list = predictor["feat_list"]
    models = predictor["models"]

    rows = []
    for h in range(1, hours + 1):
        x = base.to_dict()
        x["horizon"] = h
        X = pd.DataFrame([x]).reindex(columns=feat_list)
        pred = {q: float(m.predict(X)[0]) for q, m in models.items()}
        corr = float(lut.get(str((h - 1) // 12), 0.0)) if lut else 0.0
        row = {"time": t0 + pd.Timedelta(hours=h),
               "t2m_p50": round(pred["p50"] + corr, 1)}
        if "p10" in pred:
            row["t2m_p10"], row["t2m_p90"] = round(pred["p10"] + corr, 1), round(pred["p90"] + corr, 1)
        if predictor["rh_mdl"] is not None:
            row["rh"] = round(float(np.clip(predictor["rh_mdl"].predict(X)[0], 0, 100)), 1)
        rows.append(row)
    fc = pd.DataFrame(rows).set_index("time")
    return fc, t0


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--obs", required=True, help="近期逐小时历史 CSV(至少 48h)")
    ap.add_argument("--source", choices=["standard", "open-meteo"], default="standard")
    ap.add_argument("--hours", type=int, default=72)
    ap.add_argument("--out", default="data/processed/pred.json")
    ap.add_argument("--lut", default=None, help="偏差订正表 JSON(12h 分箱键 -> ℃)")
    ap.add_argument("--format", choices=["standard", "sensor-network"], default="standard")
    args = ap.parse_args()

    with open(args.config, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    bg, lab = read_inputs(cfg, args.obs, args.source)
    if lab.empty or "obs_t2m" not in lab.columns:
        raise SystemExit("[predict] 输入中缺少 obs_t2m(实况气温), 请检查 --source 与列名。")
    missing_bg = [c for c in ("t2m", "d2m", "tp", "ssr", "skt", "stl1", "swvl1") if c not in bg.columns]
    if missing_bg:
        print(f"[predict] 注意: 输入缺少背景列 {missing_bg}, 对应特征为 NaN(可用但会降精度)")

    lut = json.load(open(args.lut, encoding="utf-8")) if args.lut else None
    fc, t0 = run_forecast(cfg, load_predictor(cfg), bg, lab, hours=args.hours, lut=lut)
    print(f"[predict] 预报起点 t0={t0}, 历史 {len(lab)} 小时, 预报 {args.hours} 小时")

    if args.format == "sensor-network":
        sn = [{"ts": int(t.timestamp()), "temperature": r["t2m_p50"], "humidity": r.get("rh"),
               "wind_speed": None, "gust_speed": None, "soil_moisture": None}
              for t, r in fc.iterrows()]
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(sn, f, ensure_ascii=False, indent=2)
        print(f"[predict] 已输出 sensor-network 格式: {args.out}")
        return

    out = {"site": cfg["site"], "issued_at": str(t0), "bias_lut_applied": bool(lut),
           "hourly": json.loads(fc.reset_index().to_json(orient="records", date_format="iso")),
           "risk": risk_card(fc, cfg)}
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"[predict] 已输出 {args.out}")
    print(json.dumps(out["risk"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
