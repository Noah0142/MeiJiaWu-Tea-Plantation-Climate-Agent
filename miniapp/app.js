// 梅家坞茶园微气候智能体 · 小程序全局逻辑
const DEFAULT_API_BASE = "http://127.0.0.1:8000"; // 云端部署后改为你的 Railway 域名(见"数据接入"页)

App({
  globalData: {
    apiBase: DEFAULT_API_BASE,
    theme: "light",
    forecast: null,   // 最近一次预报缓存(供各页复用)
  },

  onLaunch() {
    // API 地址: 优先读取用户在本机保存的设置(数据接入页可修改)
    const saved = wx.getStorageSync("apiBase");
    if (saved) this.globalData.apiBase = saved;

    // 跟随系统深浅色
    const info = wx.getAppBaseInfo ? wx.getAppBaseInfo() : wx.getSystemInfoSync();
    this.globalData.theme = info.theme || "light";
    if (wx.onThemeChange) {
      wx.onThemeChange(({ theme }) => {
        this.globalData.theme = theme;
      });
    }
  },

  setApiBase(base) {
    const v = String(base || "").trim().replace(/\/+$/, "");
    this.globalData.apiBase = v || DEFAULT_API_BASE;
    wx.setStorageSync("apiBase", this.globalData.apiBase);
  },
});
