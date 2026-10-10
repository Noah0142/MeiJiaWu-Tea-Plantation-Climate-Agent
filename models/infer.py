"""运行时推理: 数值预报 CSV + 近期实况 CSV -> 茶园 0–72h 微气候预报 JSON。

输入:
  --forecast 预报文件(背景场列名映射 + time, 支持 t2m_cN 多格点):
             需含 t0 时刻分析行(或 t0 前 3h 内的行)与未来 1..hours 行;
             含过去若干小时行时可用于滚动偏差订正。
  --obs      实况文件(labels 列名映射 + time, 支持 obs_t2m_sN 多站):
             至少覆盖 t0 前 48h(更少也能跑, 滞后特征会缺失)。
输出 JSON: site / issued_at / bias_correction_c / hourly[t2m_p10,p50,p90,rh] /
  risk(霜冻/热害/倒春寒分级卡片, 见 models/risk.py)

用法: python models/infer.py --config config.yaml --forecast data/raw/forecast_latest.csv \
        --obs data/raw/labels.csv --out data/processed/forecast_out.json
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

from features.build_dataset import detect_stations, load_static, load_table, make_station_wide
from features.features import bg_cell_tables, build_features, plus_h_features
from models.risk import risk_card


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--forecast", required=True)
    ap.add_argument("--obs", required=True)
    ap.add_argument("--out", default="data/processed/forecast_out.json")
    ap.add_argument("--hours", type=int, default=72)
    ap.add_argument("--station", default=None, help="目标站(默认取实况文件的第一个站)")
    ap.add_argument("--format", choices=["standard", "sensor-network"], default="standard",
                    help="sensor-network = 输出与 microclimate-sensor-network 前端一致的 schema")
    args = ap.parse_args()

    with open(args.config, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    colmap = cfg["columns"]
    outdir = Path(cfg["model"]["output_dir"])
    mode = cfg["model"].get("target_mode", "error")
    neighbors_k = int(cfg["model"].get("neighbors_k", 0))

    bg_f = load_table(args.forecast, colmap["background"], colmap["time"])
    obs = load_table(args.obs, colmap["labels"], colmap["time"])
    static = load_static(cfg["data"].get("static") or "")
    stations, is_suffixed = detect_stations(obs)
    station = args.station or (stations[0] if stations else "s1")
    t0 = obs.index[-1]
    if bg_f.empty or bg_f.index.max() < t0:
        raise SystemExit(f"[infer] 预报文件未覆盖 t0={t0}(最后实况时刻)。")

    # ---- 滚动偏差订正: 近 48h(实况 - 背景场)均值 -> 订正所有格点未来值 ----
    bg = bg_f.reindex(pd.date_range(obs.index.min(), max(bg_f.index.max(), obs.index.max()), freq="1h"))
    overlap = pd.concat([obs[f"obs_t2m" if not is_suffixed else f"obs_t2m_{station}"], bg["t2m"]],
                        axis=1, keys=["o", "b"]).dropna()
    bias = 0.0
    if not overlap.empty:
        recent = overlap.loc[overlap.index >= t0 - pd.Timedelta(hours=48)]
        bias = float((recent["o"] - recent["b"]).mean())
    bg = bg.copy()
    future_mask = bg.index > t0
    for c in [c for c in bg.columns if c.startswith(("t2m", "d2m"))]:
        bg.loc[future_mask, c] = bg.loc[future_mask, c] + bias
    print(f"[infer] t0={t0}, 站点={station}, 滚动偏差订正 {bias:+.2f}℃(近 48h 实况-背景场)")

    # ---- 特征(与训练同源: make_station_wide + build_features) ----
    wide = make_station_wide(bg, obs, cfg, station, is_suffixed, stations, static, neighbors_k)
    with open(outdir / "climatology.json") as f:
        clim = pd.Series({int(k): v for k, v in json.load(f).items()})
    feats = build_features(wide, cfg, clim=clim)
    if t0 not in feats.index:
        raise SystemExit("[infer] t0 时刻特征缺失(实况或背景场不完整)。")
    base = feats.loc[t0]

    feat_list = json.loads((outdir / "features.json").read_text())
    bgd = bg_cell_tables(bg)

    p50_path = outdir / "rf_t2m_p50.joblib"
    if p50_path.exists():
        models = {"p50": joblib.load(p50_path)}
    else:
        models = {f"p{int(q * 100)}": joblib.load(outdir / f"lgbm_t2m_p{int(q * 100)}.joblib")
                  for q in (0.10, 0.50, 0.90)}
    rh_mdl = joblib.load(outdir / "lgbm_rh_p50.joblib") if (outdir / "lgbm_rh_p50.joblib").exists() else None

    # ---- 逐时效预测 ----
    base_t = pd.DatetimeIndex([t0])
    rows, xs = [], []
    for h in range(1, args.hours + 1):
        ph = plus_h_features(bgd, base_t, h)
        x = base.to_dict()
        x["horizon"] = h  # 多时效模型: 时效是特征
        for c in ph.columns:
            x[c] = float(ph[c].iloc[0])
        X = pd.DataFrame([x]).reindex(columns=feat_list)
        pred = {q: float(mdl.predict(X)[0]) for q, mdl in models.items()}
        grid = float(x.get("bg_t2m_plus_h", np.nan))
        if mode == "error" and np.isfinite(grid):
            pred = {q: grid + v for q, v in pred.items()}
        row = {"time": str(t0 + pd.Timedelta(hours=h)),
               "t2m_p50": round(pred.get("p50", np.nan), 1)}
        if "p10" in pred:
            row["t2m_p10"], row["t2m_p90"] = round(pred["p10"], 1), round(pred["p90"], 1)
        if rh_mdl is not None:
            row["rh"] = round(float(np.clip(rh_mdl.predict(X)[0], 0, 100)), 1)
        rows.append(row)
        xs.append(x)

    if args.format == "sensor-network":
        # 对齐 microclimate-sensor-network 前端的 48h 预报 schema:
        # [{ts(epoch秒), temperature, humidity, wind_speed, gust_speed, soil_moisture}]
        sn = []
        for r, x in zip(rows, xs):
            ts = int(pd.Timestamp(r["time"]).timestamp())
            sn.append({
                "ts": ts,
                "temperature": r["t2m_p50"],
                "humidity": r.get("rh", round(float(x.get("bg_rh_plus_h", np.nan)), 1)),
                "wind_speed": round(float(x.get("bg_ws_plus_h", np.nan)), 2),
                "gust_speed": None,
                "soil_moisture": None,
            })
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(sn, f, ensure_ascii=False, indent=2)
        print(f"[infer] 已输出 sensor-network 格式 {args.out}({len(sn)} 小时)")
        return

    fc = pd.DataFrame(rows)
    fc["time"] = pd.to_datetime(fc["time"])
    fc = fc.set_index("time")

    out = {
        "site": cfg["site"],
        "issued_at": str(t0),
        "target_station": station,
        "bias_correction_c": round(bias, 2),
        "hourly": json.loads(fc.reset_index().to_json(orient="records")),
        "risk": risk_card(fc, cfg),
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"[infer] 已输出 {args.out}")
    print(json.dumps(out["risk"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
