# -*- coding: utf-8 -*-
"""geosite — 梅家坞智慧茶园地学与微气候核心库

供 agent/ (地图选点微气候服务) 与 scripts/ 复用:
  terrain.py    NASADEM 30m 瓦片按需下载 + 地形特征工程 (坡度/坡向/TPI/汇流/山体阴影)
  weather.py    open-meteo 任意点气象 (archive 幂等缓存 + 7天预报)
  downscale.py  气温递减率降尺度 → 微气候指标 (GDD/霜冻/DTR/开采期/72h 预报)

所有空间数据统一 EPSG:4326。阈值参数见 downscale.CONFIG (标注"待校准"的需实测标定)。
"""
