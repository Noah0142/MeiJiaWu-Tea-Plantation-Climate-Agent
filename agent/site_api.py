# -*- coding: utf-8 -*-
"""
agent/site_api.py — 地图选点微气候 API (FastAPI Router)
========================================================
GET  /api/site/point   单点地形剖面 (网格内即时; 网格外现场计算)
POST /api/site/predict 对所选点位运行微气候模型 (背景场+地形+降尺度+72h预报)
GET  /api/site/overlay 梅家坞地形叠加层 PNG (hillshade / dem)

自包含: 只依赖 geosite/ + rasterio/numpy/matplotlib, 可独立挂载,
也可加入 GitHub 仓库的 agent/server.py (守卫式 import)。
"""
import json
import os
import sys
import time
from pathlib import Path

import numpy as np
import yaml
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

import geosite.downscale as ds
from geosite import landcover, terrain, weather

ROOT = Path(__file__).resolve().parents[1]
TERRAIN_DIR = ROOT / "data" / "terrain"
WEATHER_DIR = ROOT / "data" / "weather"
SITES_DIR = ROOT / "data" / "sites"
SITES_DIR.mkdir(parents=True, exist_ok=True)

WINDOW_HALF = 0.015  # 预测窗口半宽 (~1.7km 南北)

router = APIRouter(prefix="/api/site")

# 最近一次预测的内存缓存: (lat,lon) -> 响应 dict
_CACHE = {}


# 叠加层渲染倍率: 30m 网格窗口约 111px, 放大渲染避免 Leaflet 拉伸模糊
_RENDER_SCALE = 6


def _render_overlay(arr, bounds, out_path, cmap_name, title="", vmin=None,
                    vmax=None, zero_transparent=False):
    """把逐像素数组渲染成透明背景 PNG (供 Leaflet imageOverlay 贴图)。

    zero_transparent: 值为 0 的像素置为透明(计数类图层 0 = 无事件, 不应遮盖底图)。
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "sans-serif"]
    plt.rcParams["axes.unicode_minus"] = False

    arr = np.asarray(arr, dtype=np.float64)
    if zero_transparent:
        arr = np.where(arr <= 0, np.nan, arr)
    arr_m = np.ma.masked_invalid(arr)
    h, w = arr_m.shape
    dpi = 100
    s = _RENDER_SCALE
    fig = plt.figure(figsize=(w * s / dpi, h * s / dpi), dpi=dpi)
    ax = fig.add_axes([0, 0, 1, 1])
    cmap = plt.get_cmap(cmap_name).copy()
    cmap.set_bad("none")
    ax.imshow(arr_m, cmap=cmap, vmin=vmin, vmax=vmax,
              interpolation="nearest", aspect="equal")
    if title:
        fs = max(8, min(18, w * s / 55))  # 字号随画布宽度自适应, 避免过大被截断
        ax.text(0.012, 0.988, title, transform=ax.transAxes, fontsize=fs,
                color="white", va="top", ha="left",
                bbox=dict(boxstyle="round,pad=0.3", fc="black", ec="none",
                          alpha=0.5))
    ax.set_axis_off()
    fig.savefig(out_path, transparent=True, dpi=dpi)
    plt.close(fig)
    return out_path


def _render_terrain(dem, feats, bounds, out_path):
    """山体阴影 + 高程配色混合地形图 (透明背景)"""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    dem_m = np.ma.masked_invalid(dem)
    shade = np.nan_to_num(feats["hillshade"], nan=128.0) / 255.0
    shade = 0.45 + 0.55 * shade  # 0.45~1.0 提亮
    vmin, vmax = np.nanpercentile(dem, 2), np.nanpercentile(dem, 98)
    norm = (np.clip(dem, vmin, vmax) - vmin) / max(vmax - vmin, 1e-6)
    cmap = plt.get_cmap("terrain")
    rgb = cmap(np.nan_to_num(norm, nan=0.0))[:, :, :3] * shade[:, :, None]
    h, w = dem.shape
    dpi = 100
    s = _RENDER_SCALE
    fig = plt.figure(figsize=(w * s / dpi, h * s / dpi), dpi=dpi)
    ax = fig.add_axes([0, 0, 1, 1])
    rgba = np.dstack([rgb, np.where(dem_m.mask, 0.0, 1.0)])
    ax.imshow(rgba, interpolation="nearest", aspect="equal")
    ax.set_axis_off()
    fig.savefig(out_path, transparent=True, dpi=dpi)
    plt.close(fig)
    return out_path


def _actual_bounds(transform, h, w):
    """由窗口 transform 反算真实边界 (像素对齐)"""
    return [transform.c, transform.f + h * transform.e,
            transform.c + w * transform.a, transform.f]


def _round(v, nd=1):
    return round(float(v), nd) if v is not None and np.isfinite(v) else None


@router.get("/point")
def point_profile(lon: float, lat: float):
    """单点地形剖面; 梅家坞网格内附带现有微气候栅格值与土地覆盖"""
    if not (-180 <= lon <= 180 and -90 <= lat <= 90):
        raise HTTPException(400, "经纬度超出范围")
    vals, meta = terrain.point_terrain(lon, lat, ROOT)
    out = {
        "lon": lon, "lat": lat,
        "terrain": {k: _round(v) for k, v in vals.items()},
        "source": meta["source"],
        "note": meta["note"],
    }
    if meta["source"] == "meijiawu_grid":
        mc = {}
        micro = ROOT / "data" / "microclimate"
        for key, name in [("gdd_spring", "gdd_spring.tif"),
                          ("frost_hours", "frost_hours.tif"),
                          ("dtr_spring", "dtr_spring.tif"),
                          ("first_pluck_doy", "first_pluck_doy.tif")]:
            v = terrain._grid_sample(micro / name, lon, lat)
            mc[key] = _round(v)
        out["microclimate_grid"] = mc
    lc = landcover.point_landcover(lon, lat, ROOT / "data" / "landcover")
    out["landcover"] = ({"code": lc[0], "label": lc[1]} if lc else None)
    return out


class PredictIn(BaseModel):
    lon: float
    lat: float


@router.post("/predict")
def predict(inp: PredictIn):
    """对所选点位运行微气候模型: 背景场 + 地形 + 降尺度 + 72h 预报"""
    lon, lat = inp.lon, inp.lat
    if not (-180 <= lon <= 180 and -90 <= lat <= 90):
        raise HTTPException(400, "经纬度超出范围")
    key = f"{lat:.5f}_{lon:.5f}"
    if key in _CACHE:
        return _CACHE[key]

    t0 = time.time()
    warnings = []

    # ---- 1. 背景场: open-meteo 网格高程 + 历史 + 7 天预报 ----
    try:
        fc = weather.fetch_forecast(lat, lon)
        ref_elev = fc["elevation"]
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"气象预报获取失败: {e}") from e
    daily_path = weather.fetch_daily(lat, lon, WEATHER_DIR)
    hourly_path = weather.fetch_hourly(lat, lon, WEATHER_DIR)
    daily = ds.load_daily(daily_path)
    hourly = ds.load_hourly(hourly_path)

    # ---- 2. 地形: 点周围窗口 + 特征 ----
    try:
        dem, transform, feats, bounds, src = terrain.window_around(
            lon, lat, ROOT, half_deg=WINDOW_HALF)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"地形数据获取失败: {e}") from e
    h, w = dem.shape
    bbox = _actual_bounds(transform, h, w)
    if src == "nasadem_computed":
        warnings.append("该点位于梅家坞分析网格之外: TPI/汇流为局部窗口近似, "
                        "冷池修正精度下降")

    valid = np.isfinite(dem)
    delev = np.where(valid, dem - ref_elev, np.nan)   # 相对参考点高差
    cp = terrain.coldpool(feats["flowacc"])
    delev_f = delev.ravel()
    cp_f = cp.ravel()

    # ---- 3. 微气候模型 (多年平均品质指标) ----
    gdd = ds.spring_gdd(daily, delev_f).reshape(h, w)
    frost = ds.frost_hours(hourly, delev_f).reshape(h, w)
    dtr = ds.spring_dtr(daily, delev_f, cp_f).reshape(h, w)
    pluck = ds.first_pluck_doy(daily, delev_f).reshape(h, w)

    # ---- 4. 未来 72h 本地化预报 ----
    fc_times = fc["hourly"]["time"][:72]
    fc_t2m = fc["hourly"]["temperature_2m"][:72]
    tmin72, frost72 = ds.frost72h_pixel(fc_t2m, delev_f, cp_f)
    tmin72 = tmin72.reshape(h, w)
    frost72 = frost72.reshape(h, w)

    # ---- 5. 点位取值 (窗口中心像素) ----
    cy, cx = h // 2, w // 2
    def _pv(arr):
        return _round(arr[cy, cx])

    t2m_local = [round(t - ds.CONFIG["lapse_rate"] * delev[cy, cx]
                       - ds.CONFIG["cold_pool_alpha"] * cp[cy, cx], 1)
                 for t in fc_t2m]
    f72 = _pv(frost72)
    grade, note = ds.frost_grade(f72)

    # ---- 6. 输出 PNG 叠加层 ----
    out_dir = SITES_DIR / key
    out_dir.mkdir(parents=True, exist_ok=True)
    overlays = {}
    overlay_info = {}
    _render_terrain(dem, feats, bbox, out_dir / "terrain.png")
    overlays["terrain"] = f"/pred/{key}/terrain.png"
    # (名称, 数组, 色带, vmin, vmax, 标题, 计数类=0视为无事件置透明, 单位)
    layer_specs = [
        ("gdd", gdd, "YlOrRd", None, None, "明前积温 GDD", False, "°C·d"),
        ("frost6y", frost, "Blues", None, None, "春季霜冻小时(6年合计)", True, "h"),
        ("dtr", dtr, "RdYlBu_r", None, None, "春季昼夜温差", False, "°C"),
        ("pluck", pluck, "viridis_r", None, None, "预计开采日", False, "DOY"),
        ("frost72h", frost72, "PuRd", 0, 72, "未来72h霜冻小时", True, "h"),
    ]
    for name, arr, cmap, vmin, vmax, title, zero_tr, unit in layer_specs:
        finite = arr[np.isfinite(arr)]
        has_data = bool(finite.size and float(np.nanmax(finite)) > 0) if zero_tr else bool(finite.size)
        if name == "frost72h":
            layer_title = f"{title}: 0-72h" if has_data else f"{title}: 全为 0"
        else:
            lo, hi = (float(np.nanmin(finite)), float(np.nanmax(finite))) if finite.size else (0, 0)
            layer_title = f"{title}: {lo:.0f}~{hi:.0f} {unit}"
        _render_overlay(arr, bbox, out_dir / f"{name}.png", cmap, layer_title,
                        vmin, vmax, zero_transparent=zero_tr)
        overlays[name] = f"/pred/{key}/{name}.png"
        overlay_info[name] = {"has_data": has_data, "unit": unit,
                              "title": layer_title}

    # ---- 6.5 土地覆盖 (ESA WorldCover 10m, 失败降级) ----
    lc_point = landcover.point_landcover(lon, lat, ROOT / "data" / "landcover")
    lc_win = landcover.stats_for_window(lon, lat, ROOT / "data" / "landcover",
                                        half_deg=0.02)
    if lc_point is None or lc_win is None:
        warnings.append("土地覆盖数据获取失败 (已标注未知), 不影响其他结果")

    # ---- 7. 响应 ----
    resp = {
        "lon": lon, "lat": lat,
        "ref_elev_m": _round(ref_elev),
        "ref_note": "open-meteo ERA5 背景场网格高程 (气温递减率参考基准)",
        "terrain": {
            "elevation_m": _pv(dem),
            "slope_deg": _pv(feats["slope"]),
            "aspect_deg": _pv(feats["aspect"]),
            "tpi_m": _pv(feats["tpi"]),
            "flowacc": _pv(feats["flowacc"]),
        },
        "landcover": {
            "point": ({"code": lc_point[0], "label": lc_point[1]}
                      if lc_point else None),
            "window_pct": lc_win,
            "note": "ESA WorldCover 10m (2021), 茶园多被分为林地/灌木/农田",
        },
        "microclimate": {
            "gdd_spring": _pv(gdd),
            "frost_hours_6yr": _pv(frost),
            "dtr_spring": _pv(dtr),
            "first_pluck_doy": _pv(pluck),
            "windows": "GDD 1/1-4/5 多年平均; 霜冻 2/1-4/5 2021-2026合计; "
                       "DTR 3/1-4/5 多年平均",
            "params_note": "气温递减率 0.0065°C/m、GDD基温10°C、受冻临界2°C、"
                           "冷池系数1.5 为占位参数, 需实测校准",
        },
        "forecast_72h": {
            "issued_at": fc_times[0],
            "times": fc_times,
            "t2m_local": t2m_local,
            "min_72h": round(min(t2m_local), 1),
            "max_72h": round(max(t2m_local), 1),
            "frost_hours_next72h": f72,
            "frost_grade": grade,
            "frost_note": note,
        },
        "window": {"bbox": bbox, "half_deg": WINDOW_HALF,
                   "size_km": round(2 * WINDOW_HALF * 111.32, 1)},
        "overlays": overlays,
        "overlay_info": overlay_info,
        "elapsed_s": round(time.time() - t0, 1),
        "warnings": warnings,
    }
    _CACHE[key] = resp
    return resp


@router.get("/overlay")
def overlay(layer: str = "hillshade"):
    """梅家坞网格地形叠加层 PNG (hillshade=山体阴影, dem=高程配色)"""
    grid = TERRAIN_DIR / "meijiawu"
    out = SITES_DIR / f"meijiawu_{layer}.png"
    if out.exists():
        return {"url": f"/pred/meijiawu_{layer}.png",
                "bbox": list(terrain.MEIJIAWU_BBOX)}
    if layer == "hillshade":
        with __import__("rasterio").open(grid / "hillshade.tif") as s:
            arr = s.read(1).astype(np.float64)
            arr[arr < 0] = np.nan
        _render_overlay(arr, list(terrain.MEIJIAWU_BBOX), out, "gray",
                        vmin=0, vmax=255)
    elif layer == "dem":
        with __import__("rasterio").open(grid / "dem_30m.tif") as s:
            arr = s.read(1).astype(np.float64)
            arr[arr == -32768] = np.nan
        _render_overlay(arr, list(terrain.MEIJIAWU_BBOX), out, "terrain")
    else:
        raise HTTPException(400, "layer 只能是 hillshade 或 dem")
    return {"url": f"/pred/meijiawu_{layer}.png",
            "bbox": list(terrain.MEIJIAWU_BBOX)}


# ---- LightGBM 监测点对照预报 (供地图页 72h 曲线叠加虚线) ----
_REF_CACHE = {"ts": 0.0, "data": None}
_REF_SENSOR = os.environ.get(
    "SENSOR_CSV", str(ROOT / "training_data" / "open-meteo-30.19N120.11E180m.csv"))


@router.get("/reference-forecast")
def reference_forecast():
    """梅家坞监测点 LightGBM 模型 0-72h 预报 (2 分钟缓存)。

    输入优先 Open-Meteo 实时(最近 6 天逐小时), 失败回退本地 CSV。
    注意: 这是监测点(梅家坞茶园传感器历史)的高精度时序预报,
    作为地图任意点位的参考对照, 不是对所选点位的空间外推。
    """
    global _REF_CACHE
    if _REF_CACHE["data"] is not None and time.time() - _REF_CACHE["ts"] < 110:
        return _REF_CACHE["data"]
    sys.path.insert(0, str(ROOT))
    from models.predict import load_predictor, read_inputs, run_forecast

    with open(ROOT / "config.yaml", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    site = cfg.get("site", {})
    try:
        from models.live_data import fetch_openmeteo_inputs
        bg, lab, meta = fetch_openmeteo_inputs(
            site.get("lat", 30.2272), site.get("lon", 120.1014), past_days=6)
        src_label = f"Open-Meteo 实时({meta['fetched_at']} 拉取)"
    except Exception as e:  # noqa: BLE001
        print(f"[site] 实时数据获取失败({e}), 回退本地 CSV")
        bg, lab = read_inputs(cfg, _REF_SENSOR, "open-meteo")
        src_label = "本地 CSV(离线回退)"
    fc, t0 = run_forecast(cfg, load_predictor(cfg), bg, lab, hours=72)
    data = {
        "issued_at": str(t0),
        "data_source": src_label,
        "label": "梅家坞监测点(LightGBM)",
        "note": "监测点高精度时序预报, 供点位对照; 非所选点位的空间外推",
        "hourly": [{"time": str(idx), "t2m_p50": round(float(r["t2m_p50"]), 1)}
                   for idx, r in fc.iterrows()],
    }
    _REF_CACHE = {"ts": time.time(), "data": data}
    return data
