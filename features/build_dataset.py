"""数据集构建: 原始 CSV -> 训练/验证样本表。

支持:
- 多格点背景场(列名 t2m_c2..cN 为周边格点, 无后缀为最近格点)
- 多站实况(obs_t2m_s1 / obs_t2m_s2 ...; 单站可直接用 obs_t2m)
- static.csv 点位属性(多站时给每个站点高程/坡度等)

用法:
  python features/build_dataset.py --config config.yaml

产物:
  data/processed/dataset.parquet   样本表(time/horizon/split/t_plus_h/station)
  models/artifacts/climatology.json
  models/artifacts/build_report.json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
import pandas as pd
import yaml

from features.features import bg_cell_tables, build_features, compute_climatology, plus_h_features

STATION_RE = re.compile(r"^obs_t2m_(\w+)$")


def load_table(path: str, mapping: dict, time_col: str) -> pd.DataFrame:
    """按列名映射读取 CSV, 解析时间并重采样到整点。

    - 映射里的列按标准名读取; 其余以「已映射列名 + _后缀」出现的列
      (如 t2m_c2、obs_t2m_s2)自动透传 —— 这就是多格点/多站的支持方式。
    - 用 .to_numpy() 赋值, 避免 RangeIndex 与 DatetimeIndex 对齐错位。
    """
    df = pd.read_csv(path)
    df[time_col] = pd.to_datetime(df[time_col], errors="coerce")
    df = df.dropna(subset=[time_col])
    raw_names = set(mapping.values())
    out = pd.DataFrame()
    for std, raw in mapping.items():
        if raw in df.columns:
            out[std] = pd.to_numeric(df[raw], errors="coerce").to_numpy()
    for col in df.columns:
        for raw in raw_names:
            if col.startswith(raw + "_") and col not in out.columns:
                out[col] = pd.to_numeric(df[col], errors="coerce").to_numpy()
                break
    out.index = pd.to_datetime(df[time_col]).to_numpy()
    out = out[~out.index.duplicated(keep="last")].sort_index()
    out = out.resample("1h").mean()
    return out


def detect_stations(lab: pd.DataFrame) -> tuple[list[str], bool]:
    """实况表里的站点: 有 obs_t2m_sN 后缀列 -> 多站; 否则单站(记作 s1)。"""
    suffixed = sorted({m.group(1) for c in lab.columns if (m := STATION_RE.match(c))})
    if suffixed:
        return suffixed, True
    return (["s1"], False) if "obs_t2m" in lab.columns else ([], False)


def load_static(path: str) -> pd.DataFrame | None:
    if not path:
        return None
    df = pd.read_csv(path)
    if "station" in df.columns:
        df = df.set_index("station")
    return df


def make_station_wide(
    bg: pd.DataFrame, lab: pd.DataFrame, cfg: dict,
    station: str, is_suffixed: bool, all_stations: list[str],
    static: pd.DataFrame | None, neighbors_k: int,
) -> pd.DataFrame:
    """为目标站组装宽表: 背景场(多格点)+ 目标站实况 + 邻站实况 + 静态地形。"""
    sfx = f"_{station}" if is_suffixed else ""

    def lab_col(base: str) -> str:
        return base + sfx

    own = pd.DataFrame(index=lab.index)
    for base, std in (("obs_t2m", "obs_t2m"), ("obs_rh", "obs_rh"),
                      ("obs_ws", "obs_ws"), ("obs_wd", "obs_wd")):
        if lab_col(base) in lab.columns:
            own[std] = lab[lab_col(base)]

    wide = bg.join(own, how="inner")

    # 邻站协同特征(空间上下文): 其他站实况当前值
    others = [s for s in all_stations if s != station][:neighbors_k]
    for i, s in enumerate(others, start=1):
        ns = f"_{s}"
        if f"obs_t2m{ns}" in lab.columns:
            wide[f"obs_t2m_nb{i}"] = lab[f"obs_t2m{ns}"].reindex(wide.index)

    # 静态地形/土地覆盖(static.csv 优先, 其次 config 默认); 其余数值列原样透传(如 tea_1km 等)
    garden_el = float(cfg["site"]["garden_elevation_m"])
    row = None
    if static is not None and station in static.index:
        row = static.loc[station]
    elif static is not None and len(static) == 1:
        row = static.iloc[0]
    elevation = float(row["elevation_m"]) if row is not None and "elevation_m" in row.index \
        else float(cfg["site"]["station_elevation_m"])
    wide["elevation"] = elevation
    wide["elev_delta"] = elevation - garden_el
    wide["slope"] = float(row["slope"]) if row is not None and "slope" in row.index else 0.0
    if row is not None and "aspect_deg" in row.index:
        a = np.deg2rad(float(row["aspect_deg"]))
        wide["aspect_sin"], wide["aspect_cos"] = float(np.sin(a)), float(np.cos(a))
    else:
        wide["aspect_sin"], wide["aspect_cos"] = 0.0, 0.0
    for c in ("tpi", "cai"):
        wide[c] = float(row[c]) if row is not None and c in row.index else 0.0
    if row is not None:
        for c in row.index:
            if c in ("lat", "lon", "station") or c in wide.columns:
                continue
            try:
                wide[c] = float(row[c])
            except (TypeError, ValueError):
                pass
    return wide


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config.yaml")
    args = ap.parse_args()

    with open(args.config, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    colmap, dcfg = cfg["columns"], cfg["data"]
    horizons = [int(h) for h in cfg["horizons"]]
    split_cfg = cfg["split"]
    val_start = pd.Timestamp(split_cfg["val_start"]) if split_cfg.get("val_start") else None
    test_start = pd.Timestamp(split_cfg["test_start"])
    train_start = pd.Timestamp(split_cfg["train_start"]) if split_cfg.get("train_start") else None
    neighbors_k = int(cfg["model"].get("neighbors_k", 0))
    inject_plus_h = bool(cfg["model"].get("inject_plus_h", True))

    def split_of(t: pd.Timestamp) -> str:
        # 严格时间切分: train | val | test(三段互不重叠, 各段只用过去信息)
        if val_start is not None and t >= val_start:
            return "val" if t < test_start else "test"
        return "train"

    # ---- 1. 读取 ----
    bg = load_table(dcfg["background"], colmap["background"], colmap["time"])
    lab = load_table(dcfg["labels"], colmap["labels"], colmap["time"])
    static = load_static(dcfg.get("static") or "")
    stations, is_suffixed = detect_stations(lab)
    if not stations:
        raise SystemExit("labels 中找不到 obs_t2m 列, 请检查列名映射。")
    if "t2m" not in bg.columns:
        raise SystemExit("background 中找不到 t2m 列, 请检查列名映射。")
    if train_start is not None:
        bg, lab = bg[bg.index >= train_start], lab[lab.index >= train_start]
    print(f"[build] 背景场 {len(bg)} 小时 / 实况 {len(lab)} 小时, 站点: {stations}, 邻站特征 k={neighbors_k}")
    if inject_plus_h:
        print("[build] 注入 bg_*_plus_h(背景场在 t+h 的值) —— 适用于有数值预报输入的误差订正模式")
    else:
        print("[build] 不注入 bg_*_plus_h —— 自监督模式(纯历史实况驱动, 无未来背景场)")

    # ---- 2. 气候态(只用训练段, 防泄漏: 验证/测试完全不可见) ----
    train_bg = bg[bg.index < (val_start if val_start is not None else test_start)]
    clim = compute_climatology(train_bg["t2m"])
    print(f"[build] 气候态样本日数: {len(clim)}(仅训练段)" )

    # ---- 3. 逐站构建 ----
    bgd = bg_cell_tables(bg)
    print(f"[build] 背景场格点数: {len(bgd)}")
    parts, report = [], {}
    for st in stations:
        wide = make_station_wide(bg, lab, cfg, st, is_suffixed, stations, static, neighbors_k)
        if wide.empty:
            print(f"[build] 站点 {st}: 背景场与实况无交集, 跳过")
            continue
        feats = build_features(wide, cfg, clim=clim)
        feats = feats.dropna()
        base_t = feats.index
        feats = feats.reset_index(names="time")
        n_before = len(wide)

        for h in horizons:
            tab = feats.copy()
            drop_cols = ["y_t2m"]
            if inject_plus_h:
                ph = plus_h_features(bgd, base_t, h)
                for c in ph.columns:
                    tab[c] = ph[c].to_numpy()
                drop_cols += ph.columns.to_list()
            tab["y_t2m"] = wide["obs_t2m"].shift(-h).reindex(base_t).to_numpy()
            if "obs_rh" in wide.columns:
                tab["y_rh"] = wide["obs_rh"].shift(-h).reindex(base_t).to_numpy()
            tab["horizon"] = h
            tab["t_plus_h"] = tab["time"] + pd.Timedelta(hours=h)
            tab["split"] = [split_of(t) for t in tab["time"]]
            tab["station"] = st
            tab = tab.dropna(subset=drop_cols)
            parts.append(tab)
            report[f"{st}_h{h}"] = {"rows": len(tab),
                                    "train": int((tab["split"] == "train").sum()),
                                    "val": int((tab["split"] == "val").sum()),
                                    "test": int((tab["split"] == "test").sum())}
        print(f"[build] 站点 {st}: 对齐 {n_before} 小时 -> 特征后保留 {len(feats)} 行")

    ds = pd.concat(parts, ignore_index=True)
    Path(dcfg["processed"]).parent.mkdir(parents=True, exist_ok=True)
    ds.to_parquet(dcfg["processed"], index=False)
    print(f"[build] 样本表已保存: {dcfg['processed']} 共 {len(ds)} 行")

    # ---- 4. 产物 ----
    outdir = Path(cfg["model"]["output_dir"])
    outdir.mkdir(parents=True, exist_ok=True)
    with open(outdir / "climatology.json", "w") as f:
        json.dump({int(k): float(v) for k, v in clim.items()}, f)
    with open(outdir / "build_report.json", "w", encoding="utf-8") as f:
        json.dump({
            "stations": stations,
            "n_bg_cells": len(bgd),
            "neighbors_k": neighbors_k,
            "horizons": horizons,
            "inject_plus_h": inject_plus_h,
            "split_boundaries": {
                "train_start": str(train_start) if train_start is not None else None,
                "val_start": str(val_start) if val_start is not None else None,
                "test_start": str(test_start),
            },
            "per_station_horizon": report,
            "time_range": [str(bg.index.min()), str(bg.index.max())],
        }, f, ensure_ascii=False, indent=2)
    print(f"[build] 气候态与报告已保存到 {outdir}")


if __name__ == "__main__":
    main()
