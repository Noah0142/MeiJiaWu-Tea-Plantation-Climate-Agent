"""training_data 原始文件 -> 管线标准输入(严格无泄漏设计)。

数据分工(防污染核心):
- ERA5-Land 单格点(30.20N, 120.10E)76 年逐小时 = 唯一训练数据源;
  按时间严格切分 train/val/test(见 config.yaml split)。
- Open-Meteo 茶园序列(30.19N, 120.11E, 180m, 2026-10-06~11)与 ERA5 无时间重叠,
  不进入任何训练文件, 保留作独立外部部署测试(scripts/demo_garden_forecast.py)。
- Teamap_2022_China.tif(10m 茶园分布图)只用于提取静态土地覆盖特征。

处理: UTC→北京时间(+8h); K→℃; tp m→mm; ssrd J/m²/h→W/m²。

用法: python scripts/prepare_training_data.py [--src training_data] [--skip-tea]
产物: data/raw/background.csv, data/raw/labels.csv, data/raw/static.csv
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
import pandas as pd

from features.features import rh_from_t_td

ERA5_DIR = "training_data/ERA5"
FILES = {
    "t2m": "reanalysis-era5-land-timeseries-sfc-2m-temperature5i1zjdv8.csv",  # 含 t2m 与 d2m 两列
    "tp": "reanalysis-era5-land-timeseries-sfc-pressure-precipitationy5kmkj0s.csv",
    "ssrd": "reanalysis-era5-land-timeseries-sfc-radiation-heat909tao70.csv",
    "skt": "reanalysis-era5-land-timeseries-sfc-skin-temperature6akl57yh.csv",
    "stl": "reanalysis-era5-land-timeseries-sfc-soil-temperaturecbnppww3.csv",
    "swvl": "reanalysis-era5-land-timeseries-sfc-soil-watery96rmrj3.csv",
}
POINT = {"lat": 30.2000, "lon": 120.1000, "elevation_m": 180.0}  # 茶园参考点(与 Open-Meteo 海拔一致)


def read_var(path: str, cols: list[str]) -> pd.DataFrame:
    df = pd.read_csv(path, usecols=["valid_time"] + cols, parse_dates=["valid_time"])
    df["valid_time"] = df["valid_time"].dt.tz_localize("UTC").dt.tz_convert("Asia/Shanghai").dt.tz_localize(None)
    return df.set_index("valid_time").sort_index()


def tea_features(src_root: Path) -> dict:
    """从 10m 茶园分布图提取点位周边土地覆盖静态特征(缺 rasterio 则置 0)。"""
    try:
        import rasterio
        from rasterio.windows import from_bounds
    except Exception:  # noqa: BLE001
        return {}
    tif = src_root / "Teamap_2022_China.tif"
    if not tif.exists():
        return {}
    pad = 0.10  # 约 11km
    with rasterio.open(tif) as src:
        win = from_bounds(POINT["lon"] - pad, POINT["lat"] - pad,
                          POINT["lon"] + pad, POINT["lat"] + pad, src.transform)
        data = src.read(1, window=win)
    tea = data == 1
    h, w = data.shape
    ys, xs = np.mgrid[0:h, 0:w]
    dist_km = np.hypot(xs - w / 2, ys - h / 2) * 0.01
    out = {}
    for r in (1, 3, 5, 10):
        out[f"tea_{r}km"] = round(float(100 * tea[dist_km <= r].mean()), 2)
    ty, tx = np.where(tea)
    out["dist_tea_km"] = round(float(np.min(np.hypot(tx - w / 2, ty - h / 2)) * 0.01), 2) if len(tx) else -1.0
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default="training_data")
    ap.add_argument("--skip-tea", action="store_true")
    args = ap.parse_args()
    src = Path(args.src)

    # ---- 合并 6 个 ERA5-Land 文件 ----
    frames, info = {}, {}
    for name, path in {k: src / "ERA5" / v for k, v in FILES.items()}.items():
        if name in ("stl", "swvl"):
            cols = [f"{name}{i}" for i in range(1, 5)]
        elif name == "t2m":
            cols = ["t2m", "d2m"]  # 该文件同时含 2m 气温与露点
        else:
            cols = [name]
        df = read_var(str(path), cols)
        if name == "t2m":
            frames["t2m"], frames["d2m"] = df[["t2m"]], df[["d2m"]]
        else:
            frames[name] = df
        info[name] = (str(df.index.min()), str(df.index.max()), len(df))

    bg = pd.concat(frames.values(), axis=1).sort_index()
    for c in ("t2m", "d2m", "skt", "stl1", "stl2", "stl3", "stl4"):
        bg[c] = bg[c] - 273.15          # K -> ℃
    bg["tp"] = bg["tp"] * 1000.0        # m -> mm
    bg["ssrd"] = bg["ssrd"] / 3600.0    # J/m²/h -> W/m²
    bg = bg.rename(columns={"ssrd": "ssr"})
    bg = bg.dropna(subset=["t2m"])
    nan_report = {c: int(bg[c].isna().sum()) for c in bg.columns if bg[c].isna().any()}
    print(f"[prep] 合并后 {len(bg)} 小时, {bg.index.min()} ~ {bg.index.max()}(北京时间)")
    print("[prep] 各变量缺失数:", nan_report or "无")
    print("[prep] 各文件时间范围:", {k: v[1] for k, v in info.items()})

    # ---- 输出 ----
    out = Path("data/raw")
    out.mkdir(parents=True, exist_ok=True)
    bg.reset_index(names="time").to_csv(out / "background.csv", index=False)
    lab = pd.DataFrame({"obs_t2m": bg["t2m"], "obs_rh": rh_from_t_td(bg["t2m"], bg["d2m"])})
    lab.reset_index(names="time").to_csv(out / "labels.csv", index=False)

    static_row = {"station": "s1", **POINT,
                  "slope": 0.0, "aspect_deg": 0.0, "tpi": 0.0, "cai": 0.0}
    static_row.update({} if args.skip_tea else tea_features(src))
    pd.DataFrame([static_row]).to_csv(out / "static.csv", index=False)
    print(f"[prep] 静态特征: {static_row}")
    print(f"[prep] 已写 data/raw/background.csv, labels.csv, static.csv")


if __name__ == "__main__":
    main()
