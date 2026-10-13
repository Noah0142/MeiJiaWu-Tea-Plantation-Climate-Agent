# -*- coding: utf-8 -*-
"""
geosite/weather.py — open-meteo 任意点位气象数据 (免注册)
=========================================================
  fetch_daily()   2016-01-01 至 2026-04-30 日值 (tmax/tmin/precip), 幂等 CSV 缓存
  fetch_hourly()  2021-01-01 至 2026-04-30 小时值 (temp), 幂等 CSV 缓存
  fetch_forecast() 未来 7 天小时预报 (实时, 每次拉取) + 网格高程

缓存键按 ERA5 0.25° 网格单元取整 — 同网格不同点共享同一份数据。
梅家坞村址 (120.084, 30.206) 沿用原有文件名, 直接复用已下载 CSV。
"""
import os

from geosite.net import urlopen_json

ARCHIVE = "https://archive-api.open-meteo.com/v1/archive"
FORECAST = "https://api.open-meteo.com/v1/forecast"
TZ = "Asia%2FShanghai"

VILLAGE_LON, VILLAGE_LAT = 120.084, 30.206


def grid_key(lat, lon):
    """ERA5 0.25° 网格单元键 (cell 中心经纬度)"""
    return f"{round(lat * 4) / 4:.2f}_{round(lon * 4) / 4:.2f}"


def fetch_daily(lat, lon, cache_dir):
    """日值 CSV (幂等): 村址用原名, 其他点位按网格键命名"""
    os.makedirs(cache_dir, exist_ok=True)
    near_village = (abs(lat - VILLAGE_LAT) < 0.05
                    and abs(lon - VILLAGE_LON) < 0.05)
    if near_village:
        path = os.path.join(cache_dir, "meijiawu_daily_2016_2026.csv")
    else:
        path = os.path.join(cache_dir, f"daily_{grid_key(lat, lon)}.csv")
    if os.path.exists(path) and os.path.getsize(path) > 1000:
        return path
    url = (ARCHIVE + "?latitude={lat}&longitude={lon}"
           "&start_date=2016-01-01&end_date=2026-04-30"
           "&daily=temperature_2m_max,temperature_2m_min,precipitation_sum"
           f"&timezone={TZ}").format(lat=lat, lon=lon)
    print(f"[weather] 下载日值 {lat:.2f},{lon:.2f} ...")
    j = urlopen_json(url, timeout=240)["daily"]
    with open(path, "w", encoding="utf-8") as f:
        f.write("date,tmax,tmin,precip\n")
        for t, x, n, p in zip(j["time"], j["temperature_2m_max"],
                              j["temperature_2m_min"], j["precipitation_sum"]):
            f.write(f"{t},{x},{n},{p}\n")
    return path


def fetch_hourly(lat, lon, cache_dir):
    """小时值 CSV (幂等): 2021-01-01 至 2026-04-30 (霜冻窗口已完整)"""
    os.makedirs(cache_dir, exist_ok=True)
    near_village = (abs(lat - VILLAGE_LAT) < 0.05
                    and abs(lon - VILLAGE_LON) < 0.05)
    if near_village:
        path = os.path.join(cache_dir, "meijiawu_hourly_2021_2026.csv")
    else:
        path = os.path.join(cache_dir, f"hourly_{grid_key(lat, lon)}.csv")
    if os.path.exists(path) and os.path.getsize(path) > 10_000:
        return path
    url = (ARCHIVE + "?latitude={lat}&longitude={lon}"
           "&start_date=2021-01-01&end_date=2026-04-30"
           f"&hourly=temperature_2m&timezone={TZ}").format(lat=lat, lon=lon)
    print(f"[weather] 下载小时值 {lat:.2f},{lon:.2f} (约 5 年, 需 10-60s) ...")
    j = urlopen_json(url, timeout=300)["hourly"]
    with open(path, "w", encoding="utf-8") as f:
        f.write("time,temp\n")
        for t, v in zip(j["time"], j["temperature_2m"]):
            f.write(f"{t},{v}\n")
    return path


def fetch_forecast(lat, lon):
    """未来 7 天小时预报 + open-meteo 网格高程 (实时)"""
    url = (FORECAST + "?latitude={lat}&longitude={lon}"
           "&hourly=temperature_2m,relative_humidity_2m,precipitation"
           f"&forecast_days=7&timezone={TZ}").format(lat=lat, lon=lon)
    j = urlopen_json(url, timeout=60)
    return {
        "elevation": float(j["elevation"]),
        "hourly": j["hourly"],
        "hourly_units": j.get("hourly_units", {}),
        "generated_at": j.get("generationtime_ms"),
    }
