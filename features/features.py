"""特征工程: 对齐后的逐小时表 -> 训练/推理特征。

支持两类"空间上下文"(对标绍兴御茶村 40+6 站立体监测网):
1. 多格点背景场: 最近格点(无后缀, 即 c1)+ 周边格点(列名加 _c2.._cN 后缀)
   -> 每格点注入 bg_*_plus_h, 并聚合出邻域均值/极值特征。
2. 多站实况网络: 目标站自身实况(obs_*) + 邻站实况(obs_t2m_nb1..nbK)
   -> 邻站协同特征(当前值 + 24h 滞后), 解决时空数据协同问题。

防泄漏原则:
- 所有特征只用"当前时刻 t 及以前"的信息。
- bg_*_plus_h 由 build_dataset/infer 按时效平移注入, 训练时等于再分析在
  t+h 的值("完美预报"假设), 运行时由数值预报提供 —— MOS 降尺度标准做法。
"""
from __future__ import annotations

import re

import numpy as np
import pandas as pd

MAGNUS_A, MAGNUS_B = 17.62, 243.12

BG_VARS = ("t2m", "d2m", "rh", "u10", "v10", "ssr", "tp", "stl1", "swvl1", "sp")
BG_CELL_RE = re.compile(r"^(" + "|".join(BG_VARS) + r")_(c\d+)$")


def rh_from_t_td(t_c, td_c):
    """由气温与露点计算相对湿度(Magnus 公式, ℃)。Series/ndarray 均可。"""
    es_t = 6.112 * np.exp(MAGNUS_A * t_c / (t_c + MAGNUS_B))
    es_td = 6.112 * np.exp(MAGNUS_A * td_c / (td_c + MAGNUS_B))
    return np.clip(100.0 * es_td / es_t, 0.0, 100.0)


def _harmonics(s, period: float, order: int = 2) -> pd.DataFrame:
    """正弦/余弦谐波特征。s 可为 Series / Index / ndarray。"""
    s = np.asarray(s, dtype=float)
    out = {}
    for k in range(1, order + 1):
        ang = 2 * np.pi * k * s / period
        out[f"sin{k}"] = np.sin(ang)
        out[f"cos{k}"] = np.cos(ang)
    return pd.DataFrame(out)


# ---------------------------------------------------------------- 背景场(多格点)

def bg_cell_table(bg: pd.DataFrame, suffix: str) -> pd.DataFrame:
    """单格点诊断量表: bg_t2m / bg_rh / bg_ws / bg_tp12 ... (列名含格点后缀时取该格点)。"""
    out = pd.DataFrame(index=bg.index)

    def col(name: str) -> str:
        return name + suffix

    if col("t2m") not in bg.columns:
        return out
    out["bg_t2m"] = bg[col("t2m")]
    if col("d2m") in bg.columns:
        out["bg_d2m"] = bg[col("d2m")]
        out["bg_rh"] = rh_from_t_td(bg[col("t2m")], bg[col("d2m")])
    elif col("rh") in bg.columns:
        out["bg_rh"] = bg[col("rh")]
    if col("u10") in bg.columns and col("v10") in bg.columns:
        out["bg_ws"] = np.hypot(bg[col("u10")], bg[col("v10")])
    for c in ("ssr", "stl1", "swvl1", "sp"):
        if col(c) in bg.columns:
            out[f"bg_{c}"] = bg[col(c)]
    if col("tp") in bg.columns:
        out["bg_tp12"] = bg[col("tp")].rolling("12h").sum()
        out["bg_tp24"] = bg[col("tp")].rolling("24h").sum()
    return out


def bg_cell_tables(bg: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """bg 原始表(含 _cN 后缀列)-> {cell_id: 诊断量表}。c1 = 无后缀的最近格点。"""
    tables = {"c1": bg_cell_table(bg, "")}
    for m in sorted({m.group(2) for m in (BG_CELL_RE.match(c) for c in bg.columns) if m}):
        tables[m] = bg_cell_table(bg, "_" + m)
    return tables


def compute_climatology(bg_t2m: pd.Series) -> pd.Series:
    """多年逐日气候态: 日平均背景场气温按 dayofyear 取中位数。只允许用训练时段计算。"""
    daily = bg_t2m.resample("1D").mean()
    return daily.groupby(daily.index.dayofyear).median()


def plus_h_features(bgd: dict[str, pd.DataFrame], base_t: pd.DatetimeIndex, h: int) -> pd.DataFrame:
    """按时效 h 平移注入背景场特征(逐行, index=base_t):

    - 每格点: bg_*_plus_h(bg_*_plus_h_cN)
    - 邻域聚合: cells_*_mean/min/max_plus_h(所有格点)
    """
    shifted = {}
    for cid, t in bgd.items():
        for c in t.columns:
            shifted[(cid, c)] = t[c].shift(-h).reindex(base_t).to_numpy()
    out = pd.DataFrame(index=base_t)
    for cid, t in bgd.items():
        for c in t.columns:
            name = c + "_plus_h" if cid == "c1" else f"{c}_plus_h_{cid}"
            out[name] = shifted[(cid, c)]
    common = set(bgd["c1"].columns)
    for t in bgd.values():
        common &= set(t.columns)
    for c in sorted(common):
        vals = np.stack([shifted[(cid, c)] for cid in bgd], axis=0)
        base = c.replace("bg_", "")
        out[f"cells_{base}_mean_plus_h"] = np.nanmean(vals, axis=0)
        out[f"cells_{base}_min_plus_h"] = np.nanmin(vals, axis=0)
        out[f"cells_{base}_max_plus_h"] = np.nanmax(vals, axis=0)
    return out


# ---------------------------------------------------------------- 主特征

def build_features(df: pd.DataFrame, cfg: dict, clim: pd.Series | None = None) -> pd.DataFrame:
    """主特征构造。

    df: index=DatetimeIndex(逐小时), 含:
      - 背景场(最近格点标准名 t2m 等 + 周边格点 t2m_cN 等)
      - 目标站实况 obs_t2m / obs_rh / obs_ws / obs_wd
      - 邻站实况 obs_t2m_nb{i}(可选)
      - 静态地形列(由 make_station_wide 并入: elevation/slope/aspect_sin/...)
    clim: doy -> 背景场气温气候态(可 None, 距平置 0)。
    """
    feats = pd.DataFrame(index=df.index)
    hour = (df.index.hour + df.index.minute / 60.0).to_numpy()
    doy = (df.index.dayofyear + df.index.hour / 24.0).to_numpy()

    hh = _harmonics(hour, 24.0, 2).add_prefix("hour_")
    dd = _harmonics(doy, 365.25, 2).add_prefix("doy_")
    hh.index, dd.index = df.index, df.index
    feats = pd.concat([feats, hh, dd], axis=1)
    feats["frost_window"] = ((doy >= 32.0) & (doy <= 120.0)).astype(np.int8)
    feats["heat_window"] = ((doy >= 182.0) & (doy <= 243.0)).astype(np.int8)

    # ---- 背景场(最近格点, 时刻 t) ----
    if "u10" in df.columns and "v10" in df.columns:
        feats["bg_ws"] = np.hypot(df["u10"], df["v10"])
    if "d2m" in df.columns:
        feats["bg_rh"] = rh_from_t_td(df["t2m"], df["d2m"])
    elif "rh" in df.columns:
        feats["bg_rh"] = df["rh"]
    feats["bg_diurnal"] = df["t2m"].rolling("24h").max() - df["t2m"].rolling("24h").min()
    if "tp" in df.columns:
        feats["bg_tp12"] = df["tp"].rolling("12h").sum()
        feats["bg_tp24"] = df["tp"].rolling("24h").sum()
    # 深层土壤/皮肤温度/辐射等背景量(自监督模式的关键预报因子)
    for c in ("ssr", "tp", "skt", "stl1", "stl2", "stl3", "stl4",
              "swvl1", "swvl2", "swvl3", "swvl4"):
        if c in df.columns:
            feats[f"bg_{c}"] = df[c]
    if clim is not None:
        clim_at = pd.Series(df.index.dayofyear, index=df.index).map(clim)
        feats["bg_anom"] = df["t2m"] - clim_at
    else:
        feats["bg_anom"] = 0.0

    # ---- 空间上下文: 周边格点聚合(时刻 t) ----
    cell_cols = sorted(c for c in df.columns if re.match(r"^t2m_c\d+$", c))
    if cell_cols:
        cell_t = df[["t2m"] + cell_cols]
        feats["cells_t2m_mean"] = cell_t.mean(axis=1)
        feats["cells_t2m_min"] = cell_t.min(axis=1)
        feats["cells_t2m_max"] = cell_t.max(axis=1)
        feats["cells_t2m_std"] = cell_t.std(axis=1)

    # ---- 目标站实况(当前与滞后, 严格因果) ----
    feats["obs_t2m"] = df["obs_t2m"]
    for lag in (1, 3, 6, 12, 24, 48):
        feats[f"obs_t2m_lag{lag}"] = df["obs_t2m"].shift(lag)
    feats["obs_tmin24"] = df["obs_t2m"].rolling("24h").min()
    feats["obs_tmax24"] = df["obs_t2m"].rolling("24h").max()
    feats["obs_bg_bias24"] = (df["obs_t2m"] - df["t2m"]).rolling("24h").mean()
    if "obs_rh" in df.columns:
        feats["obs_rh"] = df["obs_rh"]
        feats["obs_rh_lag24"] = df["obs_rh"].shift(24)
    if "obs_ws" in df.columns:
        feats["obs_ws"] = df["obs_ws"]
        feats["obs_ws_lag24"] = df["obs_ws"].shift(24)

    # ---- 邻站协同特征(当前值 + 24h 滞后) ----
    for c in sorted(x for x in df.columns if re.match(r"^obs_t2m_nb\d+$", x)):
        feats[c] = df[c]
        feats[c + "_lag24"] = df[c].shift(24)

    # ---- 静态地形/土地覆盖(由 make_station_wide 并入) ----
    for c in ("elevation", "slope", "aspect_sin", "aspect_cos", "tpi", "cai", "elev_delta",
              "tea_1km", "tea_3km", "tea_5km", "tea_10km", "dist_tea_km"):
        feats[c] = df[c].astype(float) if c in df.columns else 0.0

    return feats
