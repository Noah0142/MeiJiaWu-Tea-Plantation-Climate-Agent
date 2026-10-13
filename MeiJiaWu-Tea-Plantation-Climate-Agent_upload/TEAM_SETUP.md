# 队友上手必读 (Team Setup)

梅家坞智慧茶园项目 — 地形数据 + 微气候建模工具链。按下面 4 步即可开工。

## 1. 装环境(一次性)

- **Claude Code**: 官网安装 CLI 并登录自己的账号(Agent 需要它运行)
- **Python 3.9+**: 任选一个 Python,建议用虚拟环境:
  ```bash
  cd MeijiawuSmartTeaGarden
  pip install -r requirements.txt
  ```

## 2. 拿到项目

- 压缩包: 解压到本地任意路径(路径别含中文)
- 或 Git: 仓库克隆后先运行一次数据下载(见下)

## 3. 生成数据

```bash
python scripts/download_terrain.py   # 缺失的原始瓦片会自动补下(幂等)
python scripts/process_dem.py        # 生成坡度/坡向/TPI/汇流累积等特征
python scripts/build_microclimate.py # 气温降尺度 → 积温/霜冻/温差/开采期品质指标
```

三条管线: 地形 → 气温×地形 → 品质量化。阈值参数在 `build_microclimate.py` 的 CONFIG 中,标"待校准"的需文献/实测标定。

> 数据产物 `data/terrain/meijiawu/` 已随包附上,不做数据下载也能直接看图和数据。

## 4. 使用 Agent

在**项目根目录**启动 Claude Code,子代理 `tea-garden-geo` 自动可用:

```bash
cd MeijiawuSmartTeaGarden
claude
```

然后直接说,例如:
- "帮我拉 open-meteo 的杭州历史气象数据"
- "设计茶园传感器布点方案"
- "把地形特征栅格转成训练样本表"

## 数据源速查

| 数据 | 来源 | 备注 |
|---|---|---|
| NASADEM 30m | NASA / Planetary Computer | 免注册 |
| SRTM 90m | CGIAR-CSI | 免注册 |
| 12.5m ALOS AW3D30 | JAXA | 需注册 |
| FABDEM 裸地面 30m | Fathom | 需注册 |
| 气象历史数据 | open-meteo.com API | 免注册 |
| ERA5-Land | ECMWF CDS | 需注册 |

## 约定

- 坐标系统一 **EPSG:4326**;脚本与路径保持 ASCII
- 分析范围 BBOX: 120.03–120.14°E, 30.16–30.26°N
- 引用: NASADEM → NASA JPL; SRTM → CGIAR-CSI v4.1
