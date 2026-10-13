"""Open-Meteo 实时数据接入: 拉取最近 N 天逐小时实况作为模型输入。

用途: 让大盘与地图页的"当前状况/近期实况"随线上数据滚动更新, 而不是固定 CSV。
输出与 models/predict.read_inputs(open-meteo) 同构: (bg, lab) 标准表, 北京时间(naive)。
数据不足或网络失败时抛异常, 由调用方回退本地 CSV。
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import requests

FORECAST_API = "https://api.open-meteo.com/v1/forecast"

# Open-Meteo 变量 -> 标准列名(与 models/predict.OM_COLS 同构)
VARIABLE_MAP = {
    "temperature_2m": "t2m",
    "dew_point_2m": "d2m",
    "precipitation": "tp",
    "soil_temperature_0cm": "stl1",
    "soil_temperature_6cm": "stl2",
    "soil_temperature_18cm": "stl3",
    "soil_moisture_1_to_3cm": "swvl1",
    "soil_moisture_3_to_9cm": "swvl2",
    "apparent_temperature": "ap_temp",
    "evapotranspiration": "et0",
}
OBS_MAP = {
    "temperature_2m": "obs_t2m",
    "relative_humidity_2m": "obs_rh",
}

MIN_HOURS = 72  # 少于 3 天历史时特征暖机不足, 视为不可用


def fetch_openmeteo_inputs(lat: float, lon: float, past_days: int = 6,
                           timeout: int = 30) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """拉取 Open-Meteo 最近 past_days 天逐小时数据(截至当前整点)。

    返回 (bg, lab, meta); meta 含 fetched_at / elevation / last_hour 等来源信息。
    """
    params = {
        "latitude": lat, "longitude": lon,
        "hourly": ",".join(list(VARIABLE_MAP) + ["relative_humidity_2m"]),
        "past_days": past_days,
        "forecast_days": 1,
        "timezone": "Asia/Shanghai",
    }
    resp = requests.get(FORECAST_API, params=params, timeout=timeout)
    if resp.status_code != 200:
        raise RuntimeError(f"Open-Meteo HTTP {resp.status_code}")
    payload = resp.json()
    hourly = payload.get("hourly") or {}
    if "time" not in hourly:
        raise RuntimeError("Open-Meteo 返回缺少 hourly.time")

    df = pd.DataFrame(hourly)
    df["time"] = pd.to_datetime(df["time"], errors="coerce")
    df = df.dropna(subset=["time"]).set_index("time").sort_index()
    now = pd.Timestamp.now().floor("h")
    df = df[df.index <= now]  # 只保留已发生的时刻(截至当前整点); 未来小时由本地模型预测
    if len(df) < MIN_HOURS:
        raise RuntimeError(f"实时数据不足: 仅 {len(df)} 小时 (<{MIN_HOURS})")

    bg = pd.DataFrame({std: df[src] for src, std in VARIABLE_MAP.items() if src in df.columns})
    lab = pd.DataFrame({std: df[src] for src, std in OBS_MAP.items() if src in df.columns})
    meta = {
        "fetched_at": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M"),
        "latitude": payload.get("latitude"),
        "longitude": payload.get("longitude"),
        "elevation": payload.get("elevation"),
        "hours": int(len(df)),
        "last_hour": str(df.index[-1]),
    }
    return bg, lab, meta


# ============================================================
# 茶园传感器数据接入(与 Open-Meteo 气象站数据互补)
# 定位: 气象站 API = 区域背景场, 传感器 = 茶园点位实测;
#   预报输入融合策略: 传感器实况锚定(若上传) + 气象站背景场兜底缺口。
# ============================================================

SENSOR_DIR = Path(__file__).resolve().parents[1] / "data" / "sensor"
SENSOR_CSV = SENSOR_DIR / "latest.csv"
SENSOR_META = SENSOR_DIR / "latest.json"

# 上传 CSV 的列名兼容表(大小写/中英文/单位后缀均可识别)
SENSOR_COL_ALIASES = {
    "time": ("time", "时间", "datetime", "date_time", "timestamp", "观测时间", "记录时间"),
    "obs_t2m": ("obs_t2m", "temp", "temperature", "temperature_2m", "气温", "温度", "空气温度", "t2m"),
    "obs_rh": ("obs_rh", "rh", "humidity", "relative_humidity", "湿度", "相对湿度", "空气湿度"),
    "obs_ws": ("obs_ws", "ws", "wind_speed", "wind_speed_10m", "风速"),
    "obs_wd": ("obs_wd", "wd", "wind_direction", "wind_direction_10m", "风向"),
    "soil_temp": ("soil_temp", "soil_temperature", "土壤温度", "土温"),
    "soil_moisture": ("soil_moisture", "swvl1", "土壤湿度", "土壤水分", "含水量"),
}


def _normalize_col(c: str) -> str:
    """列名归一化: 小写、去空白、去括号单位(如 '温度(℃)' -> '温度')。"""
    s = str(c).strip().lower()
    for ch in ("(", "（", "[", "【"):
        if ch in s:
            s = s.split(ch)[0]
    return s.strip()


def parse_sensor_csv(data: bytes) -> tuple[pd.DataFrame, dict]:
    """解析上传的传感器 CSV -> (标准列名 DataFrame, meta)。

    兼容中英文列名与常见单位后缀; 时间列必需, 至少要有气温列。
    逐小时重采样(高频数据取小时均值), 返回列: time 索引 + obs_t2m 等。
    """
    import io
    try:
        df = pd.read_csv(io.BytesIO(data))
    except Exception as e:  # noqa: BLE001
        raise ValueError(f"CSV 解析失败: {e}") from e
    if df.empty:
        raise ValueError("CSV 内容为空")
    # 列名映射
    rename = {}
    for std, aliases in SENSOR_COL_ALIASES.items():
        for col in df.columns:
            if _normalize_col(col) in aliases:
                rename[col] = std
                break
    df = df.rename(columns=rename)
    if "time" not in df.columns:
        raise ValueError("缺少时间列(支持: time / 时间 / timestamp 等)")
    if "obs_t2m" not in df.columns:
        raise ValueError("缺少气温列(支持: temp / temperature / 气温 / 温度 等)")
    df["time"] = pd.to_datetime(df["time"], errors="coerce")
    df = df.dropna(subset=["time"]).set_index("time").sort_index()
    df = df[~df.index.duplicated(keep="last")]
    keep = [c for c in ("obs_t2m", "obs_rh", "obs_ws", "obs_wd", "soil_temp", "soil_moisture")
            if c in df.columns]
    df = df[keep].apply(pd.to_numeric, errors="coerce")
    df = df.dropna(how="all")
    if df.empty:
        raise ValueError("数据行全部无效(请检查数值格式)")
    df = df.resample("1h").mean(numeric_only=True)
    meta = {
        "rows_raw": int(len(df.dropna(how="all"))),
        "rows_hourly": int(df.dropna(how="all").shape[0]),
        "time_from": str(df.index.min()),
        "time_to": str(df.index.max()),
        "columns": keep,
    }
    return df, meta


def save_sensor(data: bytes, meta: dict) -> None:
    """保存上传的传感器数据(原始 CSV 字节 + 元信息), 供模型输入使用。"""
    SENSOR_DIR.mkdir(parents=True, exist_ok=True)
    SENSOR_CSV.write_bytes(data)
    import json as _json
    SENSOR_META.write_text(_json.dumps(meta, ensure_ascii=False, indent=2),
                           encoding="utf-8")


def clear_sensor() -> None:
    """移除已上传的传感器数据(预报输入回到纯 Open-Meteo 气象站)。"""
    for p in (SENSOR_CSV, SENSOR_META):
        try:
            p.unlink(missing_ok=True)
        except OSError:
            pass


def load_sensor() -> tuple[pd.DataFrame, dict] | None:
    """读取已上传的传感器数据(标准化); 无数据返回 None。"""
    if not SENSOR_CSV.exists():
        return None
    data = SENSOR_CSV.read_bytes()
    try:
        df, meta_parsed = parse_sensor_csv(data)
    except ValueError:
        return None
    import json as _json
    meta = _json.loads(SENSOR_META.read_text(encoding="utf-8")) if SENSOR_META.exists() else {}
    meta.update(meta_parsed)
    return df, meta


def merge_sensor_into_inputs(bg: pd.DataFrame, lab: pd.DataFrame,
                             sensor: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """传感器实测与气象站背景场融合(互补策略)。

    - 传感器覆盖的时段: obs_t2m/obs_rh 用实测值替换(实测锚定);
    - 传感器未覆盖的时段: 保留 Open-Meteo 气象站值(背景场兜底);
    - 传感器独有的土壤观测: 并入背景场表(补充气象站缺失的本地信息);
    - 超出当前时刻的传感器行(不可能是观测)截断, 保证起报点不漂移到未来。
    返回 (bg, lab, 融合统计)。
    """
    now = pd.Timestamp.now().floor("h")
    sensor = sensor[sensor.index <= now]
    idx = lab.index.union(sensor.index)
    lab = lab.reindex(idx)
    bg = bg.reindex(idx)
    stats = {"anchored_hours": 0, "station_hours": 0, "soil_from_sensor": []}
    for col in ("obs_t2m", "obs_rh"):
        if col in sensor.columns:
            s = sensor[col].reindex(idx)
            mask = s.notna()
            lab.loc[mask, col] = s[mask]
            stats["anchored_hours"] = int(mask.sum())
    stats["station_hours"] = int(lab["obs_t2m"].notna().sum() - stats["anchored_hours"]) \
        if "obs_t2m" in lab.columns else 0
    for scol, bcol in (("soil_temp", "stl1"), ("soil_moisture", "swvl1")):
        if scol in sensor.columns and sensor[scol].notna().any():
            v = sensor[scol].reindex(idx)
            bg[bcol] = v.combine_first(bg[bcol]) if bcol in bg.columns else v
            stats["soil_from_sensor"].append(scol)
    # 传感器时间轴超出气象站覆盖范围时, 尾部补齐(气温列)
    return bg, lab, stats
