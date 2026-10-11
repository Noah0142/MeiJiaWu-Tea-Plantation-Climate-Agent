# 梅家坞智慧茶园项目 (Meijiawu Smart Tea Garden)

## 项目目标
训练茶园微气候模型(温度/湿度/霜冻风险/冷空气通道空间预测),构建智慧茶园管理系统。组队比赛项目,队友上手见 `TEAM_SETUP.md`。

## 项目锚点
- 位置: 梅家坞村, 杭州西湖区, 120.084°E, 30.206°N, 村址海拔 58–60 m, 周边 12–383 m
- 地形: 琅珰岭北麓山间谷地, 梯田茶园 ~153 公顷
- 分析 BBOX: 120.03–120.14°E, 30.16–30.26°N (~11×11 km)

## 环境(重要)
- 用安装了 `requirements.txt` 的 Python 环境运行脚本(本机是 `py -3.9`; 队友按各自环境执行)
- 空间基准统一 EPSG:4326; 项目路径保持 ASCII
- 新队友: 先读 `TEAM_SETUP.md`

## 数据布局
- `data/terrain/` — 原始 DEM 瓦片(NASADEM 30m + CGIAR SRTM 90m, 均可重下, 不入库)
- `data/terrain/meijiawu/` — 裁剪后 DEM 及衍生特征(slope/aspect/hillshade/tpi_330m/flowacc/diff/stats.json/terrain_preview.png)
- `data/weather/` — open-meteo 参考点气象 CSV(2016–2026 日值, 2021–2026 小时值)
- `data/microclimate/` — 品质微气候指标(gdd_spring/frost_hours/dtr_spring/first_pluck_doy)
- `scripts/download_terrain.py` — 幂等下载; `scripts/process_dem.py` — 裁剪+特征工程; `scripts/build_microclimate.py` — 气温降尺度+品质指标

## 工作流
1. 地形: `python scripts/download_terrain.py` → `python scripts/process_dem.py`
2. 气温×地形: `python scripts/build_microclimate.py`(GDD/霜冻/DTR/开采期, 阈值参数在脚本 CONFIG 中, 待校准)
3. 建模: 特征栅格→样本表→PyTorch 训练→品质/霜冻空间预测

## Agent
复杂地学/建模任务可委派给子代理 `tea-garden-geo`(定义在 `.claude/agents/tea-garden-geo.md`, 在本项目目录启动 Claude Code 即可用)。
