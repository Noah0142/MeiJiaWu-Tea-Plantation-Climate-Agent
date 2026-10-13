"""梅家坞茶园微气候 Agent · Web 服务

- 静态页面: web/static/(基于 microclimate-sensor-network 的 Pico+ECharts 模板)
- GET  /api/forecast   模型 0-72h 微气候预报(近 48h 实况 + 逐小时 P10/P50/P90 + 风险卡片)
- GET  /api/summary    农事建议(LLM 或规则兜底)
- POST /api/chat       农户多轮对话 {messages: [{role, content}]} -> {reply}

LLM 配置(按优先级): agent/.env 文件 > 环境变量 > 免费无密钥通道 > 规则兜底。
  免费无密钥: Pollinations(额度小, 易限流);
  免费有密钥(推荐, 国内直连): 智谱 GLM-4-Flash / SiliconFlow 免费模型(见 agent/.env.example)。
运行:
  pip install fastapi uvicorn
  python agent/server.py            # http://127.0.0.1:8000
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd
import yaml
import requests
from fastapi import FastAPI, UploadFile
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# 本机网络栈直连 IPv6 会超时(实测 curl 走 IPv4 正常), 强制 requests 使用 IPv4
import socket
import urllib3.util.connection as _urllib3_conn

_urllib3_conn.allowed_gai_family = lambda: socket.AF_INET


def _load_env_file():
    """读取 agent/.env(KEY=VALUE 每行一个), 不覆盖已存在的环境变量。"""
    env_file = Path(__file__).resolve().parent / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        os.environ.setdefault(key.strip(), val.strip())


_load_env_file()

from models.predict import load_predictor, read_inputs, run_forecast

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "web" / "static"
SENSOR_CSV = os.environ.get("SENSOR_CSV", str(ROOT / "training_data" / "open-meteo-30.19N120.11E180m.csv"))
LLM_API_KEY = os.environ.get("LLM_API_KEY", "")
LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "")
LLM_MODEL = os.environ.get("LLM_MODEL", "")
LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "")

# 免费 LLM 供应商预设(OpenAI 兼容)。无配置时走 pollinations(免费、无需密钥)。
LLM_PROVIDERS = {
    "deepseek": {"base": "https://api.deepseek.com", "model": "deepseek-chat", "label": "DeepSeek"},
    "siliconflow": {"base": "https://api.siliconflow.cn/v1", "model": "Qwen/Qwen2.5-7B-Instruct",
                    "label": "SiliconFlow 免费模型"},
    "zhipu": {"base": "https://open.bigmodel.cn/api/paas/v4", "model": "glm-4-flash",
              "label": "智谱 GLM-4-Flash(免费)"},
    "groq": {"base": "https://api.groq.com/openai/v1", "model": "llama-3.3-70b-versatile",
             "label": "Groq 免费额度"},
    "openrouter": {"base": "https://openrouter.ai/api/v1", "model": "meta-llama/llama-3.3-70b-instruct:free",
                   "label": "OpenRouter 免费模型"},
    "pollinations": {"base": "https://text.pollinations.ai", "model": "openai",
                     "path": "/openai", "label": "Pollinations(免费, 无需密钥)", "keyless": True},
}


def _llm_endpoint() -> dict:
    """解析 LLM 端点: 显式 env > 供应商预设 > 免费无密钥通道。"""
    if LLM_BASE_URL and LLM_MODEL:
        return {"base": LLM_BASE_URL.rstrip("/"), "model": LLM_MODEL, "path": "/chat/completions",
                "key": LLM_API_KEY, "label": LLM_MODEL}
    if LLM_PROVIDER in LLM_PROVIDERS:
        p = LLM_PROVIDERS[LLM_PROVIDER]
        return {"base": p["base"], "model": p["model"], "path": p.get("path", "/chat/completions"),
                "key": "" if p.get("keyless") else LLM_API_KEY, "label": p["label"]}
    p = LLM_PROVIDERS["pollinations"]
    return {"base": p["base"], "model": p["model"], "path": p.get("path", "/chat/completions"),
            "key": "", "label": p["label"]}

KB = """
你是"梅家坞茶园智慧微气候助手", 服务杭州西湖梅家坞的茶农。
用通俗易懂的中文回答, 每条建议 2-4 句, 不堆术语。

农学知识库(阈值已核实):
- 春霜冻: 日最低气温 ≤4℃ 为临界; 2~4℃ 轻度(嫩叶叶尖受冻)、0~2℃ 中度(受冻 20%~50%)、<0℃ 重度(受冻 50% 以上)。
  防护: 覆盖防霜布/遮阳网、凌晨熏烟、喷灌防冻; 重度时优先保护龙井 43 等早生种。
- 倒春寒(浙江标准): 4 月出现连续 3 天日均温 <11℃, 关注茶芽萌动后的霜冻风险。
- 高温热害: 日最高 ≥35℃ 或日均 ≥30℃, 建议遮荫、早晚喷灌、行间铺草保墒。
- 开采期: 日均温稳定通过 6/8/10℃ 分别对应早生/中生/迟生种开采; 龙井 43 约 3 月上旬萌动。
- 灌溉: 连续晴热且 0-7cm 土壤湿度偏低时, 清晨或傍晚浇灌, 避免正午。
"""

FORECAST_CACHE = {"ts": 0.0, "data": None}
CACHE_TTL = 110  # 秒; 前端每 2 分钟刷新, 保持数据实时滚动


def _load_inputs(cfg: dict):
    """模型输入: Open-Meteo 实时(背景场) + 传感器实测(若有, 互补融合)。

    融合策略: 传感器覆盖时段用实测值锚定, 其余时段气象站兜底;
    失败回退本地 CSV。返回 (bg, lab, source_label)。
    """
    site = cfg.get("site", {})
    lat, lon = site.get("lat", 30.2272), site.get("lon", 120.1014)
    from models.live_data import fetch_openmeteo_inputs, load_sensor, merge_sensor_into_inputs
    sensor = load_sensor()
    try:
        bg, lab, meta = fetch_openmeteo_inputs(lat, lon, past_days=6)
        label = f"Open-Meteo 实时(past {meta['hours']}h, {meta['fetched_at']} 拉取)"
        if sensor is not None:
            sdf, smeta = sensor
            bg, lab, stats = merge_sensor_into_inputs(bg, lab, sdf)
            label = (f"传感器实测 + Open-Meteo 互补"
                     f"(实测锚定 {stats['anchored_hours']}h, 气象站兜底 {stats['station_hours']}h)")
        return bg, lab, label
    except Exception as e:  # noqa: BLE001
        print(f"[server] 实时数据获取失败({e}), 回退本地 CSV")
    src = SENSOR_CSV
    source = "open-meteo" if "open-meteo" in Path(src).name else "standard"
    bg, lab = read_inputs(cfg, src, source)
    if sensor is not None:
        bg, lab, stats = merge_sensor_into_inputs(bg, lab, sensor[0])
        return bg, lab, f"传感器实测 + 本地 CSV 互补(实测锚定 {stats['anchored_hours']}h)"
    return bg, lab, "本地 CSV(离线回退)"


def get_forecast(force: bool = False) -> dict:
    if not force and FORECAST_CACHE["data"] and time.time() - FORECAST_CACHE["ts"] < CACHE_TTL:
        return FORECAST_CACHE["data"]
    with open(ROOT / "config.yaml", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    bg, lab, source_label = _load_inputs(cfg)
    fc, t0 = run_forecast(cfg, load_predictor(cfg), bg, lab, hours=72)

    hist = lab["obs_t2m"].iloc[-48:]
    risk = _risk_json(fc, cfg)  # 需 DatetimeIndex, 先算后转字符串
    fc.index = fc.index.map(str)

    # 完整传感器历史(供页面曲线图 + 数据标注使用)
    sensor = []
    for t in bg.index:
        sensor.append({
            "time": str(t),
            "temperature": _round(lab["obs_t2m"].get(t)),
            "humidity": _round(lab["obs_rh"].get(t) if "obs_rh" in lab.columns else None),
            "apparent_temperature": _round(bg["ap_temp"].get(t) if "ap_temp" in bg.columns else None),
            "dew_point": _round(bg["d2m"].get(t) if "d2m" in bg.columns else None),
            "soil_moisture": _round(bg["swvl1"].get(t) if "swvl1" in bg.columns else None, 3),
            "soil_temperature": _round(bg["stl1"].get(t) if "stl1" in bg.columns else None),
            "precipitation": _round(bg["tp"].get(t) if "tp" in bg.columns else None, 2),
        })
    data = {
        "site": cfg["site"],
        "issued_at": str(t0),
        "data_source": source_label,
        "history": [{"time": str(t), "t2m": round(float(v), 1)} for t, v in hist.items()],
        "sensor": sensor,
        "hourly": json.loads(fc.reset_index().to_json(orient="records", date_format="iso")),
        "risk": json.loads(json.dumps(risk, default=str)),
        "bias_lut": _load_lut(),
    }
    FORECAST_CACHE["ts"], FORECAST_CACHE["data"] = time.time(), data
    return data


def _risk_json(fc: pd.DataFrame, cfg: dict) -> dict:
    from models.risk import risk_card
    return risk_card(fc, cfg)


def _round(v, nd: int = 1):
    return round(float(v), nd) if v is not None and pd.notna(v) else None


def _load_lut() -> dict:
    p = ROOT / "data" / "processed" / "bias_lut.json"
    return json.load(open(p, encoding="utf-8")) if p.exists() else {}


def forecast_text(data: dict) -> str:
    """把预报压成一段人话(LLM 提示与规则兜底共用)。"""
    h = data["hourly"]
    w = data["risk"]["windows"]
    tmin, tmax = min(r["t2m_p50"] for r in h), max(r["t2m_p50"] for r in h)
    f = w["24h"]["frost_grade"]
    ht = w["72h"]["heat_grade"]
    txt = (f"未来 72 小时茶园气温 {tmin:.0f}~{tmax:.0f}℃。")
    if f and f > 0:
        txt += f" 有霜冻风险: {w['24h']['frost_note']}。"
    else:
        txt += " 暂无霜冻风险。"
    if ht and ht > 0:
        txt += f" {w['72h']['heat_note']}。"
    else:
        txt += " 暂无高温热害风险。"
    return txt


def rule_reply(question: str, data: dict) -> str:
    """无 LLM Key 时的规则兜底: 关键词路由 + 预报事实。"""
    q = (question or "").strip()
    w = data["risk"]["windows"]
    if any(k in q for k in ("你好", "您好", "hi", "hello", "在吗")):
        return f"您好! 我是梅家坞茶园微气候助手。{forecast_text(data)} 请问您想了解什么?"
    if any(k in q for k in ("谢谢", "感谢")):
        return "不客气! 有霜冻或高温方面的担心随时问我, 也可以问采摘期安排。"
    if any(k in q for k in ("霜冻", "冻害", "倒春寒", "低温", "冷")):
        f24, f48 = w["24h"], w["48h"]
        return (f"当前看: 未来 24h 最低温 {f24['tmin_p50']}℃({f24['frost_note']}); "
                f"未来 48h 最低温 {f48['tmin_p50']}℃({f48['frost_note']})。"
                "防冻口诀: 覆盖防霜布最稳, 凌晨熏烟应急, 喷灌防冻也行; 早生种龙井 43 要优先保护。")
    if any(k in q for k in ("高温", "热害", "热", "晒")):
        h72 = w["72h"]
        return (f"未来 72h 最高温可达 {h72['tmax_p90']}℃。{h72['heat_note']}。"
                "应对: 遮阳网遮荫、清晨傍晚喷灌、行间铺草保墒。")
    if any(k in q for k in ("采摘", "开采", "采茶", "物候")):
        return ("开采期看日均温稳定通过 6/8/10℃(对应早/中/迟生种)。"
                f"{forecast_text(data)} 建议结合未来几天最低温避开霜冻天开采。")
    if any(k in q for k in ("灌溉", "浇水", "墒情", "土壤")):
        return ("灌溉原则: 连续晴热、土壤表层偏干时清晨或傍晚浇, 避开正午。"
                f"{forecast_text(data)}")
    return forecast_text(data) + " 您可以问我: 会不会有霜冻? 什么时候采摘? 要不要浇水?"


def _grounded_prompt(data: dict, context: str | None = None) -> str:
    """把微气候模型的预测结果(逐小时预报 + 风险 + 近期实况)注入系统提示词。

    数据表达防呆: 3h 抽样、每格写成 "P50℃(P10~P90)" 避免小模型把分位数读成
    三套不同预报; 并加硬性规则禁止编造数字与自行推断风险。
    可选 context: 地图点位的地形/微气候信息, 使回答针对该点位。
    """
    hourly = []
    for i, r in enumerate(data["hourly"][:48]):
        if i % 3:
            continue
        lo = r.get("t2m_p10"); mid = r["t2m_p50"]; hi = r.get("t2m_p90")
        t = "" if lo is None or hi is None else f"{mid}℃({lo}~{hi})"
        rh = f"{r['rh']}%" if r.get("rh") is not None else "缺"
        hourly.append({"时间": r["time"][5:16], "气温(中间值,括号为可能范围)": t, "湿度": rh})
    hist = [{"时间": r["time"][5:16], "气温": f"{r['t2m']}℃"} for r in data["history"][-24:][::3]]
    risk = {k: {"最低": f"{v['tmin_p50']}℃", "最高": f"{v['tmax_p90']}℃",
                "霜冻判定": v["frost_note"], "热害判定": v["heat_note"]}
            for k, v in data["risk"]["windows"].items()}
    ctx_block = ""
    if context:
        ctx_block = (f"\n【用户当前查询的地图点位信息(回答必须针对该点位, "
                     f"同时可引用上面监测点预报作区域背景)】\n{context}\n")
    return KB + f"""
当前起报时间: {data['issued_at']}(北京时间), 地点: 杭州西湖梅家坞茶园。
【模型 0-72h 预报(前 48h, 每 3h 一行; 括号内 P10~P90 是可能范围不是另一套预报)】
{json.dumps(hourly, ensure_ascii=False)}
【模型 24/48/72h 风险判定(最终结论以此为准)】
{json.dumps(risk, ensure_ascii=False)}
【最近 24h 茶园实况(3h 抽样)】
{json.dumps(hist, ensure_ascii=False)}{ctx_block}
【回答硬性规则】
1. 先判断用户在问什么(预报/霜冻/高温/采摘/灌溉/其他), 直接回答, 给出具体数字和时段;
2. 引用的每个数字必须来自上面的数据, 严禁编造或推算不存在的数值;
3. 风险结论必须以【风险判定】为准 —— 判定为"无霜冻风险"时严禁说有霜冻或建议防霜;
4. 只回答茶园微气候相关问题, 无关问题礼貌说明本助手只服务茶园;
5. 2-4 句话, 口语化, 不堆术语; 农事建议要可执行(覆盖/熏烟/遮荫/灌溉时机)。"""


def llm_reply(messages: list[dict], data: dict, context: str | None = None) -> tuple[str | None, str | None]:
    """调用 LLM 生成回答。返回 (文本, 引擎名); 全部失败时返回 (None, None)。"""
    ep = _llm_endpoint()
    sys_prompt = _grounded_prompt(data, context)
    payload = {"model": ep["model"],
               "messages": [{"role": "system", "content": sys_prompt}] + messages[-10:],
               "temperature": 0.5, "max_tokens": 600}
    headers = {"Content-Type": "application/json"}
    if ep["key"]:
        headers["Authorization"] = f"Bearer {ep['key']}"
    try:
        for attempt in range(3):  # 免费通道偶发抖动, 最多重试两次
            r = requests.post(f"{ep['base']}{ep['path']}",
                              headers=headers, json=payload, timeout=60)
            if r.status_code == 200:
                content = r.json()["choices"][0]["message"]["content"].strip()
                if content:
                    return content, ep["label"]
            if attempt < 2:
                time.sleep(1.5)
        print(f"[agent] LLM({ep['label']}) 失败 {r.status_code}: {r.text[:200]}")
    except Exception as e:  # noqa: BLE001
        print(f"[agent] LLM({ep['label']}) 异常: {e}")
    # 主通道失败时尝试免费无密钥通道兜底
    if ep["label"] != LLM_PROVIDERS["pollinations"]["label"]:
        try:
            p = LLM_PROVIDERS["pollinations"]
            payload["model"] = p["model"]
            r = requests.post(f"{p['base']}{p['path']}", json=payload, timeout=60)
            if r.status_code == 200:
                content = r.json()["choices"][0]["message"]["content"].strip()
                if content:
                    return content, p["label"]
        except Exception as e:  # noqa: BLE001
            print(f"[agent] Pollinations 兜底异常: {e}")
    return None, None


app = FastAPI(title="梅家坞茶园微气候 Agent")


class ChatIn(BaseModel):
    messages: list[dict]
    context: str | None = None  # 可选: 地图点位地形/气候上下文, 注入该轮系统提示词


@app.get("/api/forecast")
def api_forecast(force: bool = False):
    return JSONResponse(get_forecast(force))


@app.get("/api/summary")
def api_summary():
    data = get_forecast()
    reply, engine = llm_reply([{"role": "user", "content": "请给出一段今天的农事建议总结。"}], data)
    if reply is None:
        reply = f"今日农事建议: {forecast_text(data)} 农事提醒: 关注凌晨最低温与土壤墒情, 有霜冻迹象提前覆盖防霜布。"
        engine = "规则兜底"
    return JSONResponse({"summary": reply, "engine": engine})


@app.post("/api/chat")
def api_chat(inp: ChatIn):
    data = get_forecast()
    reply, engine = llm_reply(inp.messages, data, inp.context)
    if reply is None:
        reply = rule_reply((inp.messages[-1] or {}).get("content", "") if inp.messages else "", data)
        engine = "规则兜底"
    return JSONResponse({"reply": reply, "engine": engine})


# ---- 传感器数据接入(与 Open-Meteo 气象站互补) ----
@app.post("/api/sensor/upload")
async def sensor_upload(file: UploadFile):
    """上传茶园传感器 CSV: 解析质控 -> 保存 -> 预报输入自动切换为互补融合。"""
    from models.live_data import parse_sensor_csv, save_sensor, load_sensor
    raw = await file.read()
    if not raw:
        return JSONResponse({"ok": False, "error": "空文件"}, status_code=400)
    if len(raw) > 5 * 1024 * 1024:
        return JSONResponse({"ok": False, "error": "文件过大(>5MB)"}, status_code=400)
    try:
        df, meta = parse_sensor_csv(raw)
    except ValueError as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=400)
    meta["filename"] = file.filename or "sensor.csv"
    meta["uploaded_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    save_sensor(raw, meta)
    FORECAST_CACHE["ts"] = 0  # 立即失效, 下次请求用新数据
    return JSONResponse({"ok": True, "meta": meta})


@app.get("/api/sensor/status")
def sensor_status():
    """当前传感器数据状态(未接入 / 已接入详情)。"""
    from models.live_data import load_sensor
    sensor = load_sensor()
    if sensor is None:
        return JSONResponse({"connected": False})
    df, meta = sensor
    return JSONResponse({"connected": True, "meta": meta})


@app.delete("/api/sensor")
def sensor_remove():
    """移除传感器数据, 预报输入回到纯 Open-Meteo 气象站。"""
    from models.live_data import clear_sensor
    clear_sensor()
    FORECAST_CACHE["ts"] = 0
    return JSONResponse({"ok": True})


# ---- 地图选点微气候路由(agent/site_api.py)+ 叠加层 PNG 静态挂载 ----
# 降级保护: 地图模块依赖 rasterio/GDAL 等系统库, 个别部署环境若缺库,
# 仅禁用地图接口, 大盘/预报/传感器/助手不受影响(启动不再整体崩溃)。
try:
    from agent.site_api import router as site_router

    app.include_router(site_router)
    (ROOT / "data" / "sites").mkdir(parents=True, exist_ok=True)
    app.mount("/pred", StaticFiles(directory=str(ROOT / "data" / "sites")), name="site-overlays")
    _SITE_OK = True
except Exception as _e:  # noqa: BLE001
    _SITE_OK = False
    print(f"[server] 地图选点功能不可用(大盘与预报不受影响): {_e}")

# 传感器/上传目录(运行时需要, 云端全新克隆时自建)
(ROOT / "data" / "sensor").mkdir(parents=True, exist_ok=True)


@app.get("/api/health")
def api_health():
    """健康检查(Railway 等平台探活用; 注意必须在静态挂载前注册)。"""
    return {"ok": True, "service": "meijiawu-climate-agent", "map_feature": _SITE_OK}


# 静态挂载放在最后: mount("/") 会兜底所有未匹配路径
app.mount("/", StaticFiles(directory=str(STATIC), html=True), name="static")


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    host = "0.0.0.0" if os.environ.get("PORT") else "127.0.0.1"
    uvicorn.run(app, host=host, port=port)
