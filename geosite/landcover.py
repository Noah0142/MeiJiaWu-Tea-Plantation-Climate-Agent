# -*- coding: utf-8 -*-
"""
geosite/landcover.py — ESA WorldCover 10m 土地覆盖 (Planetary Computer, 免注册)
==============================================================================
按需窗口读取: STAC 搜索 → SAS 签名 → rasterio 对签名 URL 窗口读取 → 本地缓存。
失败时优雅降级返回 None (调用方标注"土地覆盖未知"), 不影响主流程。
"""
import os
import urllib.parse

import numpy as np
import rasterio
from rasterio.transform import rowcol
from rasterio.windows import from_bounds

from geosite.net import urlopen_json
from geosite.terrain import MEIJIAWU_BBOX

STAC_SEARCH = "https://planetarycomputer.microsoft.com/api/stac/v1/search"
SIGN_API = "https://planetarycomputer.microsoft.com/api/sas/v1/sign"

# ESA WorldCover 11 类 → 中文标签
WC_LABELS = {
    10: "林地", 20: "灌木", 30: "草地", 40: "农田", 50: "建筑",
    60: "裸地", 70: "冰雪", 80: "水体", 90: "草本湿地", 95: "红树林",
    100: "苔藓地衣",
}
# 茶园(多年生常绿灌木)在 WorldCover 中最常被分为林地/灌木/农田
TEA_FRIENDLY = {10, 20, 30, 40}


def _sign(href):
    url = SIGN_API + "?href=" + urllib.parse.quote(href, safe="")
    return urlopen_json(url, timeout=30)["href"]


def _search_item(bounds):
    """按 bbox 搜索 WorldCover item, 优先 2021 (v200)"""
    q = (STAC_SEARCH + "?collections=esa-worldcover&bbox={w},{s},{e},{n}"
         "&limit=4").format(w=bounds[0], s=bounds[1], e=bounds[2], n=bounds[3])
    feats = urlopen_json(q, timeout=60)["features"]
    if not feats:
        return None
    for f in feats:
        if "2021" in f["id"]:
            return f
    return feats[0]


def worldcover_window(bounds, cache_dir, key):
    """bounds(w,s,e,n) 窗口的 WorldCover → 本地缓存 tif 路径 (失败返回 None)"""
    os.makedirs(cache_dir, exist_ok=True)
    path = os.path.join(cache_dir, key + ".tif")
    if os.path.exists(path) and os.path.getsize(path) > 1000:
        return path
    try:
        item = _search_item(bounds)
        if item is None:
            return None
        signed = _sign(item["assets"]["map"]["href"])
        with rasterio.Env(GDAL_HTTP_UNSAFESSL="YES",
                          GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR"):
            with rasterio.open(signed) as src:
                win = from_bounds(*bounds, src.transform)
                arr = src.read(1, window=win)
                transform = src.window_transform(win)
                profile = src.profile.copy()
        profile.update(driver="GTiff", width=arr.shape[1],
                       height=arr.shape[0], transform=transform,
                       compress="deflate", nodata=None)
        with rasterio.open(path, "w", **profile) as dst:
            dst.write(arr, 1)
        print(f"[landcover] 窗口已缓存: {key} ({os.path.getsize(path):,} bytes)")
        return path
    except Exception as e:  # noqa: BLE001
        print(f"[landcover] 获取失败 (降级为未知): {e}")
        return None


def point_landcover(lon, lat, cache_dir):
    """单点土地覆盖 → (code, label) 或 None

    快路径: 梅家坞网格窗口 (首次获取一次 11x11km); 其他点按 0.05° 单元缓存。
    """
    in_grid = (MEIJIAWU_BBOX[0] <= lon <= MEIJIAWU_BBOX[2]
               and MEIJIAWU_BBOX[1] <= lat <= MEIJIAWU_BBOX[3])
    if in_grid:
        key, bounds = "meijiawu", MEIJIAWU_BBOX
    else:
        gx, gy = int(np.floor(lon * 20)) / 20, int(np.floor(lat * 20)) / 20
        key = f"wc_{gy:.2f}_{gx:.2f}"
        bounds = (gx, gy, gx + 0.05, gy + 0.05)
    path = worldcover_window(bounds, cache_dir, key)
    if path is None:
        return None
    with rasterio.open(path) as src:
        r, c = rowcol(src.transform, lon, lat)
        if not (0 <= r < src.height and 0 <= c < src.width):
            return None
        code = int(src.read(1)[r, c])
    return code, WC_LABELS.get(code, f"类别{code}")


def window_landcover_stats(bounds, cache_dir, key, mask=None):
    """窗口内土地覆盖构成 → {code: 占比%} 或 None (mask: 可选有效像元掩膜)"""
    path = worldcover_window(bounds, cache_dir, key)
    if path is None:
        return None
    with rasterio.open(path) as src:
        win = from_bounds(*bounds, src.transform)
        arr = src.read(1, window=win)
    codes, counts = np.unique(arr, return_counts=True)
    total = counts.sum()
    out = {}
    for code, cnt in zip(codes.tolist(), counts.tolist()):
        out[int(code)] = {"label": WC_LABELS.get(int(code), f"类别{code}"),
                          "pct": round(100.0 * cnt / total, 1)}
    return out


def stats_for_window(lon, lat, cache_dir, half_deg):
    """点周围窗口 (或梅家坞网格) 的土地覆盖构成"""
    in_grid = (MEIJIAWU_BBOX[0] <= lon <= MEIJIAWU_BBOX[2]
               and MEIJIAWU_BBOX[1] <= lat <= MEIJIAWU_BBOX[3])
    if in_grid:
        bounds, key = MEIJIAWU_BBOX, "meijiawu"
    else:
        gx, gy = int(np.floor(lon * 20)) / 20, int(np.floor(lat * 20)) / 20
        key = f"wc_{gy:.2f}_{gx:.2f}"
        bounds = (gx, gy, gx + 0.05, gy + 0.05)
    return window_landcover_stats(bounds, cache_dir, key)
