// 地图选点: 微信原生 map 组件 + 点击选点 -> 地形剖面 -> 运行微气候模型 -> 叠加层贴图
const api = require("../../utils/api");

const PRESETS = [
  { name: "梅家坞村址", lat: 30.206, lon: 120.084 },
  { name: "琅珰岭", lat: 30.228, lon: 120.09 },
  { name: "云栖竹径", lat: 30.184, lon: 120.062 },
  { name: "九溪", lat: 30.196, lon: 120.115 },
];

function aspectText(deg) {
  if (deg == null) return "—";
  const d = ["北", "东北", "东", "东南", "南", "西南", "西", "西北"];
  return d[Math.round((((deg % 360) + 360) % 360) / 45) % 8];
}
function doyDate(doy) {
  if (doy == null) return "—";
  const d = new Date(2025, 0, 1);
  d.setDate(d.getDate() + Math.round(doy) - 1);
  return `${d.getMonth() + 1}月${d.getDate()}日`;
}
const fmt = (v, nd = 1) => (v == null ? "—" : Number(v).toFixed(nd));

Page({
  data: {
    presets: PRESETS,
    centerLat: 30.206,
    centerLon: 120.084,
    scale: 14,
    mapLayerStyle: 2,  // 2=卫星图, 1=街道图
    marker: null,
    point: null,          // 点位地形信息
    pointLoading: false,
    predicting: false,
    elapsed: 0,
    result: null,         // 微气候预测结果
    overlays: [],         // 模型运行后的叠加层(霜冻等)
    terrainOverlay: null, // 地形 hillshade 叠加层(常驻底图)
    overlayOn: true,
    allOverlays: [],      // 合并后的所有叠加层(地形 + 模型层)
    mapH: 440,            // 地图高度(rpx)
  },

  onLoad() {
    // 高度自适应: 地图占屏幕 42%
    const info = wx.getWindowInfo ? wx.getWindowInfo() : wx.getSystemInfoSync();
    this.setData({ mapH: Math.round(info.windowHeight * 0.42 * 2) });
    // 加载地形底图叠加层(hillshade)
    this.loadTerrainOverlay();
  },

  // 地图加载完成后切换为卫星图层
  onMapReady() {
    console.log("[map] 地图 ready, 尝试切换卫星图(layer-style=" + this.data.mapLayerStyle + ")");
    const ctx = wx.createMapContext("teaMap", this);
    if (ctx && typeof ctx.setMapStyle === "function") {
      // 某些基础库版本支持 setMapStyle, 尝试强制切换
      ctx.setMapStyle({
        styleId: "2",
        success: (res) => console.log("[map] setMapStyle 成功", res),
        fail: (err) => console.warn("[map] setMapStyle 失败", err),
      });
    }
  },

  // 合并地形叠加层与模型叠加层
  _refreshAllOverlays() {
    const list = [];
    if (this.data.terrainOverlay) {
      list.push(this.data.terrainOverlay);
    }
    if (this.data.overlayOn && this.data.overlays.length) {
      list.push(...this.data.overlays);
    }
    this.setData({ allOverlays: list });
  },

  // 加载梅家坞地形叠加层(DEM 高程配色 + 山体阴影)
  async loadTerrainOverlay() {
    try {
      const d = await api.siteOverlay("dem");
      const b = d.bbox; // [west, south, east, north]
      const overlay = {
        src: getApp().globalData.apiBase + d.url,
        bounds: {
          southwest: { latitude: b[1], longitude: b[0] },
          northeast: { latitude: b[3], longitude: b[2] },
        },
        opacity: 0.7,
      };
      this.setData({ terrainOverlay: overlay });
      this._refreshAllOverlays();
      console.log("[map] 地形叠加层加载成功", d.url);
    } catch (e) {
      console.warn("[map] 地形叠加层加载失败:", e.message);
    }
  },

  // 地图点击选点
  onMapTap(e) {
    if (!e.detail || e.detail.latitude == null) return;
    this.selectPoint(e.detail.latitude, e.detail.longitude);
  },

  onPreset(e) {
    const p = this.data.presets[e.currentTarget.dataset.i];
    this.setData({ centerLat: p.lat, centerLon: p.lon, scale: 15 });
    this.selectPoint(p.lat, p.lon);
  },

  async selectPoint(lat, lon) {
    this.setData({
      marker: { latitude: lat, longitude: lon },
      pointLoading: true,
      point: null,
    });
    try {
      const d = await api.sitePoint(lat, lon);
      const t = d.terrain || {};
      const mc = d.microclimate_grid || {};
      this.setData({
        pointLoading: false,
        point: {
          lat, lon,
          elevation: fmt(t.elevation_m, 0),
          slope: fmt(t.slope_deg),
          aspect: `${aspectText(t.aspect_deg)} ${fmt(t.aspect_deg, 0)}°`,
          tpi: fmt(t.tpi_m),
          landcover: d.landcover ? d.landcover.label : "未知",
          note: d.note || "",
          hasGrid: d.source === "meijiawu_grid" && mc.gdd_spring != null,
          gdd: fmt(mc.gdd_spring),
          frostH: fmt(mc.frost_hours_6yr != null ? mc.frost_hours_6yr : mc.frost_hours, 0),
          dtr: fmt(mc.dtr_spring),
          pluck: doyDate(mc.first_pluck_doy),
        },
      });
    } catch (e) {
      this.setData({ pointLoading: false });
      wx.showToast({ title: `点位查询失败: ${e.message}`, icon: "none" });
    }
  },

  async runPredict() {
    if (!this.data.point || this.data.predicting) return;
    const { lat, lon } = this.data.point;
    this.setData({ predicting: true, elapsed: 0, result: null });
    const t0 = Date.now();
    const timer = setInterval(() => {
      this.setData({ elapsed: Math.round((Date.now() - t0) / 1000) });
    }, 1000);

    try {
      const d = await api.sitePredict(lat, lon);
      clearInterval(timer);
      const f = d.forecast_72h || {};
      const mc = d.microclimate || {};
      const b = (d.window && d.window.bbox) || null;

      this.setData({
        predicting: false,
        result: {
          gdd: fmt(mc.gdd_spring),
          frostH: fmt(mc.frost_hours_6yr, 0),
          dtr: fmt(mc.dtr_spring, 2),
          pluck: doyDate(mc.first_pluck_doy),
          min72: fmt(f.min_72h),
          frost72h: fmt(f.frost_hours_next72h, 0),
          frostGrade: f.frost_grade || 0,
          frostNote: f.frost_note || "",
          paramsNote: mc.params_note || "",
          warnings: (d.warnings || []).join("; "),
          elapsed: d.elapsed_s,
        },
        // 叠加层: 72h 霜冻(默认显示)
        overlays:
          d.overlays && d.overlays.frost72h && b
            ? [
                {
                  src: getApp().globalData.apiBase + d.overlays.frost72h,
                  bounds: {
                    southwest: { latitude: b[1], longitude: b[0] },
                    northeast: { latitude: b[3], longitude: b[2] },
                  },
                  opacity: 0.75,
                },
              ]
            : [],
      });
      this._refreshAllOverlays();
      wx.showToast({ title: `完成(耗时 ${d.elapsed_s}s)`, icon: "success" });
    } catch (e) {
      clearInterval(timer);
      this.setData({ predicting: false });
      wx.showToast({ title: `模型运行失败: ${e.message}`, icon: "none" });
    }
  },

  toggleOverlay() {
    this.setData({ overlayOn: !this.data.overlayOn });
    this._refreshAllOverlays();
  },

  // AI 解读该点位
  async askAI() {
    if (!this.data.point || !this.data.result) return;
    const p = this.data.point;
    const r = this.data.result;
    const context = [
      `点位坐标: ${p.lat.toFixed(4)}°N, ${p.lon.toFixed(4)}°E`,
      `地形: 海拔 ${p.elevation} m, 坡度 ${p.slope}°, 坡向 ${p.aspect}, TPI ${p.tpi} m`,
      `土地覆盖: ${p.landcover}`,
      `微气候指标: 明前GDD ${r.gdd} °C·d, 春季霜冻 ${r.frostH} h/6年, 预计开采 ${r.pluck}`,
      `未来72h本地预报: 最低 ${r.min72} °C, 霜冻小时 ${r.frost72h} h, 风险判定: ${r.frostNote}`,
      `(本地预报为物理降尺度模型的演示占位参数结果, 仅作技术展示)`,
    ].join("\n");

    wx.showLoading({ title: "AI 解读中…" });
    try {
      const d = await api.chat([{ role: "user", content: "请解读这个点位的微气候情况, 并给出农事建议。" }], context);
      wx.hideLoading();
      wx.showModal({ title: "AI 解读", content: d.reply || "暂无回复", showCancel: false, confirmText: "知道了" });
    } catch (e) {
      wx.hideLoading();
      wx.showToast({ title: `解读失败: ${e.message}`, icon: "none" });
    }
  },
});
