// 大盘页: 状态条 + 指标卡 + 72h 预报图 + 风险预警 + AI 农事建议
const api = require("../../utils/api");
const { fmtTime, fmtShort, FROST_TEXT, HEAT_TEXT, GRADE_TEXT } = require("../../utils/format");

Page({
  data: {
    loading: true,
    error: "",
    issuedAt: "",
    dataSource: "",
    cards: { tnow: "—", rh: "—", tmin: "—", tmax: "—", tnowTime: "", frost: "—", heat: "—" },
    chartHours: [],
    riskRows: [],
    summary: "",
    summaryLoading: true,
  },

  onLoad() {
    this.loadAll();
  },

  onShow() {
    // 从其他页返回时刷新(数据源可能已切换)
    if (this.loadedOnce) this.loadAll();
  },

  onPullDownRefresh() {
    this.loadAll().finally(() => wx.stopPullDownRefresh());
  },

  async loadAll() {
    this.loadedOnce = true;
    this.setData({ loading: !this.data.issuedAt, error: "" });
    try {
      const fc = await api.getForecast();
      getApp().globalData.forecast = fc;

      const h = fc.hourly || [];
      const hist = fc.history || [];
      const w24 = (fc.risk && fc.risk.windows && fc.risk.windows["24h"]) || {};
      const w72 = (fc.risk && fc.risk.windows && fc.risk.windows["72h"]) || {};

      this.setData({
        loading: false,
        issuedAt: fmtShort(fc.issued_at),
        dataSource: (fc.data_source || "Open-Meteo").split("(")[0].trim(),
        cards: {
          tnow: hist.length ? hist[hist.length - 1].t2m : "—",
          tnowTime: hist.length ? fmtShort(hist[hist.length - 1].time) : "",
          rh: h.length ? h[0].rh : "—",
          tmin: w24.tmin_p50 != null ? w24.tmin_p50 : "—",
          tmax: w72.tmax_p90 != null ? w72.tmax_p90 : "—",
          frost: GRADE_TEXT[w24.frost_grade || 0],
          heat: GRADE_TEXT[w72.heat_grade || 0],
        },
        chartHours: h.map((r) => ({
          label: fmtTime(r.time),
          p10: r.t2m_p10,
          p50: r.t2m_p50,
          p90: r.t2m_p90,
        })),
        riskRows: ["24h", "48h", "72h"].map((k) => {
          const w = (fc.risk && fc.risk.windows && fc.risk.windows[k]) || {};
          return {
            label: `未来 ${k}`,
            frostText: FROST_TEXT[w.frost_grade || 0],
            frostGrade: w.frost_grade || 0,
            heatText: HEAT_TEXT[w.heat_grade || 0],
            heatGrade: w.heat_grade || 0,
            detail: `最低 ${w.tmin_p50}℃(P10 ${w.tmin_p10}℃) · 最高 ${w.tmax_p90}℃`,
          };
        }),
      });
    } catch (e) {
      this.setData({ loading: false, error: e.message || "加载失败" });
    }
    this.loadSummary();
  },

  async loadSummary() {
    this.setData({ summaryLoading: true });
    try {
      const d = await api.getSummary();
      this.setData({ summary: d.summary || "", summaryLoading: false });
    } catch (e) {
      this.setData({ summary: "", summaryLoading: false });
    }
  },

  onChatTap() {
    wx.switchTab({ url: "/pages/chat/chat" });
  },
});
