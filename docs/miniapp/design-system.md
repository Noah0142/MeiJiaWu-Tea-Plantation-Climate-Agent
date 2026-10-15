# 小程序设计系统(小程序版)

> 基线来源: 网页版设计体系(2026-10-14 已上线版本)。小程序延续同一品牌令牌,
> 不做三套风格探索 —— 遵循 launch-wechat-miniapp「已有品牌与用户指定风格优先」。
> 高保真原型: `docs/miniapp/prototype/index.html`(浏览器打开, 四屏并排)。

## 画布与平台约束

| 项目 | 约定 |
|---|---|
| 画布基准 | 375px 逻辑宽度(iPhone 基准), rpx 等比: 1rpx = 0.5px @375 |
| 胶囊避让 | 使用**系统默认导航栏**(navigationBar), 不自定义导航, 天然避开胶囊 |
| 安全区 | 底部输入栏使用 `env(safe-area-inset-bottom)`(见 app.wxss `.input-row`) |
| tabBar | 原生 tabBar, 4 项(大盘/农事助手/地图选点/数据接入), 图标为项目内本地 PNG |
| 触控区域 | 按钮/输入行均 ≥ 84rpx(≈42px), chip ≥ 56rpx, 列表行 ≥ 88rpx |
| 深浅色 | `darkmode: true` + `theme.json`, 跟随系统自动切换 |

## 视觉令牌(与网页版 oklch 令牌同源, 已换算为 sRGB)

| 令牌 | 浅色 | 深色 | 用途 |
|---|---|---|---|
| --bg | `#f8f7f1` | `#060e09` | 页面底色(暖米白/松针墨绿) |
| --surface | `#ffffff` | `#101a13` | 卡片、输入栏 |
| --surface-2 | `#f2f0e9` | `#18241c` | 次级面(chip、输入框、代码块) |
| --border | `#e2e6e0` | `#223028` | 描边(1rpx) |
| --text | `#132419` | `#ebe8dc` | 正文 |
| --muted | `#536257` | `#a19e94` | 次要文字 |
| --primary | `#267543` | `#51af6f` | 茶青主色(按钮/曲线/选中态) |
| --amber | `#b47825` | `#e7b551` | 高温/轻度预警语义色 |
| --frost | `#357b95` | `#6eb7ce` | 低温/湿度语义色 |
| --danger | `#c92f33` | `#e8605b` | 重度预警语义色 |

### 字体与排版

- 标题: `"Songti SC"` 衬线(延续网页版 Noto Serif SC 的编辑气质), 正文: 系统无衬线
- 字号层级: 品牌标题 40rpx / 面板标题 32rpx / 正文 28rpx / 次要 22–24rpx / 指标值 52rpx
- 间距节奏: 卡片间距 24rpx, 卡片内边距 28rpx, 网格间隔 20rpx(不挤不密)
- 圆角: 卡片 24rpx, 按钮 20rpx, 胶囊 999rpx
- 数字: `font-variant-numeric: tabular-nums`(指标值不跳动)

## 页面结构与数据映射

| 页面 | 结构 | API | 空/错状态 |
|---|---|---|---|
| 大盘 | 品牌头 → 状态条 → 2×2 指标卡 → 72h 预报图 → 风险行 → AI 建议 | `/api/forecast` `/api/summary` | 加载转圈 / 错误+重试按钮 / 下拉刷新 |
| 农事助手 | 引擎提示 → 气泡列表 → 快捷提问(横滑) → 输入栏 | `/api/chat` | 发送中"思考中…" / 失败气泡含原因 / 会话本机缓存 |
| 地图选点 | 原生 map(42% 高) → 常用位置 chips → 地形卡 → 结果卡 | `/api/site/point` `/api/site/predict` `/api/chat`(AI 解读) | 点位查询转圈 / 运行中计时 / toast 报错 |
| 数据接入 | 服务器地址卡 → 传感器卡 → CSV 说明 → 数据来源 | `/api/health` `/api/sensor/*` | 连接失败提示 / 上传成功/失败提示 |

字段映射: `t2m_p50 → 曲线`, `risk.windows["24h"].frost_grade → chip 分级(g0–g3)`, `data_source → 状态条`, 空值统一显示 `—`。

## 组件与素材

| 元素 | 实现 | 来源 |
|---|---|---|
| 预报曲线(P10–P90 带 + P50 线) | `components/line-chart`(canvas 2d, DPR 适配, 深浅色随主题重取色) | 自研(网页版 ECharts 的小程序等价物) |
| 地图与叠加层 | 微信原生 `<map>` + `groundOverlays`(贴后端渲染的 PNG) | 平台组件 |
| tabBar 图标 | 项目内本地 PNG(81×81, 灰绿/茶青两态, PIL 生成, 超采样抗锯齿) | `miniapp/assets/tabbar/` |
| 卡片/胶囊/按钮 | WXSS(见 app.wxss) | 自研, 无第三方组件库 |

> 技术选型: **不引入第三方组件库**(WeUI/TDesign)——页面元素简单(WXSS 原生即可高质量实现),
> 少一个依赖少一份构建风险; 这是本项目的取舍记录。

## 与网页版的差异(有意为之)

| 差异 | 原因 |
|---|---|
| ECharts → 自研 canvas 组件 | 小程序体积/性能约束; 只画一种图(折线+区间) |
| Leaflet → 微信原生 map | 小程序不支持 Leaflet |
| 历史实况 4 图 → 并入主图 | 手机一屏信息量有限, 避免"挤在一团"; 需要时二期加 |
| 对话页独立成 tab | 移动端高频任务, 值得一级入口 |

## 未验证项(需开发者工具/真机确认)

- canvas 2d 在开发者工具与真机的渲染一致性(曲线与字体度量)
- 原生地图 `groundOverlays` 的 PNG 加载(需 HTTPS 域名且加入 downloadFile 合法域名)
- 深色模式下导航栏/tabBar 跟随(`theme.json` 行为以真机为准)
- 输入框键盘弹起时的页面布局(`cursor-spacing` 已设 16)
