// 网络请求封装: 拼接 API 地址 + 统一错误处理
function request(path, options = {}) {
  const app = getApp();
  return new Promise((resolve, reject) => {
    wx.request({
      url: app.globalData.apiBase + path,
      method: options.method || "GET",
      data: options.data,
      header: { "content-type": "application/json" },
      timeout: options.timeout || 120000,
      success(res) {
        if (res.statusCode >= 200 && res.statusCode < 300) {
          resolve(res.data);
        } else {
          const d = res.data || {};
          reject(new Error(d.detail || d.error || `HTTP ${res.statusCode}`));
        }
      },
      fail(err) {
        reject(new Error(err.errMsg ? err.errMsg.replace("request:fail ", "") : "网络请求失败"));
      },
    });
  });
}

// 传感器 CSV 上传(小程序只能从聊天文件选择)
function uploadSensorFile(filePath, fileName) {
  const app = getApp();
  return new Promise((resolve, reject) => {
    wx.uploadFile({
      url: app.globalData.apiBase + "/api/sensor/upload",
      filePath,
      name: "file",
      formData: { filename: fileName },
      timeout: 120000,
      success(res) {
        try {
          const d = JSON.parse(res.data || "{}");
          if (res.statusCode >= 200 && res.statusCode < 300 && d.ok) resolve(d);
          else reject(new Error(d.error || d.detail || `HTTP ${res.statusCode}`));
        } catch (e) {
          reject(new Error("返回内容解析失败"));
        }
      },
      fail(err) {
        reject(new Error(err.errMsg ? err.errMsg.replace("uploadFile:fail ", "") : "上传失败"));
      },
    });
  });
}

module.exports = {
  request,
  uploadSensorFile,

  // ---- 业务接口 ----
  getForecast: () => request("/api/forecast", { timeout: 180000 }),
  getSummary: () => request("/api/summary"),
  chat: (messages, context) => request("/api/chat", { method: "POST", data: { messages, context } }),
  getHealth: () => request("/api/health", { timeout: 30000 }),
  sensorStatus: () => request("/api/sensor/status"),
  removeSensor: () => request("/api/sensor", { method: "DELETE" }),
  sitePoint: (lat, lon) => request(`/api/site/point?lat=${lat}&lon=${lon}`, { timeout: 60000 }),
  sitePredict: (lat, lon) => request("/api/site/predict", { method: "POST", data: { lat, lon }, timeout: 300000 }),
  siteOverlay: (layer = "hillshade") => request(`/api/site/overlay?layer=${layer}`, { timeout: 60000 }),
};
