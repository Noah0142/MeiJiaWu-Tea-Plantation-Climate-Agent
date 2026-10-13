# -*- coding: utf-8 -*-
"""
geosite/terrain.py — 任意点位/窗口的地形数据获取与特征工程
===========================================================
数据源: NASADEM 30m (NASA, 2020, SRTM 重处理版), 经 Microsoft Planetary
Computer 公开 SAS 签名获取 (免注册), 瓦片 1°x1° 按需下载、本地幂等缓存。

梅家坞网格 (data/terrain/meijiawu/) 内直接采样现有衍生特征栅格 (快路径),
网格外按需下载 NASADEM 瓦片并现场计算 (慢路径, 约 2-5s)。

纯函数全部参数化, 供 agent/ 与 scripts/process_dem.py 复用。
"""
import os
import urllib.parse

import numpy as np
import rasterio
from rasterio.transform import rowcol
from rasterio.windows import from_bounds

from geosite.net import download, urlopen_json

M_PER_DEG_LAT = 111320.0
NODATA_I16 = -32768

SIGN_API = "https://planetarycomputer.microsoft.com/api/sas/v1/sign"
NASADEM_URL = ("https://nasademeuwest.blob.core.windows.net/nasadem-cog/v001/"
               "{tile}.tif")

# 梅家坞分析网格 (process_dem.py 裁剪产物, 360x396 @ ~30.9m)
MEIJIAWU_BBOX = (120.03, 30.16, 120.14, 30.26)  # west, south, east, north


def tile_name(lat, lon):
    """1°x1° NASADEM 瓦片名 (西南角命名), 如 n30e120 覆盖 30-31N/120-121E"""
    ns = "n" if lat >= 0 else "s"
    ew = "e" if lon >= 0 else "w"
    return f"{ns}{int(abs(np.floor(lat))):02d}{ew}{int(abs(np.floor(lon))):03d}"


def ensure_nasadem_tile(lat, lon, cache_dir):
    """确保某点所在 NASADEM 瓦片已在本地 (幂等: 已存在则直接返回路径)"""
    os.makedirs(cache_dir, exist_ok=True)
    path = os.path.join(cache_dir, tile_name(lat, lon) + ".tif")
    if os.path.exists(path) and os.path.getsize(path) > 100_000:
        return path
    href = NASADEM_URL.format(tile=tile_name(lat, lon))
    sign_url = SIGN_API + "?href=" + urllib.parse.quote(href, safe="")
    signed = urlopen_json(sign_url, timeout=30)["href"]
    print(f"[terrain] 下载 NASADEM 瓦片 {tile_name(lat, lon)} ...")
    download(signed, path, min_bytes=100_000)
    print(f"[terrain] 完成: {path} ({os.path.getsize(path):,} bytes)")
    return path


def extract_window(src_path, bounds):
    """从 1° 瓦片按 bounds(west,south,east,north) 窗口读取 DEM (float64)"""
    with rasterio.open(src_path) as src:
        win = from_bounds(*bounds, src.transform)
        data = src.read(1, window=win).astype(np.float64)
        transform = src.window_transform(win)
    data[data == NODATA_I16] = np.nan
    return data, transform


def boxcar_mean(a, k):
    """精确的 kxk 均值滤波 (cumsum 实现, 边界留 NaN)"""
    h, w = a.shape
    s = np.zeros((h + 1, w + 1), dtype=np.float64)
    s[1:, 1:] = np.cumsum(np.cumsum(a.astype(np.float64), axis=0), axis=1)
    ws = s[k:, k:] - s[:-k, k:] - s[k:, :-k] + s[:-k, :-k]
    out = np.full_like(a, np.nan, dtype=np.float64)
    out[k // 2:h - k // 2, k // 2:w - k // 2] = ws / (k * k)
    return out


def d8_flowacc(dem):
    """D8 流向汇流累积 (谷底/冷空气通道代理特征)"""
    offs = [(-1, 0), (-1, 1), (0, 1), (1, 1),
            (1, 0), (1, -1), (0, -1), (-1, -1)]
    h, w = dem.shape
    dp = np.pad(dem.astype(np.float64), 1, mode="constant",
                constant_values=np.inf)
    drops = np.stack([dem - dp[1 + dr:1 + dr + h, 1 + dc:1 + dc + w]
                      for dr, dc in offs])
    d2 = np.where(np.isnan(drops), -np.inf, drops)
    d2[d2 <= 0] = -np.inf                       # 只沿下坡方向流动
    dirs = np.argmax(d2, axis=0)
    valid = np.isfinite(d2.max(axis=0))
    acc = np.ones((h, w), dtype=np.float64)
    order = np.argsort(np.nan_to_num(dem).ravel())[::-1]  # 从高到低逐格累加
    for idx in order:
        r, c = divmod(int(idx), w)
        if not valid[r, c]:
            continue
        dr, dc = offs[int(dirs[r, c])]
        acc[r + dr, c + dc] += acc[r, c]
    return acc


def terrain_features(dem, transform):
    """由 DEM 计算坡度/坡向/山体阴影/TPI/汇流累积 (与 process_dem.py 同算法)

    返回 dict of float64 数组; TPI 需要 >=11x11 邻域, 小窗口时为 NaN。
    """
    h, w = dem.shape
    res = transform.a  # 每像素度数
    lats = transform.f + res * (np.arange(h) + 0.5)
    dx_m = res * M_PER_DEG_LAT * np.cos(np.radians(lats))[:, None]  # 东西向
    dy_m = res * M_PER_DEG_LAT                                   # 南北向

    dzdx = np.gradient(dem, axis=1) / dx_m
    dzdy = np.gradient(dem, axis=0) / dy_m
    slope_rad = np.arctan(np.hypot(dzdx, dzdy))
    slope = np.degrees(slope_rad)
    aspect = np.mod(np.degrees(np.arctan2(-dzdx, -dzdy)), 360.0)

    az, alt = 315.0, 45.0
    hs = (np.sin(np.radians(alt)) * np.cos(slope_rad)
          + np.cos(np.radians(alt)) * np.sin(slope_rad)
          * np.cos(np.radians(az) - np.radians(aspect)))
    hs_min, hs_max = np.nanmin(hs), np.nanmax(hs)
    hillshade = np.clip(255.0 * (hs - hs_min) / (hs_max - hs_min), 0, 255)

    tpi = (dem - boxcar_mean(dem, 11) if min(h, w) >= 11
           else np.full_like(dem, np.nan))
    flowacc = d8_flowacc(np.where(np.isnan(dem), np.inf, dem))
    return {"slope": slope, "aspect": aspect, "hillshade": hillshade,
            "tpi": tpi, "flowacc": flowacc}


def coldpool(flowacc):
    """冷池强度 0-1 (与 build_microclimate.py 相同公式)"""
    flow = np.where(np.isnan(flowacc), 0, np.maximum(flowacc, 0))
    mx = np.nanmax(flow)
    return np.log1p(flow) / np.log1p(mx) if mx > 0 else np.zeros_like(flow)


def _grid_sample(path, lon, lat):
    """在 Meijiawu 网格栅格上按经纬度采样单点 (无效值返回 None)"""
    with rasterio.open(path) as s:
        r, c = rowcol(s.transform, lon, lat)
        if not (0 <= r < s.height and 0 <= c < s.width):
            return None
        v = s.read(1)[r, c]
    v = float(v)
    if not np.isfinite(v) or v in (NODATA_I16, -9999.0):
        return None
    return v


def _in_meijiawu(lon, lat, pad=0.0):
    w, s, e, n = MEIJIAWU_BBOX
    return (w + pad <= lon <= e - pad) and (s + pad <= lat <= n - pad)


def point_terrain(lon, lat, root):
    """单点地形剖面: 网格内走快路径, 网格外现场计算 (返回 dict + 元信息)"""
    grid_dir = os.path.join(root, "data", "terrain", "meijiawu")
    if _in_meijiawu(lon, lat):
        return {
            "elevation_m": _grid_sample(os.path.join(grid_dir, "dem_30m.tif"),
                                        lon, lat),
            "slope_deg": _grid_sample(os.path.join(grid_dir, "slope.tif"),
                                      lon, lat),
            "aspect_deg": _grid_sample(os.path.join(grid_dir, "aspect.tif"),
                                       lon, lat),
            "tpi_m": _grid_sample(os.path.join(grid_dir, "tpi_330m.tif"),
                                  lon, lat),
            "flowacc": _grid_sample(os.path.join(grid_dir, "flowacc.tif"),
                                    lon, lat),
        }, {"source": "meijiawu_grid", "note": "梅家坞 11x11km 分析网格直接采样"}
    # 慢路径: 点周围 ~1.7km 窗口现场计算
    tile = ensure_nasadem_tile(lat, lon, os.path.join(root, "data", "terrain"))
    half = 0.015
    dem, transform = extract_window(tile, (lon - half, lat - half,
                                           lon + half, lat + half))
    feats = terrain_features(dem, transform)
    vals = {k: _sample_center(feats[k], lon, lat, transform)
            for k in ("slope", "aspect", "tpi", "flowacc")}
    vals["elevation_m"] = _sample_center(dem, lon, lat, transform)
    return vals, {"source": "nasadem_computed",
                  "note": "NASADEM 30m 现场计算 (TPI/汇流为局部窗口近似)"}


def _sample_center(arr, lon, lat, transform):
    """采样 arr 中最接近 (lon,lat) 的像素 (最近邻)"""
    r, c = rowcol(transform, lon, lat)
    r = int(np.clip(r, 0, arr.shape[0] - 1))
    c = int(np.clip(c, 0, arr.shape[1] - 1))
    v = float(arr[r, c])
    return v if np.isfinite(v) else None


def window_around(lon, lat, root, half_deg=0.015):
    """点周围窗口: 返回 (dem, transform, feats, bounds)

    Meijiawu 网格内直接切取现有栅格 (含预计算汇流, 最准确);
    网格外下载 NASADEM 瓦片现场计算。
    """
    bounds = (lon - half_deg, lat - half_deg, lon + half_deg, lat + half_deg)
    grid_dir = os.path.join(root, "data", "terrain", "meijiawu")
    if _in_meijiawu(lon, lat, pad=half_deg):
        with rasterio.open(os.path.join(grid_dir, "dem_30m.tif")) as s:
            win = from_bounds(*bounds, s.transform)
            dem = s.read(1, window=win).astype(np.float64)
            transform = s.window_transform(win)
        dem[dem == NODATA_I16] = np.nan
        feats = {}
        for name in ("slope", "aspect", "hillshade", "tpi_330m", "flowacc"):
            with rasterio.open(os.path.join(grid_dir, name + ".tif")) as s:
                win = from_bounds(*bounds, s.transform)
                arr = s.read(1, window=win).astype(np.float64)
                arr[~np.isfinite(arr)] = np.nan
                arr[arr == -9999.0] = np.nan
                feats[name.replace("tpi_330m", "tpi")] = arr
        return dem, transform, feats, bounds, "meijiawu_grid"
    # 慢路径: 现场计算
    tile = ensure_nasadem_tile(lat, lon, os.path.join(root, "data", "terrain"))
    dem, transform = extract_window(tile, bounds)
    feats = terrain_features(dem, transform)
    return dem, transform, feats, bounds, "nasadem_computed"
