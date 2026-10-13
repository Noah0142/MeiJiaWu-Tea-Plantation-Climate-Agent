// ============================================================
// API 调用层 · Open-Meteo 免费气象接口(无需 API Key)
// 通用函数 fetchClimateData(endpoint, params) -> JSON
//   endpoint: '/forecast' | '/air-quality' | '/archive'
//   params:   { latitude, longitude, hourly: [...], ... }
// 注: 空气质量接口实际部署在 air-quality-api.open-meteo.com,
//     这里自动切换主机, 调用方无需感知。
// ============================================================

const CLIMATE_API_BASE = "https://api.open-meteo.com/v1/";
const AIR_QUALITY_API_BASE = "https://air-quality-api.open-meteo.com/v1/";
const ARCHIVE_API_BASE = "https://archive-api.open-meteo.com/v1/";

/** 梅家坞茶园坐标(与项目其余模块一致) */
const CLIMATE_LOCATION = { latitude: 30.2272, longitude: 120.1014, timezone: "Asia/Shanghai" };

/**
 * 图表调色板(hex/rgba, 按主题)。
 * 注意: 图表元素不要用 oklch() 颜色串 —— ECharts 在悬停 emphasis 重绘
 * areaStyle 时无法正确解析 oklch, 会导致面积填充整块消失(线条消失 bug)。
 */
const CHART_PALETTE = {
  dark: {
    primary: "#51af6f", primaryDim: "#22683b", text: "#ebe8dc", muted: "#a19e94",
    grid: "#354039", band: "rgba(81,175,111,0.13)", area: "rgba(81,175,111,0.15)",
    ref: "#58a6ff", danger: "#f85149",
  },
  light: {
    primary: "#267543", primaryDim: "#5a966b", text: "#132419", muted: "#536257",
    grid: "#d9e0db", band: "rgba(38,117,67,0.12)", area: "rgba(38,117,67,0.12)",
    ref: "#2f6fd0", danger: "#d1242f",
  },
};

/** 返回当前主题的图表调色板 */
function chartPalette() {
  const theme = document.documentElement.getAttribute("data-theme");
  return CHART_PALETTE[theme === "light" ? "light" : "dark"];
}

/**
 * 调用 Open-Meteo 接口并返回解析后的 JSON。
 * apiKey 可选(Open-Meteo 免费额度无需密钥; 传入时作为 apikey 参数附加)。
 * 失败时抛出带用户可读信息的 Error(由调用方展示)。
 */
async function fetchClimateData(endpoint, params, apiKey) {
  const host = endpoint === "/air-quality" ? AIR_QUALITY_API_BASE
    : endpoint === "/archive" ? ARCHIVE_API_BASE
    : CLIMATE_API_BASE;
  const url = new URL(host + endpoint.replace(/^\//, ""));
  Object.entries(params).forEach(([key, value]) => {
    if (Array.isArray(value)) {
      value.forEach((v) => url.searchParams.append(key, v));
    } else {
      url.searchParams.set(key, String(value));
    }
  });
  if (apiKey) url.searchParams.set("apikey", apiKey);
  let res;
  try {
    res = await fetch(url.toString(), { signal: AbortSignal.timeout(30000) });
  } catch {
    throw new Error("网络请求失败, 请检查网络连接");
  }
  if (!res.ok) throw new Error(`接口返回 HTTP ${res.status}`);
  const data = await res.json();
  if (data.error) throw new Error(data.reason || "Open-Meteo 返回了错误");
  return data;
}

/**
 * 根据 QPI 识别结果构造各端点的请求参数。
 * /archive 取最近 7 天; /forecast 取未来 3 天; /air-quality 为当前逐小时。
 */
function buildClimateParams(qpi) {
  const params = { ...CLIMATE_LOCATION };
  if (qpi.endpoint === "/archive") {
    // 归档数据(ERA5)有约 5 天延迟: 取 [今天-10天, 今天-3天] 保证有数据
    const end = new Date();
    end.setDate(end.getDate() - 3);
    const start = new Date();
    start.setDate(start.getDate() - 10);
    params.start_date = start.toISOString().slice(0, 10);
    params.end_date = end.toISOString().slice(0, 10);
  } else if (qpi.endpoint !== "/air-quality") {
    params.forecast_days = 3;
  }
  params.hourly = qpi.variables;
  return params;
}
