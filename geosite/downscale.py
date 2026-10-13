# -*- coding: utf-8 -*-
"""
geosite/downscale.py — 气温递减率降尺度 → 茶园微气候指标
========================================================
与 scripts/build_microclimate.py 同一套物理模型 (参数化版本):
  open-meteo(ERA5 背景)参考点气温 + DEM 地形降尺度 → 逐像素:

    T(pixel) = T(ref) - Γ * Δelev   (Γ = 气温递减率)
    Tmin(pixel) 额外叠加山谷冷池修正 -α * coldpool(flowacc 归一化)

指标:
  spring_gdd         明前积温 (多年平均, 1/1-4/5)
  frost_hours        春季霜冻小时 (2021-2026 合计, 2/1-4/5)
  spring_dtr         品质关键期昼夜温差 (多年平均, 3/1-4/5)
  first_pluck_doy    开采期 (中位 GDD 跨越阈值的日序)
  frost72h_*         未来 72h 逐像素霜冻小时/最低温

所有阈值集中在 CONFIG, 标注"待校准"的需文献/实测传感器标定。
"""
import numpy as np

CONFIG = {
    "lapse_rate": 0.0065,     # °C/m, 标准气温递减率
    "gdd_base": 10.0,         # °C, 茶芽生长起点温度 (文献常用 8-10, 待校准)
    "frost_temp": 2.0,        # °C, 芽梢受冻临界温度 (待校准)
    "pluck_gdd": 120.0,       # °C·d, 开采所需积温阈值 (待校准, 占位值)
    "cold_pool_alpha": 1.5,   # °C, 山谷冷池夜间降温强度系数 (待传感器校准)
    "spring_window": ("01-01", "04-05"),  # 明前积温统计窗口
    "frost_window": ("02-01", "04-05"),   # 春季霜冻统计窗口
    "dtr_window": ("03-01", "04-05"),     # 品质关键期 DTR 窗口
}


def load_daily(path):
    """读取日值 CSV → {date:[], tmax:[], tmin:[]}"""
    daily = {"date": [], "tmax": [], "tmin": []}
    with open(path, encoding="utf-8") as f:
        for line in f:
            if line.startswith("date"):
                continue
            d, x, n, _ = line.strip().split(",")
            daily["date"].append(d)
            daily["tmax"].append(float(x))
            daily["tmin"].append(float(n))
    return daily


def load_hourly(path):
    """读取小时值 CSV → {time:[], temp:[]}"""
    hourly = {"time": [], "temp": []}
    with open(path, encoding="utf-8") as f:
        for line in f:
            if line.startswith("time"):
                continue
            t, v = line.strip().split(",")
            hourly["time"].append(t)
            hourly["temp"].append(float(v))
    return hourly


def spring_gdd(daily, delev):
    """明前积温 (多年平均, 每像素; delev 为扁平数组 = DEM - 参考点海拔)"""
    dates = np.array(daily["date"])
    tmax = np.array(daily["tmax"])
    tmin = np.array(daily["tmin"])
    years = np.unique([d[:4] for d in dates])
    acc = []
    for y in years:
        sel = [(d[:4] == y and d[5:] >= "01-01" and d[5:] <= "04-05")
               for d in dates]
        tm = (tmax[sel] + tmin[sel]) / 2.0
        gdd = np.maximum(tm[None, :] - CONFIG["lapse_rate"] * delev[:, None]
                         - CONFIG["gdd_base"], 0).sum(axis=1)
        acc.append(gdd)
    return np.mean(acc, axis=0)


def frost_hours(hourly, delev):
    """春季霜冻小时数 (2021-2026 合计, 每像素)"""
    times = np.array(hourly["time"])
    temps = np.array(hourly["temp"])
    sel = [("02-01" <= t[5:10] <= "04-05") for t in times]
    temps = temps[sel]
    # 每小时的受冻临界高差: T - Γ*Δelev < frost_temp  <=>  Δelev > (T-frost_temp)/Γ
    thr = (temps - CONFIG["frost_temp"]) / CONFIG["lapse_rate"]
    thr_sorted = np.sort(thr)
    return np.searchsorted(thr_sorted, delev, side="left").astype(np.float64)


def spring_dtr(daily, delev, coldpool):
    """品质关键期昼夜温差 (多年平均): Tmax 仅递减率, Tmin 叠加山谷冷池"""
    dates = np.array(daily["date"])
    tmax = np.array(daily["tmax"])
    tmin = np.array(daily["tmin"])
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
    tmax = np.array(daily["tmax"])
    tmin = np.array(daily["tmin"])
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
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.nanmedian(np.array(doys), axis=0)


def frost72h_pixel(t2m_series, delev, coldpool=0.0):
    """未来 72h 逐小时预报 (背景场) 对单点/逐像素降尺度:
    返回 (未来72h最低温, 未来72h低于frost_temp的小时数)"""
    t = (np.asarray(t2m_series, dtype=np.float64)[None, :]
         - CONFIG["lapse_rate"] * np.asarray(delev)[:, None]
         - CONFIG["cold_pool_alpha"] * np.asarray(coldpool)[:, None])
    tmin72 = t.min(axis=1)
    hours = (t < CONFIG["frost_temp"]).sum(axis=1)
    return tmin72, hours


def frost_grade(hours):
    """霜冻风险等级 (占位阈值, 待实测校准):
    0 无风险 / 1 关注 / 2 中等(建议防护) / 3 高(重点防护)"""
    if hours is None or hours <= 0:
        return 0, "未来 72h 无霜冻风险"
    if hours <= 5:
        return 1, f"未来 72h 约 {hours:.0f}h 低于芽梢受冻临界 (2°C), 建议关注"
    if hours <= 20:
        return 2, f"未来 72h 约 {hours:.0f}h 低于 2°C, 建议做防霜准备 (覆盖/熏烟)"
    return 3, f"未来 72h 约 {hours:.0f}h 低于 2°C, 重点防护: 覆盖、熏烟、喷灌"
