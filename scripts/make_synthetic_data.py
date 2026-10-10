"""生成合成数据用于管线冒烟测试(切勿当作真实数据使用)。

可生成:
- 多格点背景场(--n-cells 9: 3×3 格点, 带空间梯度, 让邻域聚合特征有信息量)
- 多站实况(--n-stations 2: 不同高程/微地形差异, 测试邻站协同特征与微调)

用法: python scripts/make_synthetic_data.py --outdir data/synthetic --n-cells 9 --n-stations 2
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
import pandas as pd

from features.features import rh_from_t_td

RNG = np.random.default_rng(42)

CELL_OFFSETS = {  # 3×3 格点相对最近格点(c1=中心)的气温偏移: 北冷南暖东略暖(山谷地形代理)
    "c2": -0.4, "c3": -0.2, "c4": -0.5,   # 北侧
    "c5": 0.3, "c6": 0.5, "c7": 0.1,      # 南侧
    "c8": 0.2, "c9": -0.1,                # 东/西
}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--outdir", default="data/synthetic")
    ap.add_argument("--start", default="2022-01-01")
    ap.add_argument("--end", default="2024-12-31")
    ap.add_argument("--n-cells", type=int, choices=[1, 9], default=9)
    ap.add_argument("--n-stations", type=int, choices=[1, 2], default=2)
    args = ap.parse_args()

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    idx = pd.date_range(args.start, args.end, freq="1h", tz=None)
    n = len(idx)
    doy = idx.dayofyear + idx.hour / 24.0
    hour = idx.hour

    t2m = 17.0 + 9.0 * np.sin(2 * np.pi * (doy - 105) / 365.25) \
        + 4.0 * np.sin(2 * np.pi * (hour - 14) / 24.0) + RNG.normal(0, 0.6, n)
    d2m = t2m - 5.5 - 1.5 * np.sin(2 * np.pi * (doy - 150) / 365.25)
    ssr = np.clip(600.0 * np.sin(2 * np.pi * (hour - 6) / 24.0), 0, None) * (1 - 0.3 * np.sin(2 * np.pi * doy / 365.25))
    tp = np.where(RNG.random(n) < 0.08, RNG.exponential(1.2, n), 0.0)

    bg = pd.DataFrame({"t2m": t2m, "d2m": d2m,
                       "u10": RNG.normal(1.0, 0.8, n), "v10": RNG.normal(-0.5, 0.8, n),
                       "ssr": ssr, "tp": tp,
                       "stl1": t2m + 2.0 + RNG.normal(0, 0.5, n),
                       "swvl1": 0.25 + 0.05 * np.sin(2 * np.pi * (doy - 180) / 365.25) + RNG.normal(0, 0.01, n),
                       "sp": 1013.0 + RNG.normal(0, 1.5, n)}, index=idx)
    if args.n_cells == 9:
        for cid, off in CELL_OFFSETS.items():
            bg[f"t2m_{cid}"] = t2m + off + RNG.normal(0, 0.15, n)
            bg[f"d2m_{cid}"] = d2m + off * 0.8
            bg[f"u10_{cid}"] = bg["u10"] + RNG.normal(0, 0.2, n)
            bg[f"v10_{cid}"] = bg["v10"] + RNG.normal(0, 0.2, n)
            bg[f"ssr_{cid}"] = ssr + RNG.normal(0, 5, n)
            bg[f"tp_{cid}"] = tp

    # 实况: 已知映射 + 冷空气堆积(2–4 月 02–07 时)+ 噪声
    cold_pool = ((doy >= 32) & (doy <= 120) & (hour >= 2) & (hour <= 7)).astype(float) * -1.8
    s1_t2m = 0.90 * t2m - 0.6 + cold_pool + RNG.normal(0, 0.7, n)
    s2_t2m = 0.88 * t2m + 0.2 + cold_pool * 1.1 + RNG.normal(0, 0.7, n)  # 更高海拔、冷池更强

    stations = {}
    for i, s in enumerate([("s1", s1_t2m, 80.0), ("s2", s2_t2m, 120.0)][: args.n_stations], start=1):
        sid, st, el = s
        rh = rh_from_t_td(st, d2m - 0.5)
        ws = np.hypot(bg["u10"], bg["v10"]) * 0.8 + RNG.normal(0, 0.3, n)
        stations[sid] = pd.DataFrame(
            {"obs_t2m": st, "obs_rh": rh, "obs_ws": ws,
             "obs_wd": (np.degrees(np.arctan2(bg["v10"], bg["u10"])) + 360) % 360},
            index=idx)
        stations[sid].attrs["elevation_m"] = el

    # 写文件: 多站带后缀列, 单站无后缀
    if args.n_stations == 1:
        lab = stations["s1"].reset_index(names="time")
    else:
        lab = pd.DataFrame(index=idx)
        for sid, st in stations.items():
            for c in st.columns:
                lab[f"{c}_{sid}"] = st[c]
        lab = lab.reset_index(names="time")
    bg.reset_index(names="time").to_csv(outdir / "background.csv", index=False)
    lab.to_csv(outdir / "labels.csv", index=False)

    static = pd.DataFrame([
        {"station": sid, "lat": 30.2272 + (i - 1) * 0.01, "lon": 120.1014,
         "elevation_m": st.attrs["elevation_m"], "slope": 15.0 + i * 5,
         "aspect_deg": (180 + 90 * i) % 360, "tpi": -0.5 + i, "cai": 0.3}
        for i, (sid, st) in enumerate(stations.items(), start=1)])
    static.to_csv(outdir / "static.csv", index=False)

    daily_min = stations["s1"]["obs_t2m"].resample("1D").min()
    events = pd.DataFrame({"date": daily_min[daily_min <= 4.0].index.strftime("%Y-%m-%d"), "type": "frost"})
    events.to_csv(outdir / "events.csv", index=False)

    print(f"[synthetic] 已生成 {n} 小时, {args.n_cells} 格点, {args.n_stations} 站 -> {outdir}")
    print(f"[synthetic] s1 霜冻事件日(日 Tmin≤4℃): {len(events)} 天")


if __name__ == "__main__":
    main()
