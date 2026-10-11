# 梅家坞智慧茶园 — 地形数据与微气候建模

梅家坞茶园微气候模型项目:以 DEM 地形特征 + 气象数据训练模型,预测茶园空间温湿度、霜冻风险与冷空气通道,辅助智慧茶园管理(灌溉、防霜、采摘调度)。

## 目录结构

```
MeijiawuSmartTeaGarden/
├── CLAUDE.md                  # 项目上下文(Claude Code 自动加载)
├── README.md                  # 本文件(项目总览)
├── TEAM_SETUP.md              # 队友上手指南
├── requirements.txt           # Python 依赖
├── .gitignore                 # 大文件排除规则
├── .claude/agents/
│   └── tea-garden-geo.md      # 专用子代理(在项目目录启动 Claude Code 即可用)
├── data/terrain/              # 原始 DEM 瓦片(可由脚本重下, 不入库)
│   ├── nasadem_N30E120.tif    # NASADEM 30m (NASA JPL, 2020)
│   ├── srtm_61_06.tif         # CGIAR SRTM v4.1 90m (2008)
│   └── meijiawu/              # 裁剪+衍生(全部 EPSG:4326)
│       ├── dem_30m.tif        #   裁剪后 DEM, 360×396 格, ~30.9 m
│       ├── slope.tif          #   坡度 (度)
│       ├── aspect.tif         #   坡向 (0–360, 0=北, 顺时针)
│       ├── hillshade.tif      #   山体阴影
│       ├── tpi_330m.tif       #   地形位置指数 (11×11 邻域 ~330 m)
│       ├── flowacc.tif        #   D8 汇流累积 (冷空气排水代理)
│       ├── diff_nasadem_srtm.tif  # 两数据源差值
│       ├── stats.json         #   统计摘要
│       └── terrain_preview.png    # 四联预览图
├── data/weather/              # open-meteo 参考点气象 (CSV)
│   ├── meijiawu_daily_2016_2026.csv   # 2016–2026 日最高/最低温+降水
│   └── meijiawu_hourly_2021_2026.csv  # 2021–2026 小时温度
├── data/microclimate/         # 品质微气候指标
│   ├── gdd_spring.tif         #   明前积温 (基温 10°C)
│   ├── frost_hours.tif        #   春季霜冻小时数
│   ├── dtr_spring.tif         #   昼夜温差 (含山谷冷池修正)
│   ├── first_pluck_doy.tif    #   开采期日序估计
│   ├── microclimate_stats.json
│   └── microclimate_preview.png
└── scripts/
    ├── download_terrain.py    # 幂等下载地形数据
    ├── process_dem.py         # 裁剪 + 地形特征工程
    └── build_microclimate.py  # 气温降尺度 + 品质微气候指标
```

## 快速开始

```bash
cd <项目根目录>
pip install -r requirements.txt      # 首次
python scripts/download_terrain.py   # 下载(已下载会自动跳过)
python scripts/process_dem.py        # 生成特征 + 交叉验证 + 预览图
```

> 注: 创建者机器上 rasterio 装在 Python 3.9 环境(需 `py -3.9`),队友用各自安装了 requirements.txt 的环境即可。组队协作见 `TEAM_SETUP.md`。

## 关键结果 (2026-10-11)

| 指标 | 值 |
|---|---|
| 村址海拔 (NASADEM) | 58.0 m (GeoNames 参考 60 m) |
| 区域海拔范围 | −6 ~ 417 m, 均值 72.9 m |
| 坡度 | 均值 11.2°, 最大 50.7° |
| 汇流累积 | 最大 907 格 (≈0.87 km² 上游) |
| NASADEM vs SRTM 交叉验证 | 相关系数 0.980, RMSE 15.6 m |

### 微气候品质指标 (2026-10-11, 待校准阈值)

| 指标 | 空间范围 | 含义 |
|---|---|---|
| 明前积温 GDD (1/1–4/5, 基温 10°C) | 75 ~ 159 °C·d | 茶芽萌发与开采早晚; 高值区先开采 |
| 春季霜冻时长 (2/1–4/5, <2°C, 6年合计) | 484 ~ 1358 h | 倒春寒毁芽风险; 谷底/高坡差异近 3 倍 |
| 昼夜温差 DTR (3/1–4/5) | 9.6 ~ 11.0 °C | 茶氨酸积累与香气形成; 含山谷冷池修正 |
| 开采期 DOY (1/1 起算) | 85 ~ 95 (3/26–4/5) | 各地块开采先后相差约 10 天 → 采收调度依据 |

## 数据源与引用

| 数据 | 来源 | 许可/引用 |
|---|---|---|
| NASADEM 30m | NASA JPL, 经 Microsoft Planetary Computer 公开 STAC 获取 | 公共领域, 引用 NASA JPL NASADEM |
| SRTM v4.1 90m | [CGIAR-CSI](https://srtm.csi.cgiar.org) | 引用: Jarvis et al. 2008, CGIAR-CSI SRTM 90m Database v4.1 |

## 下一步路线图

1. **更高精度 DEM**: ALOS AW3D30 12.5m(需 JAXA 注册)/ FABDEM 裸地面(需 Fathom 注册)/ 无人机摄影测量或 LiDAR 0.5–1 m
2. **阈值校准**: GDD 基温 / 霜冻临界 / 开采积温 / 冷池系数 — 查茶学文献 + 实地传感器/农事记录标定
3. **茶园边界**: 用卫星影像或现场勘测勾画茶园范围 shp,掩膜掉非茶园格点
4. **传感器布点**: 按高程分层 + 坡向 + 冷空气通道候选点输出坐标清单
5. **品质模型**: 地形+微气候特征→样本表→PyTorch 训练→品质分级/霜冻预警/采收调度预测
