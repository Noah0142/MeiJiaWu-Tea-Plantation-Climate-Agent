// 数据接入: 服务器地址配置 + 传感器 CSV 上传/移除 + 数据源说明
const api = require("../../utils/api");

Page({
  data: {
    apiBase: "",
    health: null,
    healthText: "",
    sensor: { connected: false },
    uploading: false,
    uploadMsg: "",
    csvDemo: "time,气温,湿度,土壤温度,土壤湿度\n2026-10-11 00:00,17.2,82,19.1,0.35\n2026-10-11 01:00,16.8,84,19.0,0.35",
  },

  onLoad() {
    this.setData({ apiBase: getApp().globalData.apiBase });
    this.checkHealth();
    this.refreshSensor();
  },

  onApiInput(e) {
    this.setData({ apiBase: e.detail.value });
  },

  saveApi() {
    getApp().setApiBase(this.data.apiBase);
    this.setData({ apiBase: getApp().globalData.apiBase });
    wx.showToast({ title: "已保存", icon: "success" });
    this.checkHealth();
    this.refreshSensor();
  },

  async checkHealth() {
    this.setData({ health: null, healthText: "检测中…" });
    try {
      const h = await api.getHealth();
      this.setData({
        health: h,
        healthText: `服务正常 · 地图功能 ${h.map_feature ? "可用" : "不可用"}`,
      });
    } catch (e) {
      this.setData({ health: { ok: false }, healthText: `连接失败: ${e.message}` });
    }
  },

  async refreshSensor() {
    try {
      const s = await api.sensorStatus();
      this.setData({ sensor: s });
    } catch (e) {
      this.setData({ sensor: { connected: false } });
    }
  },

  // 从聊天文件选择 CSV 并上传(小程序环境无本地文件浏览, 需先发到微信任一聊天)
  chooseCsv() {
    wx.chooseMessageFile({
      count: 1,
      type: "file",
      extension: ["csv"],
      success: (res) => {
        const f = res.tempFiles[0];
        this.uploadCsv(f.path, f.name);
      },
      fail: () => {},
    });
  },

  async uploadCsv(filePath, fileName) {
    this.setData({ uploading: true, uploadMsg: "" });
    wx.showLoading({ title: "上传解析中…" });
    try {
      const d = await api.uploadSensorFile(filePath, fileName);
      wx.hideLoading();
      const m = d.meta || {};
      this.setData({
        uploading: false,
        uploadMsg: `接入成功: ${m.rows_hourly} 条逐小时记录(${String(m.time_from || "").slice(0, 16)} ~ ${String(m.time_to || "").slice(0, 16)})已用于预报`,
      });
      this.refreshSensor();
    } catch (e) {
      wx.hideLoading();
      this.setData({ uploading: false, uploadMsg: `接入失败: ${e.message}` });
    }
  },

  removeSensor() {
    wx.showModal({
      title: "移除传感器数据",
      content: "移除后预报输入将回到纯气象站数据, 确定吗?",
      success: async (r) => {
        if (!r.confirm) return;
        try {
          await api.removeSensor();
          this.setData({ uploadMsg: "已移除, 预报输入回到 Open-Meteo 气象站" });
          this.refreshSensor();
        } catch (e) {
          wx.showToast({ title: `移除失败: ${e.message}`, icon: "none" });
        }
      },
    });
  },

  copyDemo() {
    wx.setClipboardData({ data: this.data.csvDemo });
    wx.showToast({ title: "示例已复制", icon: "success" });
  },
});
