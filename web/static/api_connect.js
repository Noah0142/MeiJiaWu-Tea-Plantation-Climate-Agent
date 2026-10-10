// ============================================================
// 数据源接入卡 · 控制器(像接入大模型一样接入气象 API)
// 用户输入 API 密钥(当前支持 Open-Meteo, 免费额度可留空)+ 位置,
// 点击「连接」后用 API 返回数据驱动上方: 实时卡片 + 主预报图 + 风险胶囊。
// 密钥只保存在浏览器 localStorage, 随请求作为 apikey 参数使用。
// 调用链: api_connect.js -> climate_api.js -> (复用 app.js 的 render*)
// ============================================================

const FROST_NOTES = [
  "无霜冻风险",
  "轻度霜冻(2~4℃): 嫩叶叶尖或边缘受冻, 关注凌晨低温",
  "中度霜冻(0~2℃): 受冻面积 20%~50%, 建议覆盖防霜布",
  "重度霜冻(最低温<0℃): 芽叶受冻面积可达 50% 以上, 建议立即覆盖/熏烟",
];
const HEAT_NOTES = [
  "无高温热害风险",
  "高温关注(最高≥30℃): 注意墒情",
  "中度高温热害: 芽叶生长受抑, 建议遮荫、增加土壤水分",
  "重度高温热害(最高≥35℃): 新梢灼伤, 建议遮荫+早晚喷灌",
];

function jsGradeFrost(tmin) {
  if (tmin == null) return 0;
  if (tmin < 0) return 3;
  if (tmin < 2) return 2;
  if (tmin <= 4) return 1;
  return 0;
}
function jsGradeHeat(tmax) {
  if (tmax == null) return 0;
  if (tmax >= 35) return 3;
  if (tmax >= 33) return 2;
  if (tmax >= 30) return 1;
  return 0;
}

/** 把 Open-Meteo /forecast 响应转成页面 FORECAST 结构(不含虚构的不确定性区间) */
function buildForecastFromApi(data) {
  const h = data.hourly || {};
  const times = h.time || [];
  const hourly = times.map((t, i) => {
    const v = h.temperature_2m?.[i];
    return {
      time: t.replace(" ", "T"),
      t2m_p50: v == null ? null : Math.round(v * 10) / 10,
      t2m_p10: v == null ? null : Math.round(v * 10) / 10,  // 无区间数据时不虚构
      t2m_p90: v == null ? null : Math.round(v * 10) / 10,
      rh: h.relative_humidity_2m?.[i] == null ? null : Math.round(h.relative_humidity_2m[i]),
    };
  });
  const risk = { windows: {}, coldspell_april_dates: [] };
  for (const hh of [24, 48, 72]) {
    const seg = hourly.slice(0, hh).map((r) => r.t2m_p50).filter((v) => v != null);
    const tmin = seg.length ? Math.min(...seg) : null;
    const tmax = seg.length ? Math.max(...seg) : null;
    const fg = jsGradeFrost(tmin), hg = jsGradeHeat(tmax);
    risk.windows[`${hh}h`] = {
      tmin_p50: tmin, tmin_p10: tmin, tmax_p90: tmax,
      frost_grade: fg, frost_note: FROST_NOTES[fg],
      frost_grade_conservative: fg, frost_note_conservative: FROST_NOTES[fg],
      heat_grade: hg, heat_note: HEAT_NOTES[hg],
    };
  }
  return {
    site: { name: "梅家坞茶园(API 数据源)" },
    issued_at: times[0] ? times[0].replace(" ", "T") : new Date().toISOString().slice(0, 16),
    history: FORECAST.history,  // 保留后端传感器历史
    api_current: data.current
      ? { t2m: data.current.temperature_2m, rh: data.current.relative_humidity_2m }
      : null,
    hourly, risk,
  };
}

function initApiConnect() {
  const saved = JSON.parse(localStorage.getItem("apiConnect") || "{}");
  if (saved.key) document.getElementById("api-key-input").value = saved.key;
  if (saved.lat) document.getElementById("api-lat-input").value = saved.lat;
  if (saved.lon) document.getElementById("api-lon-input").value = saved.lon;
  document.getElementById("api-connect-btn").addEventListener("click", connectApi);
  document.getElementById("api-reset-btn").addEventListener("click", resetToModel);
}

async function connectApi() {
  const status = document.getElementById("api-connect-status");
  const btn = document.getElementById("api-connect-btn");
  const key = document.getElementById("api-key-input").value.trim();
  const lat = parseFloat(document.getElementById("api-lat-input").value);
  const lon = parseFloat(document.getElementById("api-lon-input").value);
  if (!Number.isFinite(lat) || !Number.isFinite(lon) || Math.abs(lat) > 90 || Math.abs(lon) > 180) {
    status.innerHTML = `<span class="chip g3">参数错误</span> <small>请填写有效的纬度/经度。</small>`;
    return;
  }
  status.innerHTML = `<span class="spinner"></span> 正在连接 Open-Meteo 并拉取数据 …`;
  btn.disabled = true;
  try {
    const data = await fetchClimateData("/forecast", {
      latitude: lat, longitude: lon, timezone: "Asia/Shanghai", forecast_days: 3,
      hourly: ["temperature_2m", "relative_humidity_2m", "precipitation",
               "wind_speed_10m", "wind_direction_10m"],
    }, key || undefined);
    FORECAST = buildForecastFromApi(data);
    window.API_DRIVEN = true;
    localStorage.setItem("apiConnect", JSON.stringify({ key, lat, lon }));
    renderCards();
    renderChart();
    renderRisk();
    renderApiJson();
    status.innerHTML = `<span class="chip g0">已连接 Open-Meteo</span>
      <small>数据已用于上方卡片、预报曲线与风险胶囊(纬度 ${lat}, 经度 ${lon})</small>`;
    document.getElementById("api-reset-btn").hidden = false;
  } catch (err) {
    status.innerHTML = `<span class="chip g3">连接失败</span> <small>${err.message}。请检查密钥或网络后重试。</small>`;
  } finally {
    btn.disabled = false;
  }
}

async function resetToModel() {
  const status = document.getElementById("api-connect-status");
  status.innerHTML = `<span class="spinner"></span> 正在恢复默认模型预报 …`;
  try {
    const res = await fetch("/api/forecast");
    FORECAST = await res.json();
    window.API_DRIVEN = false;
    renderCards();
    renderChart();
    renderSensorCharts();
    renderRisk();
    renderApiJson();
    status.innerHTML = `<span class="chip g0">已恢复</span> <small>上方卡片与曲线回到本地微气候模型预报。</small>`;
    document.getElementById("api-reset-btn").hidden = true;
  } catch (err) {
    status.innerHTML = `<span class="chip g3">恢复失败</span> <small>${err.message}</small>`;
  }
}

document.addEventListener("DOMContentLoaded", initApiConnect);
