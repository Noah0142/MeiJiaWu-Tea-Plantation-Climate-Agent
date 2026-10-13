// 梅家坞茶园微气候智能体 · 前端逻辑
// 数据源: GET /api/forecast(模型预报) / GET /api/summary(农事建议) / POST /api/chat(多轮对话)

let FORECAST = null;
const CHAT_HISTORY = [{ role: "assistant", content: "您好! 我是梅家坞茶园微气候助手。" }];
const chart = echarts.init(document.getElementById("chart"), null, { renderer: "canvas" });

// ---------- 主题与令牌 ----------
const rootEl = document.documentElement;
const cssVar = (name) => getComputedStyle(rootEl).getPropertyValue(name).trim();
const withAlpha = (name, a) => cssVar(name).replace(/\)$/, ` / ${a})`);

function initTheme() {
  const saved = localStorage.getItem("theme");
  const systemDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
  const theme = saved || (systemDark ? "dark" : "light");
  applyTheme(theme);
  document.getElementById("theme-toggle").addEventListener("click", () => {
    applyTheme(rootEl.getAttribute("data-theme") === "dark" ? "light" : "dark");
  });
}
function applyTheme(theme) {
  rootEl.setAttribute("data-theme", theme);
  localStorage.setItem("theme", theme);
  document.getElementById("theme-toggle").textContent = theme === "dark" ? "浅色" : "深色";
  if (FORECAST) { renderChart(); renderSensorCharts(); }
  if (typeof loadClimateCard === "function") loadClimateCard(); // 实时数据小卡随主题重渲
}

document.addEventListener("DOMContentLoaded", () => {
  initTheme();
  loadForecast();
  loadSummary();
  document.getElementById("chat-form").addEventListener("submit", onChatSubmit);
  document.querySelectorAll("#quick-chips .chip").forEach((b) =>
    b.addEventListener("click", () => {
      const input = document.getElementById("chat-input");
      input.value = b.dataset.q;
      document.getElementById("chat-form").requestSubmit();
    })
  );
  setInterval(loadForecast, 2 * 60 * 1000);
});

async function loadForecast() {
  const res = await fetch("/api/forecast");
  FORECAST = await res.json();
  renderCards();
  renderChart();
  renderSensorCharts();
  renderRisk();
  renderApiJson();
}

function renderCards() {
  const h = FORECAST.hourly;
  const srcText = `${(FORECAST.data_source || "Open-Meteo").split("(")[0].trim()} · 每 2 分钟刷新`;
  document.getElementById("issued-at").textContent =
    `${FORECAST.issued_at.replace("T", " ").slice(0, 16)} 起报 · 数据源 ${srcText}`;
  document.getElementById("card-tnow").textContent = FORECAST.history.at(-1).t2m + "℃";
  document.getElementById("card-tnow-t").textContent =
    `实况时间 ${FORECAST.history.at(-1).time.replace("T", " ")}`;
  document.getElementById("card-rh").textContent = (h[0].rh ?? "—") + "%";
  const w24 = FORECAST.risk.windows["24h"], w72 = FORECAST.risk.windows["72h"];
  document.getElementById("card-tmin").textContent = w24.tmin_p50 + "℃";
  document.getElementById("card-frost").textContent = "霜冻风险: " + gradeText(w24.frost_grade);
  document.getElementById("card-tmax").textContent = w72.tmax_p90 + "℃";
  document.getElementById("card-heat").textContent = "高温风险: " + gradeText(w72.heat_grade);
}

function gradeText(g) {
  return ["无", "轻度关注", "中度预警", "重度预警"][g ?? 0];
}

// ---------- 主预报图 ----------
function renderChart() {
  // 时间一律转 Date 并走 time 轴; 图表颜色一律用 hex/rgba 调色板(见 climate_api.js
  // 的说明: oklch 颜色串会在悬停重绘时导致面积/线条丢失)
  const P = chartPalette();
  const toDate = (s) => new Date(s.replace(" ", "T"));
  const times = [...FORECAST.history.map(r => toDate(r.time)), ...FORECAST.hourly.map(r => toDate(r.time))];
  const obs = [...FORECAST.history.map(r => r.t2m), ...FORECAST.hourly.map(() => null)];
  const p50 = [...FORECAST.history.map(() => null), ...FORECAST.hourly.map(r => r.t2m_p50)];
  const p10 = [...FORECAST.history.map(() => null), ...FORECAST.hourly.map(r => r.t2m_p10)];
  const p90 = [...FORECAST.history.map(() => null), ...FORECAST.hourly.map(r => r.t2m_p90)];
  const mark = toDate(FORECAST.issued_at);
  chart.setOption({
    backgroundColor: "transparent",
    textStyle: { fontFamily: "Noto Sans SC, sans-serif" },
    tooltip: { trigger: "axis", valueFormatter: v => (v == null ? "—" : v + "℃") },
    legend: { data: ["实况", "预报 P50", "80% 区间"], textStyle: { color: P.muted } },
    grid: { left: 42, right: 20, top: 44, bottom: 60 },
    xAxis: {
      type: "time",
      axisLabel: { formatter: "{MM}-{dd} {HH}:00", color: P.muted },
      axisLine: { lineStyle: { color: P.grid } },
      splitLine: { show: true, lineStyle: { color: P.grid, opacity: 0.5 } },
    },
    yAxis: {
      type: "value", name: "℃", scale: true,
      nameTextStyle: { color: P.muted },
      axisLabel: { color: P.muted },
      splitLine: { lineStyle: { color: P.grid, opacity: 0.5 } },
    },
    series: [
      // 置信区间带: 用 markArea 逐小时竖条绘制(ECharts 5/6 的 stack+areaStyle
      // 在悬停 emphasis 重绘时会整块丢失, markArea 无此问题)
      { name: "80% 区间", type: "line", data: p90.map((v, i) => [times[i], v]),
        lineStyle: { opacity: 0 }, symbol: "none",
        markArea: {
          silent: true,
          itemStyle: { color: P.band },
          data: buildBandStrips(times, p10, p90),
        },
        markLine: { silent: true, symbol: "none",
          lineStyle: { type: "dashed", color: P.muted },
          label: { formatter: "起报", position: "end", color: P.muted },
          data: [{ xAxis: mark }] } },
      { name: "实况", type: "line", data: obs.map((v, i) => [times[i], v]), color: P.text,
        showSymbol: false, lineStyle: { width: 1.5 } },
      { name: "预报 P50", type: "line", data: p50.map((v, i) => [times[i], v]), color: P.primary,
        showSymbol: false, lineStyle: { width: 2.2 } },
    ],
  }, true);
}

/** 由 P10/P90 数组构造 markArea 逐小时竖条(每个条: [起点{P10}, 终点{P90}]) */
function buildBandStrips(times, p10, p90) {
  const HALF_HOUR = 30 * 60 * 1000;
  const strips = [];
  for (let i = 0; i < times.length; i++) {
    if (p10[i] == null || p90[i] == null) continue;
    const t = times[i].getTime();
    strips.push([
      { xAxis: t - HALF_HOUR, yAxis: p10[i] },
      { xAxis: t + HALF_HOUR, yAxis: p90[i] },
    ]);
  }
  return strips;
}

// ---------- 历史实况曲线(统一浅绿, 与主预报图一致) ----------
function renderSensorCharts() {
  const s = FORECAST.sensor || [];
  const t = r => new Date(r.time.replace(" ", "T"));
  const series = key => s.map(r => [t(r), r[key] == null ? null : r[key]]);

  buildSensorChart("sensor-temp", {
    name: "气温", unit: "°C",
    data: series("temperature"),
    forecast: FORECAST.hourly.map(r => [new Date(r.time.replace(" ", "T")), r.t2m_p50]),
  });
  buildSensorChart("sensor-hum", {
    name: "湿度", unit: "%",
    data: series("humidity"),
    forecast: FORECAST.hourly.map(r => [new Date(r.time.replace(" ", "T")), r.rh]),
  });
  buildSensorChart("sensor-soilt", {
    name: "土壤温度(0cm)", unit: "°C",
    data: series("soil_temperature"),
  });
  buildSensorChart("sensor-soilm", {
    name: "土壤湿度(1–3cm)", unit: "m³/m³",
    data: series("soil_moisture"),
  });
}

function buildSensorChart(domId, cfg) {
  const el = document.getElementById(domId);
  const inst = echarts.getInstanceByDom(el) || echarts.init(el);
  const P = chartPalette();
  const series = [{
    name: cfg.name, type: "line", data: cfg.data, smooth: true,
    symbol: "none",
    lineStyle: { width: 2.4, color: P.primary },
    areaStyle: { color: P.area },
    markPoint: { data: [{ type: "max", name: "最高" }, { type: "min", name: "最低" }],
      label: { fontSize: 10, color: P.text } },
    markLine: { data: [{ type: "average", name: "平均" }],
      label: { fontSize: 10, color: P.muted },
      lineStyle: { type: "dashed", color: P.muted } },
  }];
  if (cfg.forecast) {
    series.push({ name: "预报", type: "line", data: cfg.forecast, symbol: "none",
      lineStyle: { type: "dashed", width: 2, color: P.primaryDim } });
  }
  inst.setOption({
    backgroundColor: "transparent",
    textStyle: { fontFamily: "Noto Sans SC, sans-serif" },
    grid: { left: 8, right: 8, top: 28, bottom: 42, containLabel: true },
    legend: cfg.forecast ? { top: 0, textStyle: { color: P.muted } } : undefined,
    xAxis: { type: "time", axisLabel: { formatter: "{MM}-{dd} {HH}:00", color: P.muted },
      axisLine: { lineStyle: { color: P.grid } },
      splitLine: { show: true, lineStyle: { color: P.grid, opacity: 0.4 } } },
    yAxis: { type: "value", scale: true, axisLabel: { formatter: `{value} ${cfg.unit}`, color: P.muted },
      splitLine: { lineStyle: { color: P.grid, opacity: 0.4 } } },
    series: series,
    tooltip: {
      trigger: "axis",
      valueFormatter: v => (v == null ? "—" : (typeof v === "number" ? v.toFixed(cfg.unit === "m³/m³" ? 3 : 1) : v) + " " + cfg.unit),
      position: function (point, params, dom) {
        const w = dom.offsetWidth, h = dom.offsetHeight;
        let x = point[0];
        if (x + w > inst.getWidth()) x = point[0] - w;
        return [x, point[1] - h];
      },
    },
    dataZoom: [{ type: "inside" }, { type: "slider", height: 16, bottom: 4 }],
  }, true);
  return inst;
}

// ---------- 风险面板 ----------
const FROST_LABELS = ["无霜冻", "轻度霜冻", "中度霜冻", "重度霜冻"];
const HEAT_LABELS = ["无热害", "高温关注", "中度热害", "重度热害"];

function renderRisk() {
  const el = document.getElementById("risk-panel");
  el.innerHTML = ["24h", "48h", "72h"].map(k => {
    const w = FORECAST.risk.windows[k];
    const fg = w.frost_grade ?? 0, hg = w.heat_grade ?? 0;
    return `<div class="risk-window">
      <b>未来 ${k}</b>
      <span><span class="chip g${fg}">${FROST_LABELS[fg]}</span>
            <span class="chip g${hg}">${HEAT_LABELS[hg]}</span></span>
      <span class="detail">最低 ${w.tmin_p50}℃(P10 保守 ${w.tmin_p10}℃) · 最高 ${w.tmax_p90}℃</span>
    </div>`;
  }).join("");
}

function renderApiJson() {
  document.getElementById("api-json").textContent = JSON.stringify(FORECAST, null, 2);
}

// ---------- Agent ----------
async function loadSummary() {
  const res = await fetch("/api/summary");
  const d = await res.json();
  document.getElementById("agent-summary").textContent = d.summary;
}

async function onChatSubmit(e) {
  e.preventDefault();
  const input = document.getElementById("chat-input");
  const text = input.value.trim();
  if (!text) return;
  input.value = "";
  addMsg("user", text);
  addMsg("agent", "思考中…", true);
  const history = [...CHAT_HISTORY, { role: "user", content: text }];
  try {
    const res = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ messages: history }),
    });
    const d = await res.json();
    removePending();
    addMsg("agent", d.reply);
    document.getElementById("chat-engine").textContent = `引擎: ${d.engine || "未知"}`;
    CHAT_HISTORY.push({ role: "user", content: text }, { role: "assistant", content: d.reply });
  } catch (err) {
    removePending();
    addMsg("agent", "网络出错, 请稍后再试。");
  }
}

function addMsg(role, text, pending = false) {
  const box = document.getElementById("chat-box");
  const div = document.createElement("div");
  div.className = "chat-msg " + (role === "user" ? "user" : "agent");
  if (pending) div.id = "chat-pending";
  div.textContent = (role === "user" ? "我: " : "助手: ") + text;
  box.appendChild(div);
  box.scrollTop = box.scrollHeight;
}

function removePending() {
  const p = document.getElementById("chat-pending");
  if (p) p.remove();
}
