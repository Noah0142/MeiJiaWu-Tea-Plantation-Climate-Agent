"""霜冻 / 高温热害 / 倒春寒风险分级(纯函数, 推理与 Agent 共用)。

阈值依据(已核实):
- 春霜冻: 日最低温 ≤4℃ 为临界; 分级 2~4 轻 / 0~2 中 / <0 重
- 高温热害: 日最高温 ≥35℃ 或 日均温 ≥30℃ 持续
- 浙江倒春寒: 4 月出现连续 3 天日均温 <11℃
"""
from __future__ import annotations

import pandas as pd


def grade_frost(tmin: float | None):
    if tmin is None:
        return None, "无预报"
    if tmin < 0.0:
        return 3, "重度霜冻(最低温<0℃): 芽叶受冻面积可达 50% 以上, 建议立即覆盖/熏烟"
    if tmin < 2.0:
        return 2, "中度霜冻(0~2℃): 受冻面积 20%~50%, 建议覆盖防霜布"
    if tmin <= 4.0:
        return 1, "轻度霜冻(2~4℃): 嫩叶叶尖或边缘受冻, 关注凌晨低温"
    return 0, "无霜冻风险"


def grade_heat(tmax: float | None, tmean: float | None):
    if tmax is None:
        return None, "无预报"
    if tmax >= 35.0 and tmean is not None and tmean >= 30.0:
        return 3, "重度高温热害(最高≥35℃且日均≥30℃): 新梢灼伤, 建议遮荫+早晚喷灌"
    if tmax >= 35.0 or (tmean is not None and tmean >= 30.0):
        return 2, "中度高温热害: 芽叶生长受抑, 建议遮荫、增加土壤水分"
    if tmax >= 33.0:
        return 1, "高温关注(最高≥33℃): 注意墒情, 连续晴热需提前灌溉"
    return 0, "无高温热害风险"


def check_coldspell(daily_mean: pd.Series, threshold: float = 11.0) -> list[str]:
    """浙江标准倒春寒: 4 月连续 3 天日均温 < 阈值, 返回触发日期列表。"""
    apr = daily_mean[daily_mean.index.month == 4].dropna()
    if len(apr) < 3:
        return []
    dates = []
    for i in range(len(apr) - 2):
        w = apr.iloc[i:i + 3]
        consecutive = (w.index.to_series().diff().dt.days == 1).iloc[1:].all()
        if consecutive and w.mean() < threshold:
            dates.append(str(w.index[0].date()))
    return dates


def risk_card(fc: pd.DataFrame, cfg: dict) -> dict:
    """由 0–72h 分位数预报生成风险卡片。

    fc: index=时间, 至少含 t2m_p10 / t2m_p50 / t2m_p90 列。
    """
    r = cfg["risk"]
    windows = {}
    for hours in (24, 48, 72):
        seg = fc.iloc[:hours] if len(fc) >= hours else fc
        tmin10 = float(seg["t2m_p10"].min())
        tmin50 = float(seg["t2m_p50"].min())
        tmax90 = float(seg["t2m_p90"].max())
        tmean50 = float(seg["t2m_p50"].mean())
        g, msg = grade_frost(tmin50)
        gc, msgc = grade_frost(tmin10)
        hg, hmsg = grade_heat(tmax90, tmean50)
        windows[f"{hours}h"] = {
            "tmin_p50": round(tmin50, 1),
            "tmin_p10": round(tmin10, 1),
            "tmax_p90": round(tmax90, 1),
            "frost_grade": g, "frost_note": msg,
            "frost_grade_conservative": gc, "frost_note_conservative": msgc,
            "heat_grade": hg, "heat_note": hmsg,
        }
    daily_mean = fc["t2m_p50"].resample("1D").mean()
    return {
        "windows": windows,
        "coldspell_april_dates": check_coldspell(daily_mean, float(r["coldspell_apr_mean"])),
    }
