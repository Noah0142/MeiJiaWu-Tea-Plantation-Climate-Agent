# -*- coding: utf-8 -*-
"""
process_dem.py — 梅家坞茶园 DEM 裁剪 + 微气候地形特征工程
=========================================================
输入: data/terrain/nasadem_N30E120.tif (NASADEM 30m, 必需)
      data/terrain/srtm_61_06.tif    (CGIAR SRTM 90m, 可选, 用于交叉验证)
输出: data/terrain/meijiawu/
      dem_30m.tif        裁剪后的 DEM (int16, EPSG:4326)
      slope.tif          坡度 (度)
      aspect.tif         坡向 (0-360, 0=北, 顺时针)
      hillshade.tif      山体阴影 (0-255)
      tpi_330m.tif       地形位置指数 (11x11 邻域, 谷/脊判别)
      flowacc.tif        D8 汇流累积 (冷空气排水代理)
      diff_nasadem_srtm.tif  (可选) 两数据源差值
      terrain_preview.png    可视化总览
      stats.json         统计摘要

运行: py -3.9 scripts/process_dem.py   (rasterio 装在 Python 3.9 环境)
"""
import json
import os
import sys

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import rasterio
from rasterio.transform import rowcol
from rasterio.windows import from_bounds

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TERRAIN = os.path.join(BASE, "data", "terrain")
OUTDIR = os.path.join(TERRAIN, "meijiawu")
os.makedirs(OUTDIR, exist_ok=True)

# 梅家坞村中心坐标与裁剪范围 (含周边山脊, 保证汇流/冷空气分析流域完整)
VILLAGE = (120.084, 30.206)  # lon, lat
BBOX = (120.03, 30.16, 120.14, 30.26)  # west, south, east, north ~11x11 km

M_PER_DEG_LAT = 111320.0


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
    # 边界用 +inf 填充: 越界邻域自动视为无效流向
    dp = np.pad(dem.astype(np.float64), 1, mode="constant", constant_values=np.inf)
    drops = np.stack([dem - dp[1 + dr:1 + dr + h, 1 + dc:1 + dc + w]
                      for dr, dc in offs])
    d2 = np.where(np.isnan(drops), -np.inf, drops)
    d2[d2 <= 0] = -np.inf                       # 只沿下坡方向流动
    dirs = np.argmax(d2, axis=0)
    valid = np.isfinite(d2.max(axis=0))
    acc = np.ones((h, w), dtype=np.float64)
    order = np.argsort(dem.ravel())[::-1]       # 从高到低逐格累加
    for idx in order:
        r, c = divmod(int(idx), w)
        if not valid[r, c]:
            continue
        dr, dc = offs[int(dirs[r, c])]
        acc[r + dr, c + dc] += acc[r, c]
    return acc


def clip(src_path, dst_path, dtype="int16", nodata=-32768):
    """按 BBOX 裁剪并另存为 GeoTIFF"""
    with rasterio.open(src_path) as src:
        win = from_bounds(*BBOX, src.transform)
        data = src.read(1, window=win)
        profile = src.profile.copy()
        profile.update(
            driver="GTiff", width=win.width, height=win.height,
            transform=src.window_transform(win), dtype=dtype,
            nodata=nodata, compress="deflate",
        )
        with rasterio.open(dst_path, "w", **profile) as dst:
            dst.write(data.astype(dtype), 1)
    return data, profile["transform"]


def main():
    src_dem = os.path.join(TERRAIN, "nasadem_N30E120.tif")
    if not os.path.exists(src_dem):
        sys.exit("缺少数据, 先运行: py -3.9 scripts/download_terrain.py")

    # ---- 1. 裁剪 DEM ----
    dem_i16, transform = clip(src_dem, os.path.join(OUTDIR, "dem_30m.tif"))
    dem = dem_i16.astype(np.float64)
    dem[dem_i16 == -32768] = np.nan

    h, w = dem.shape
    res = transform.a  # 每像素度数 (1/3600)
    lats = transform.f + res * (np.arange(h) + 0.5)
    dx_m = res * M_PER_DEG_LAT * np.cos(np.radians(lats))[:, None]  # 东西向
    dy_m = res * M_PER_DEG_LAT                                   # 南北向

    # ---- 2. 坡度 / 坡向 / 山体阴影 ----
    dzdx = np.gradient(dem, axis=1) / dx_m   # 东西向坡度 (中心差分/米距)
    dzdy = np.gradient(dem, axis=0) / dy_m   # 南北向坡度
    slope_rad = np.arctan(np.hypot(dzdx, dzdy))
    slope = np.degrees(slope_rad)
    aspect = np.mod(np.degrees(np.arctan2(-dzdx, -dzdy)), 360.0)  # 下坡方向罗盘角

    az, alt = 315.0, 45.0
    hs = (np.sin(np.radians(alt)) * np.cos(slope_rad)
          + np.cos(np.radians(alt)) * np.sin(slope_rad)
          * np.cos(np.radians(az) - np.radians(aspect)))
    hillshade = np.clip(255.0 * (hs - hs.min()) / (hs.max() - hs.min()), 0, 255)

    # ---- 3. TPI 与汇流累积 ----
    tpi = dem - boxcar_mean(dem, 11)      # ~330 m 邻域
    flowacc = d8_flowacc(dem)

    # ---- 4. 写出 GeoTIFF ----
    profile = {"driver": "GTiff", "dtype": "float32", "nodata": np.nan,
               "width": w, "height": h, "count": 1, "crs": "EPSG:4326",
               "transform": transform, "compress": "deflate"}
    for name, arr in [("slope", slope), ("aspect", aspect),
                      ("hillshade", hillshade), ("tpi_330m", tpi),
                      ("flowacc", flowacc)]:
        with rasterio.open(os.path.join(OUTDIR, name + ".tif"), "w", **profile) as dst:
            dst.write(np.nan_to_num(arr, nan=-9999).astype("float32"), 1)

    # ---- 5. 可选: 与 CGIAR SRTM 交叉验证 ----
    diff_stats = None
    srtm_path = os.path.join(TERRAIN, "srtm_61_06.tif")
    if os.path.exists(srtm_path):
        try:
            srtm_arr, srtm_transform = clip(srtm_path,
                                            os.path.join(OUTDIR, "srtm_61_06_clip.tif"))
            from rasterio.warp import reproject, Resampling
            srtm_f = srtm_arr.astype(np.float64)
            srtm_f[srtm_arr == -32768] = np.nan
            srtm_rs = np.empty_like(dem)
            reproject(source=srtm_f, destination=srtm_rs,
                      src_transform=srtm_transform, dst_transform=transform,
                      src_crs="EPSG:4326", dst_crs="EPSG:4326",
                      src_nodata=np.nan, dst_nodata=np.nan,
                      resampling=Resampling.bilinear)
            diff = dem - srtm_rs
            with rasterio.open(os.path.join(OUTDIR, "diff_nasadem_srtm.tif"), "w",
                               **profile) as dst:
                dst.write(np.nan_to_num(diff, nan=-9999).astype("float32"), 1)
            mask = np.isfinite(diff)
            diff_stats = {"mean_abs_m": float(np.nanmean(np.abs(diff[mask]))),
                          "rmse_m": float(np.sqrt(np.nanmean(diff[mask] ** 2))),
                          "corr": float(np.corrcoef(dem[mask], srtm_rs[mask])[0, 1])}
        except Exception as e:
            print("SRTM 交叉验证跳过:", e)

    # ---- 6. 可视化 ----
    plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "sans-serif"]
    plt.rcParams["axes.unicode_minus"] = False
    fig, axes = plt.subplots(2, 2, figsize=(13, 11))
    extent = [BBOX[0], BBOX[2], BBOX[1], BBOX[3]]
    vrow, vcol = rowcol(transform, VILLAGE[0], VILLAGE[1])

    ax = axes[0, 0]
    im = ax.imshow(dem, extent=extent, cmap="terrain")
    cs = ax.contour(np.arange(w) * transform.a + transform.c,
                    np.arange(h) * transform.e + transform.f, dem,
                    levels=12, colors="k", linewidths=0.4, alpha=0.5)
    ax.scatter(*VILLAGE, marker="*", s=180, c="red", edgecolors="k", zorder=5,
               label="Meijiawu village")
    ax.set_title("Elevation + contours (m)")
    ax.legend(loc="lower right")
    fig.colorbar(im, ax=ax, shrink=0.8)

    im = axes[0, 1].imshow(slope, extent=extent, cmap="YlOrRd")
    axes[0, 1].set_title("Slope (deg)")
    fig.colorbar(im, ax=axes[0, 1], shrink=0.8)

    im = axes[1, 0].imshow(aspect, extent=extent, cmap="twilight")
    axes[1, 0].set_title("Aspect (downhill direction)")
    fig.colorbar(im, ax=axes[1, 0], shrink=0.8)

    im = axes[1, 1].imshow(np.log1p(flowacc), extent=extent, cmap="Blues")
    axes[1, 1].set_title("Log flow accumulation (cold-air drainage proxy)")
    fig.colorbar(im, ax=axes[1, 1], shrink=0.8)

    fig.suptitle("Meijiawu Tea Garden Terrain Features (NASADEM 30 m)", fontsize=14)
    fig.tight_layout()
    png_path = os.path.join(OUTDIR, "terrain_preview.png")
    fig.savefig(png_path, dpi=150)
    plt.close(fig)

    # ---- 7. 统计摘要 ----
    stats = {
        "village": {"lon": VILLAGE[0], "lat": VILLAGE[1],
                    "elev_m": float(dem[vrow, vcol])},
        "bbox": list(BBOX),
        "grid": {"cols": w, "rows": h, "res_m": round(res * M_PER_DEG_LAT, 2)},
        "elevation_m": {"min": float(np.nanmin(dem)), "max": float(np.nanmax(dem)),
                        "mean": float(np.nanmean(dem))},
        "slope_deg": {"mean": float(np.nanmean(slope)),
                      "max": float(np.nanmax(slope))},
        "flowacc": {"max": float(np.nanmax(flowacc))},
        "srtm_crosscheck": diff_stats,
        "outputs": sorted(os.listdir(OUTDIR)),
    }
    with open(os.path.join(OUTDIR, "stats.json"), "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)
    print(json.dumps(stats, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
