# -*- coding: utf-8 -*-
"""
build_microclimate.py — 地形 × 气温 → 茶园品质相关微气候指标
============================================================
思路: 以 open-meteo(ERA5 背景)参考点气温 + DEM 地形降尺度,
      生成茶园空间化的品质驱动指标:

  明前积温 GDD     — 决定茶芽萌发与开采期早晚 (品质分级"明前/雨前"的核心)
  春季霜冻时长     — 倒春寒毁芽风险 (山谷冷空气沉积使低处风险更高)
  昼夜温差 DTR     — 茶氨酸积累、香气形成的关键 (含山谷冷池修正)
  开采期 DOY       — 各地块开采先后估计 (采收调度依据)

所有阈值参数集中在下方 CONFIG, 标注"待校准"的需用文献/实测传感器数据标定。

运行: python scripts/build_microclimate.py  (依赖: rasterio/numpy/matplotlib)
"""
import json
import os
import sys
import urllib.request

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import rasterio

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(BASE, "data")
TERRAIN = os.path.join(DATA, "terrain")
WEATHER = os.path.join(DATA, "weather")
OUTDIR = os.path.join(DATA, "microclimate")
os.makedirs(WEATHER, exist_ok=True)
os.makedirs(OUTDIR, exist_ok=True)

LAT, LON = 30.206, 120.084
REF_ELEV = 58.0   # 参考点海拔 (open-meteo 网格高程 58m, 与村址 DEM 一致)

CONFIG = {
    "lapse_rate": 0.0065,     # °C/m, 标准气温递减率
    "gdd_base": 10.0,         # °C, 茶芽生长起点温度 (文献常用 8–10, 待校准)
    "frost_temp": 2.0,        # °C, 芽梢受冻临界温度 (待校准)
    "pluck_gdd": 120.0,       # °C·d, 开采所需积温阈值 (待校准, 占位值)
    "cold_pool_alpha": 1.5,   # °C, 山谷冷池夜间降温强度系数 (待传感器校准)
    "spring_window": ("01-01", "04-05"),  # 明前积温统计窗口
    "frost_window": ("02-01", "04-05"),   # 春季霜冻统计窗口
    "dtr_window": ("03-01", "04-05"),     # 品质关键期 DTR 窗口
}


def fetch_weather():
    """下载参考点气象数据 (幂等, 缓存 CSV)"""
    daily_csv = os.path.join(WEATHER, "meijiawu_daily_2016_2026.csv")
    if not os.path.exists(daily_csv):
        url = ("https://archive-api.open-meteo.com/v1/archive?latitude={lat}"
               "&longitude={lon}&start_date=2016-01-01&end_date=2026-10-10"
               "&daily=temperature_2m_max,temperature_2m_min,precipitation_sum"
               "&timezone=Asia%2FShanghai".format(lat=LAT, lon=LON))
        with urllib.request.urlopen(url, timeout=120) as r:
            j = json.load(r)["daily"]
        with open(daily_csv, "w", encoding="utf-8") as f:
            f.write("date,tmax,tmin,precip\n")
            for t, x, n, p in zip(j["time"], j["temperature_2m_max"],
                                  j["temperature_2m_min"], j["precipitation_sum"]):
                f.write(f"{t},{x},{n},{p}\n")

    hourly_csv = os.path.join(WEATHER, "meijiawu_hourly_2021_2026.csv")
    if not os.path.exists(hourly_csv):
        url = ("https://archive-api.open-meteo.com/v1/archive?latitude={lat}"
               "&longitude={lon}&start_date=2021-01-01&end_date=2026-10-10"
               "&hourly=temperature_2m&timezone=Asia%2FShanghai".format(lat=LAT, lon=LON))
        with urllib.request.urlopen(url, timeout=180) as r:
            j = json.load(r)["hourly"]
        with open(hourly_csv, "w", encoding="utf-8") as f:
            f.write("time,temp\n")
            for t, v in zip(j["time"], j["temperature_2m"]):
                f.write(f"{t},{v}\n")
    print("气象数据就绪:", daily_csv, "|", hourly_csv)


def load_arrays():
    """载入 DEM 与地形特征, 返回掩膜后的扁平数组"""
    with rasterio.open(os.path.join(TERRAIN, "meijiawu", "dem_30m.tif")) as s:
        dem = s.read(1).astype(np.float64)
        profile = s.profile.copy()
    with rasterio.open(os.path.join(TERRAIN, "meijiawu", "flowacc.tif")) as s:
        flow = s.read(1).astype(np.float64)
    flow = np.where(flow == -9999, 0, flow)
    mask = (dem != -32768)
    delev = dem - REF_ELEV                       # 相对参考点高差
    coldpool = np.log1p(flow) / np.log1p(np.max(flow))  # 冷池强度 0–1
    return delev, coldpool, mask, profile


def lapse_series(series, delev):
    """气温递减率降尺度: T(pixel) = T(ref) - Γ * Δelev"""
    return series[None, :] - CONFIG["lapse_rate"] * delev[:, None]


def spring_gdd(daily, delev):
    """明前积温 (多年平均, 每像素)"""
    # 每年 1/1–4/5 窗口
    dates = np.array(daily["date"])
    tmax = np.array(daily["tmax"]); tmin = np.array(daily["tmin"])
    years = np.unique([d[:4] for d in dates])
    acc = []
    for y in years:
        sel = [(d[:4] == y and d[5:] >= "01-01" and d[5:] <= "04-05") for d in dates]
        tm = (tmax[sel] + tmin[sel]) / 2.0
        gdd = np.maximum(tm[None, :] - CONFIG["lapse_rate"] * delev[:, None]
                         - CONFIG["gdd_base"], 0).sum(axis=1)
        acc.append(gdd)
    return np.mean(acc, axis=0)


def frost_hours(hourly, delev):
    """春季霜冻小时数 (2021–2026 合计, 每像素)"""
    times = np.array(hourly["time"]); temps = np.array(hourly["temp"])
    sel = [("02-01" <= t[5:10] <= "04-05") for t in times]
    temps = temps[sel]
    # 每小时的受冻临界高差: T - Γ*Δelev < frost_temp  <=>  Δelev > (T-frost_temp)/Γ
    thr = (temps - CONFIG["frost_temp"]) / CONFIG["lapse_rate"]
    thr_sorted = np.sort(thr)
    return np.searchsorted(thr_sorted, delev, side="left").astype(np.float64)


def spring_dtr(daily, delev, coldpool):
    """品质关键期昼夜温差 (多年平均): Tmax 仅递减率, Tmin 叠加山谷冷池"""
    dates = np.array(daily["date"])
    tmax = np.array(daily["tmax"]); tmin = np.array(daily["tmin"])
    years = np.unique([d[:4] for d in dates])
    acc = []
    for y in years:
        sel = [(d[:4] == y and "03-01" <= d[5:] <= "04-05") for d in dates]
        tmax_p = tmax[sel][None, :] - CONFIG["lapse_rate"] * delev[:, None]
        tmin_p = (tmin[sel][None, :] - CONFIG["lapse_rate"] * delev[:, None]
                  - CONFIG["cold_pool_alpha"] * coldpool[:, None])
        acc.append(np.mean(tmax_p - tmin_p, axis=1))
    return np.mean(acc, axis=0)


def first_pluck_doy(daily, delev):
    """开采期估计: 各像素多年中位 GDD 跨越阈值日 (1/1 起算的日序)"""
    dates = np.array(daily["date"])
    tmax = np.array(daily["tmax"]); tmin = np.array(daily["tmin"])
    years = np.unique([d[:4] for d in dates])
    doys = []
    for y in years:
        sel = [(d[:4] == y and "01-01" <= d[5:] <= "04-05") for d in dates]
        tm = (tmax[sel] + tmin[sel]) / 2.0
        gdd = np.maximum(tm[None, :] - CONFIG["lapse_rate"] * delev[:, None]
                         - CONFIG["gdd_base"], 0)
        cum = np.cumsum(gdd, axis=1)
        cross = np.argmax(cum >= CONFIG["pluck_gdd"], axis=1)
        never = ~(cum >= CONFIG["pluck_gdd"]).any(axis=1)
        cross = cross.astype(np.float64)
        cross[never] = np.nan
        doys.append(cross)
    return np.nanmedian(np.array(doys), axis=0)


def save_map(name, flat, mask, profile, nodata=-9999):
    h, w = mask.shape
    arr = np.full(h * w, nodata, dtype=np.float32)
    arr[mask.ravel()] = flat.astype(np.float32)
    prof = profile.copy()
    prof.update(dtype="float32", nodata=nodata, compress="deflate")
    with rasterio.open(os.path.join(OUTDIR, name), "w", **prof) as dst:
        dst.write(arr.reshape(h, w), 1)


def main():
    fetch_weather()

    daily = {k: [] for k in ("date", "tmax", "tmin")}
    with open(os.path.join(WEATHER, "meijiawu_daily_2016_2026.csv"), encoding="utf-8") as f:
        for line in f:
            if line.startswith("date"):
                continue
            d, x, n, _ = line.strip().split(",")
            daily["date"].append(d); daily["tmax"].append(float(x))
            daily["tmin"].append(float(n))
    hourly = {"time": [], "temp": []}
    with open(os.path.join(WEATHER, "meijiawu_hourly_2021_2026.csv"), encoding="utf-8") as f:
        for line in f:
            if line.startswith("time"):
                continue
            t, v = line.strip().split(",")
            hourly["time"].append(t); hourly["temp"].append(float(v))

    delev, coldpool, mask, profile = load_arrays()
    idx = mask.ravel()
    delev_f = delev.ravel()[idx]
    cp_f = coldpool.ravel()[idx]
    print(f"有效格点: {idx.sum()} / {idx.size}")

    gdd = spring_gdd(daily, delev_f)
    frost = frost_hours(hourly, delev_f)
    dtr = spring_dtr(daily, delev_f, cp_f)
    pluck = first_pluck_doy(daily, delev_f)

    for name, val in [("gdd_spring.tif", gdd), ("frost_hours.tif", frost),
                      ("dtr_spring.tif", dtr), ("first_pluck_doy.tif", pluck)]:
        save_map(name, val, mask, profile)

    # ---- 可视化 ----
    def full(flat):
        arr = np.full(mask.shape, np.nan)
        arr[mask] = flat
        return arr

    plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "sans-serif"]
    plt.rcParams["axes.unicode_minus"] = False
    fig, axes = plt.subplots(2, 2, figsize=(13, 11))
    extent = [120.03, 120.14, 30.16, 30.26]
    titles = ["Mingqian GDD (degree-days, Jan1-Apr5)",
              "Spring frost hours (Feb-Apr, 2021-2026)",
              "Spring DTR (degC, Mar-Apr)",
              "Estimated first-pluck day (DOY from Jan 1)"]
    cmaps = ["YlOrRd", "Blues", "RdYlBu_r", "viridis_r"]
    for ax, t, c, name, flat in zip(axes.ravel(), titles, cmaps,
                                    ["gdd_spring.tif", "frost_hours.tif",
                                     "dtr_spring.tif", "first_pluck_doy.tif"],
                                    [gdd, frost, dtr, pluck]):
        im = ax.imshow(full(flat), extent=extent, cmap=c)
        ax.scatter(120.084, 30.206, marker="*", s=150, c="red",
                   edgecolors="k", zorder=5)
        ax.set_title(t)
        fig.colorbar(im, ax=ax, shrink=0.8)
    fig.suptitle("Meijiawu Tea Garden Microclimate & Tea-Quality Metrics", fontsize=14)
    fig.tight_layout()
    fig.savefig(os.path.join(OUTDIR, "microclimate_preview.png"), dpi=150)
    plt.close(fig)

    stats = {
        "reference_point": {"lat": LAT, "lon": LON, "elev_m": REF_ELEV},
        "config": CONFIG,
        "gdd_spring": {"min": float(np.nanmin(gdd)), "max": float(np.nanmax(gdd)),
                       "mean": float(np.nanmean(gdd))},
        "frost_hours": {"min": float(np.nanmin(frost)), "max": float(np.nanmax(frost)),
                        "mean": float(np.nanmean(frost))},
        "dtr_spring": {"min": float(np.nanmin(dtr)), "max": float(np.nanmax(dtr)),
                       "mean": float(np.nanmean(dtr))},
        "first_pluck_doy": {"min": float(np.nanmin(pluck)), "max": float(np.nanmax(pluck))},
        "note": "GDD基温/霜冻临界/开采积温/冷池系数为占位参数, 需文献与实测校准",
    }
    with open(os.path.join(OUTDIR, "microclimate_stats.json"), "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)
    print(json.dumps(stats, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    sys.exit(main())
