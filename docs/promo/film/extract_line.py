# -*- coding: utf-8 -*-
"""extract_line.py — 为影片抽取"那条线"的真实数据

- 山脊剖面: NASADEM 30m 沿梅家坞对角横断面(rasterio 采样, 145 点)
- 气温曲线: /api/forecast 的真实 t2m_p50 / p10 / p90 (72h → 145 点重采样)
产出: docs/promo/film/assets/data.js 与 data_preview.png
"""
import json
import pathlib

import numpy as np
import rasterio
from PIL import Image, ImageDraw

ROOT = pathlib.Path(__file__).resolve().parents[3]
OUT = ROOT / "docs" / "promo" / "film" / "assets"
N = 145

# ---- 1. DEM 横断面 -------------------------------------------------------
A = (30.250, 120.045)   # 西北(山) 
B = (30.175, 120.130)   # 东南(谷/城)
lons = np.linspace(A[1], B[1], N)
lats = np.linspace(A[0], B[0], N)
with rasterio.open(ROOT / "data" / "terrain" / "meijiawu" / "dem_30m.tif") as src:
    prof = np.array([v[0] for v in src.sample(zip(lons, lats))], dtype=float)
prof[prof == -32768] = np.nan
# 平滑一点, 保留形态(9 点滑动平均, 端点保持)
k = 9
pad = np.r_[np.full(k // 2, prof[0]), prof, np.full(k // 2, prof[-1])]
prof_s = np.convolve(pad, np.ones(k) / k, mode="valid")

# ---- 2. 真实预报曲线 -----------------------------------------------------
fc = json.loads((OUT / "forecast.json").read_text(encoding="utf-8"))["hourly"]
t50 = np.array([r["t2m_p50"] for r in fc], dtype=float)
# 原始数据头两小时 p10/p90 与 p50 不自洽(不同 horizon 混排), 按分位数定义收拢到包含中位数
lo = np.minimum(np.minimum(np.array([r["t2m_p10"] for r in fc]), np.array([r["t2m_p90"] for r in fc])), t50)
hi = np.maximum(np.maximum(np.array([r["t2m_p10"] for r in fc]), np.array([r["t2m_p90"] for r in fc])), t50)


def resample(a, n):
    x = np.linspace(0, 1, len(a))
    return np.interp(np.linspace(0, 1, n), x, a)


def smooth(a, k=7):
    p = np.r_[np.full(k // 2, a[0]), a, np.full(k // 2, a[-1])]
    return np.convolve(p, np.ones(k) / k, mode="valid")


T50 = smooth(resample(t50, N), 9)
T10 = smooth(resample(lo, N), 9)
T90 = smooth(resample(hi, N), 9)

print("剖面 m: min %.0f max %.0f  (前10点 %s)" % (np.nanmin(prof_s), np.nanmax(prof_s),
      np.round(prof_s[:10]).astype(int).tolist()))
print("T50 ℃: %.1f … %.1f   区间最大宽 %.1f" % (T50.min(), T50.max(), (T90 - T10).max()))
ok = ((T10 <= T50 + 0.05) & (T50 <= T90 + 0.05)).mean()
print("区间包含中位数比例 %.2f" % ok)

data = {
    "prof": [round(float(v), 1) for v in prof_s],
    "t50": [round(float(v), 2) for v in T50],
    "t10": [round(float(v), 2) for v in T10],
    "t90": [round(float(v), 2) for v in T90],
    "issued": json.loads((OUT / "forecast.json").read_text(encoding="utf-8"))["issued_at"],
}
(OUT / "data.js").write_text("window.LINE = " + json.dumps(data, ensure_ascii=False) + ";\n",
                             encoding="utf-8")
print("data.js:", (OUT / "data.js").stat().st_size, "B")

# ---- 3. 预览(人看) -------------------------------------------------------
W, H = 1520, 420
im = Image.new("RGB", (W + 80, H + 60), (248, 247, 241))
d = ImageDraw.Draw(im)
def yy(v, v0, v1, top, bot):
    return bot - (v - v0) / (v1 - v0) * (bot - top)
p0, p1 = np.nanmin(prof_s), np.nanmax(prof_s)
pts = [(40 + i / (N - 1) * W, yy(v, p0, p1, 20, 400)) for i, v in enumerate(prof_s)]
d.line(pts, fill=(38, 117, 67), width=4)
t0, t1 = 2, 26
tp = [(40 + i / (N - 1) * W, yy(v, t0, t1, 20, 400)) for i, v in enumerate(T50)]
bp = [(40 + i / (N - 1) * W, yy(v, t0, t1, 20, 400)) for i, v in enumerate(T10)][::-1]
up = [(40 + i / (N - 1) * W, yy(v, t0, t1, 20, 400)) for i, v in enumerate(T90)][::-1]
d.polygon(bp + up, fill=(180, 205, 185))
d.line(tp, fill=(38, 117, 67), width=4)
yth = yy(2, t0, t1, 20, 400)
d.line([(40, yth), (W + 40, yth)], fill=(201, 47, 51), width=3)
im.save(OUT / "data_preview.png")
print("preview saved")
