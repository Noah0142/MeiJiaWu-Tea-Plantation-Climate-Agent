# 梅家坞茶园微气候智能体

> AI4Climate 全球青年气候解决方案挑战赛 · 方向 01「梅家坞气候智慧茶园」参赛项目

用 **76 年 ERA5-Land 再分析数据**训练微气候预测模型,把茶园未来 **0–72 小时逐小时气温**(含 P10–P90 不确定性区间)与**霜冻/高温热害风险**算出来;再接入**免费大模型(智谱 GLM-4-Flash)**把预报翻译成茶农听得懂的农事建议,支持自然语言多轮问答;全部结果呈现在一个 Web 仪表盘上(预报图、实况曲线、风险胶囊、对话窗口)。

**一句话架构**:数据 → LightGBM 微气候模型(预测+风险)→ LLM 农事问答 → Web 仪表盘。

## 功能特性

- **微气候预报模型**:多时效 LightGBM 分位数回归(气温 P10/P50/P90 + 湿度),时效 1/3/6/12/24/48/72 小时,纯历史实况驱动(无需数值预报输入,拿到茶园传感器即可部署)
- **地图定点查询**:Leaflet 卫星/街道地图任意选点,输出该点 30m 地形剖面(海拔/坡度/坡向/TPI/土地覆盖)、物理降尺度微气候指标(明前 GDD/霜冻小时/昼夜温差/开采期)与 72h 本地化预报,叠加 6 张专题图层;曲线同时叠加**监测点 LightGBM 对照线**,并支持**点位 AI 解读**(复用 /api/chat 注入点位上下文)
- **严格三段切分**:train 1981–2020 / val 2021–2024 / test 2025–2026,气候态只用训练段、早停只挂验证集、测试集只评一次 —— 防数据污染
- **风险预警**:春霜冻(日最低温 ≤4℃ 分级)、高温热害(≥35℃)、浙江倒春寒(4 月连续 3 天均温 <11℃),阈值均已核实
- **LLM 农事问答**:模型逐小时预报全文注入提示词,回答严格基于数据(禁止编造),多供应商降级链(智谱 GLM-4-Flash 免费 → Pollinations 无密钥 → 规则兜底),页面显示当前回答引擎
- **Web 仪表盘**:实时卡片、72h 预报图(80% 置信区间带)、4 张历史实况曲线(最高/最低标注点、均值线、缩放)、风险胶囊、AI 农事建议、农户多轮对话、明暗主题切换
- **Open-Meteo 集成**:自动取数小卡(72h 气温曲线)+ API 密钥接入卡(像接入大模型一样填 Key,用返回数据驱动上方卡片与曲线,可恢复默认模型)
- **迁移学习与部署**:`--finetune-station` 锚点站微调(稀疏校准)、m2cgen 导出纯 JS 模型(零 Python 边缘运行)、sensor-network 前端 schema 对齐

## 关键结果(测试集 2025-01 ~ 2026-10,训练全程未见)

| 指标 | 数值 |
|---|---|
| 总体气温 MAE | **1.52℃**(持续预报 2.69℃,skill +41%) |
| 1h / 24h / 72h MAE | 0.37 / 1.87 / 2.59℃ |
| 24h 最低温准确率(±2℃) | **74.1%**(对标绍兴御茶村 52%→64%) |
| 霜冻预警 POD / FAR | **0.98 / 0.19** |
| P10–P90 区间覆盖率 | 78.1% |

外部部署测试(Open-Meteo 茶园序列,模型从未见过):0-24h MAE 1.05℃;长时效经偏差订正后 24-72h MAE 2.1–2.6℃。详见 [docs/model_report.md](docs/model_report.md)。

## 技术栈

| 层 | 技术 |
|---|---|
| 模型训练 | Python 3.13 · LightGBM(分位数回归)· scikit-learn(随机森林基线)· pandas/numpy |
| 特征工程 | 时间谐波、实况滞后/滚动、气候距平(训练段气候态)、多格点/邻站协同、茶园土地覆盖静态特征 |
| Web 服务 | FastAPI + uvicorn(预测/农事摘要/多轮对话接口 + 静态托管) |
| 前端 | 原生 JS + **ECharts 5.6** + Pico CSS(自建 oklch 设计令牌、Noto Serif SC/Sans SC、明暗双主题) |
| LLM 层 | OpenAI 兼容供应商链:智谱 GLM-4-Flash(免费)/ SiliconFlow / Groq / OpenRouter / DeepSeek / Pollinations(无密钥) |
| 数据 API | Open-Meteo(forecast / air-quality / archive,前端直连,支持 apikey) |
| 部署导出 | m2cgen(LightGBM → 纯 JS) |

## 项目结构

```
AI4Climate/
├── agent/                  # Web 服务 + LLM 问答层 + 地图选点 API(site_api.py); 密钥在 agent/.env
├── geosite/                # 地图选点微气候库(30m 地形/土地覆盖/物理降尺度/天气获取)
├── web/static/             # 前端页面(index.html 大盘 + map.html 地图页, 共用设计系统)
├── miniapp/                # 微信小程序(4 tab: 大盘/农事助手/地图选点/数据接入)
├── models/                 # baseline / train_lgbm / evaluate / infer / predict / risk
├── features/               # 特征工程 + 数据集构建(严格三段切分)
├── scripts/                # prepare_training_data / make_synthetic_data / export_to_js
├── training_data/          # 原始数据(ERA5-Land × 6 文件、Open-Meteo 茶园序列、10m 茶园分布图)
├── data/                   # raw / processed / terrain(30m DEM) / landcover / microclimate / weather / sites
├── docs/                   # 训练/模型/文书文档; docs/miniapp/ 小程序设计系统与部署教程
└── config.yaml             # 全局配置(路径、列名映射、切分日期、target_mode、超参)
```

## 微信小程序

`miniapp/` 是网页版的微信小程序复刻: 大盘(指标卡+72h 预报曲线+风险预警+AI 建议)、
农事助手(多轮对话)、地图选点(原生地图选点+微气候预测+叠加层)、数据接入(服务器地址+传感器 CSV)。

- **设计**: 延续网页版设计令牌(茶青主色/暖米白/衬线标题/大留白), 跟随系统深浅色;
  高保真原型在 `docs/miniapp/prototype/index.html`(浏览器直接打开);
- **部署教程**(从注册账号到体验版/正式发布): [docs/miniapp/deploy-guide.md](docs/miniapp/deploy-guide.md);
- **使用方法**: 微信开发者工具「导入项目」→ 选择 `miniapp` 目录 → 本地调试填 `http://127.0.0.1:8000`,
  云端填 Railway 域名(数据接入页可随时切换)。

## 快速开始

```bash
pip install -r requirements.txt

# ① 启动 Web 仪表盘 + LLM 问答(默认 8000 端口)
python agent/server.py                    # http://127.0.0.1:8000 (大盘)
#    地图定点查询: http://127.0.0.1:8000/map.html(与大盘导航互通)
#    免费 LLM: 把 agent/.env.example 复制为 agent/.env 填入密钥(见文件内三个方案)

# ② 训练管线(数据已在 training_data/, 可一键复现)
python scripts/prepare_training_data.py   # 6 个 ERA5 CSV -> data/raw 标准输入
python features/build_dataset.py          # 严格三段切分, 生成 280 万条样本(train/val/test)
python models/baseline.py --split test
python models/train_lgbm.py               # P10/P50/P90 + RH, 验证集早停
python models/evaluate.py --split test    # 最终报告(只跑一次)

# ③ 命令行调用模型(近期传感器历史 -> 72h 预报 + 风险卡片)
python models/predict.py --obs data/raw/labels.csv --hours 72
python models/predict.py --source open-meteo --obs training_data/open-meteo-30.19N120.11E180m.csv

# ④ 自测管线(合成数据, 无需真实数据, 产物在 models/artifacts_smoke)
python scripts/make_synthetic_data.py && python features/build_dataset.py --config scripts/smoke_config.yaml
```

## 部署到 Railway(云端)

仓库已内置云端部署配置, 在 Railway 里把本仓库连上即可, 无需额外设置:

| 文件 | 作用 |
|---|---|
| `main.py` | 云端启动入口(暴露 `agent.server` 的 FastAPI app) |
| `railway.json` / `Procfile` | 启动命令 `uvicorn main:app --host 0.0.0.0 --port $PORT` + 健康检查 `/api/health` |
| `.python-version` | 固定 Python 3.12 |
| `models/artifacts/*.joblib`、`data/terrain`、`data/landcover`、`data/microclimate`、`data/weather` | 预报与地图功能必需的小数据, 已随仓库入库(训练用大数据仍不入库) |

可选环境变量(在 Railway 服务的 Variables 里设置):

- `LLM_PROVIDER=zhipu` + `LLM_API_KEY=...` —— 农事问答走智谱 GLM-4-Flash(推荐);
  不设置时自动走免费无密钥通道(Pollinations), 再兜底规则回答, 页面不会断答。
- 运行时自动从 Open-Meteo 拉取实时数据, 无需其他密钥。

注意: 云端实例(如 Railway 免费计划)重启后本地上传的传感器数据会清空(容器文件系统不持久), 属预期行为;
如需持久化可挂载 Railway Volume 到 `data/sensor`。

## 数据

- **ERA5-Land 单格点(30.20°N, 120.10°E)1950–2026 逐小时 × 67.3 万条**:2m 气温/露点、降水、短波辐射、皮肤温度、4 层土壤温度、4 层土壤湿度(Copernicus CDS 下载)
- **Open-Meteo 茶园点序列**(30.19°N, 120.11°E, 海拔 180m):近期线上数据,作外部部署测试
- **Teamap_2022_China.tif**:全国 10m 茶园分布图(figshare, 福州大学邱炳文团队)→ 提取茶园占比/最近茶园距离静态特征
- 数据合同与兜底通道(Open-Meteo 历史、NOAA ISD 杭州站 58457、ECMWF Open Data)见 [docs/training_plan.md](docs/training_plan.md)

## 参考的项目与资料

| 参考 | 借鉴了什么 |
|---|---|
| [microclimate-sensor-network](https://github.com/Noah0142/microclimate-sensor-network)(模板, 上游 [adam-sid/microclimate-sensor-network](https://github.com/adam-sid/microclimate-sensor-network)) | 网页模板(Pico + ECharts 卡片/曲线页)、LightGBM 预报 + m2cgen 导 JS 部署思路、48h 预报 JSON schema |
| [ConardLi/garden-skills](https://github.com/ConardLi/garden-skills) 的 web-design-engineer 技能 | 页面重设计方法论(Design Read、redesign 协议、反 AI 俗套清单、oklch 色彩体系) |
| 绍兴御茶村茶园案例(40+6 微型气象站, 200m 间距) | "粗网格预报 + 微型站实况 → AI 误差订正"范式;24h 最低温准确率 52%→64% 对标指标 |
| AI4Climate 组委会数据源清单 | 六方向公开数据渠道与赛题数据包配置 |
| Open-Meteo / ERA5-Land / ECMWF Open Data / NOAA ISD | 训练与运行时数据源(免费/开放) |

## 文档

- [docs/training_plan.md](docs/training_plan.md) —— 训练方法论、数据合同、七天节奏、传感器网络路线图
- [docs/model_report.md](docs/model_report.md) —— 严格三段切分协议与测试集完整结果
- [docs/web_demo.png](docs/web_demo.png) / [docs/web_demo_light.png](docs/web_demo_light.png) —— 页面截图(深/浅色)
