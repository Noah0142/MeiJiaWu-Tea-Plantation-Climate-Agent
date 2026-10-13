/* map.js — 梅家坞茶园: 地图定点查询 + 微气候预测 + AI 解读
   依赖: Leaflet(地图)、ECharts(曲线)、climate_api.js(chartPalette 调色板)
   页面: /map.html; 接口: /api/site/point|predict|overlay|reference-forecast, /api/chat
*/
"use strict";

/* ---------- 1. Bing 卫星瓦片层 (quadkey, WGS84 无偏移) ---------- */
function tileXYToQuadKey(x, y, z) {
  let q = "";
  for (let i = z; i > 0; i--) {
    let d = 0;
    const m = 1 << (i - 1);
    if ((x & m) !== 0) d += 1;
    if ((y & m) !== 0) d += 2;
    q += d;
  }
  return q;
}
const BingSat = L.TileLayer.extend({
  getTileUrl(coords) {
    const q = tileXYToQuadKey(coords.x, coords.y, coords.z);
    const s = (coords.x + coords.y) % 4;
    return `https://ecn.t${s}.tiles.virtualearth.net/tiles/a${q}.jpeg?g=1`;
  },
});

/* ---------- 2. 主题(与大盘共用 localStorage "theme" 键, 两页同步) ---------- */
const rootEl = document.documentElement;
function applyTheme(theme) {
  rootEl.setAttribute("data-theme", theme);
  localStorage.setItem("theme", theme);
  document.getElementById("theme-toggle").textContent = theme === "dark" ? "浅色" : "深色";
  if (lastChartData) renderChart72(lastChartData);
}
function initTheme() {
  const saved = localStorage.getItem("theme");
  const systemDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
  applyTheme(saved || (systemDark ? "dark" : "light"));
  document.getElementById("theme-toggle").addEventListener("click", () => {
    applyTheme(rootEl.getAttribute("data-theme") === "dark" ? "light" : "dark");
  });
}

/* ---------- 3. 地图初始化 ---------- */
const VILLAGE = [30.206, 120.084];
const map = L.map("map", { zoomControl: true, attributionControl: true })
  .setView(VILLAGE, 14);

const bing = new BingSat("", { maxZoom: 19, attribution: "卫星影像 © Bing" });
const osm = L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
  maxZoom: 19, attribution: "© OpenStreetMap",
});
bing.addTo(map);
L.control.layers({ "卫星影像": bing, "街道地图": osm }, {}, { position: "topright" }).addTo(map);
L.control.scale({ imperial: false, position: "bottomleft" }).addTo(map);

/* 梅家坞地形叠加层(山体阴影) */
async function addGridOverlay(layerName) {
  try {
    const r = await (await fetch(`/api/site/overlay?layer=${layerName}`)).json();
    const b = r.bbox;
    L.imageOverlay(r.url + "?t=" + Date.now(), [[b[1], b[0]], [b[3], b[2]]], { opacity: 0.55 })
      .addTo(map);
  } catch (e) { console.warn("地形叠加层加载失败:", e); }
}
addGridOverlay("hillshade");

/* ---------- 4. 选点交互 ---------- */
let marker = null;
let current = null;
let siteOverlay = null;
let chart72 = null;
let lastChartData = null;      // {local, ref} 主题切换时重绘
let refForecast = null;        // 监测点 LightGBM 对照(页面缓存)
let pointContext = "";         // AI 解读上下文
const aiHistory = [];

const $ = (id) => document.getElementById(id);

function aspectText(deg) {
  if (deg == null) return "—";
  const d = ["北", "东北", "东", "东南", "南", "西南", "西", "西北"];
  return d[Math.round(((deg % 360) + 360) % 360 / 45) % 8];
}
function doyDate(doy) {
  if (doy == null) return "—";
  const d = new Date(2025, 0, 1);
  d.setDate(d.getDate() + Math.round(doy) - 1);
  return `${d.getMonth() + 1}月${d.getDate()}日`;
}
const fmt = (v, nd = 1) => (v == null ? "—" : Number(v).toFixed(nd));

function lcTop(lc) {
  if (!lc || !lc.window_pct) return "";
  const rows = Object.entries(lc.window_pct)
    .sort((a, b) => b[1].pct - a[1].pct).slice(0, 3);
  return " (周边: " + rows.map(([c, v]) => `${v.label}${v.pct}%`).join(" / ") + ")";
}

function renderPoint(info) {
  const t = info.terrain || {};
  const mc = info.microclimate_grid || {};
  const cards = [
    ["海拔", `${fmt(t.elevation_m, 0)} <small>m</small>`],
    ["坡度", `${fmt(t.slope_deg)} <small>°</small>`],
    ["坡向", `${aspectText(t.aspect_deg)} <small>${fmt(t.aspect_deg, 0)}°</small>`],
    ["地形位置 TPI", `${fmt(t.tpi_m)} <small>m</small>`],
    ["土地覆盖", info.landcover ? info.landcover.label : "未知"],
  ];
  let html = `<div class="map-grid2">` +
    cards.map(c => `<div class="map-card"><div class="k">${c[0]}</div><div class="v">${c[1]}</div></div>`).join("") +
    `</div>`;
  if (info.source === "meijiawu_grid" && mc.gdd_spring != null) {
    html += `<div class="map-card" style="margin-top:8px">
      <div class="k">该点现有微气候栅格值 (梅家坞分析网格)</div>
      <div class="v" style="font-size:13px;line-height:1.9">
        明前GDD ${fmt(mc.gdd_spring)} °C·d ｜ 霜冻 ${fmt(mc.frost_hours_6yr ?? mc.frost_hours, 0)} h/6年<br>
        春季DTR ${fmt(mc.dtr_spring)} °C ｜ 预计开采 ${doyDate(mc.first_pluck_doy)}
      </div></div>`;
  }
  html += `<p class="note">${info.note || ""}</p>`;
  $("point-box").innerHTML = html;
}

async function queryPoint(lat, lon) {
  $("btn-run").disabled = true;
  $("run-status").textContent = "查询点位地形中…";
  if (marker) marker.setLatLng([lat, lon]);
  else marker = L.marker([lat, lon]).addTo(map);
  current = { lon, lat };
  try {
    const r = await fetch(`/api/site/point?lon=${lon}&lat=${lat}`);
    if (!r.ok) throw new Error((await r.json()).detail || r.statusText);
    renderPoint(await r.json());
    $("btn-run").disabled = false;
    $("run-status").textContent = "";
  } catch (e) {
    $("run-status").innerHTML = `<span class="warn">点位查询失败: ${e.message}</span>`;
    $("btn-run").disabled = true;
  }
}

map.on("click", (e) => queryPoint(e.latlng.lat, e.latlng.lng));

$("presets").addEventListener("click", (e) => {
  const chip = e.target.closest(".chip");
  if (!chip) return;
  const lat = parseFloat(chip.dataset.lat), lon = parseFloat(chip.dataset.lon);
  map.setView([lat, lon], 15);
  queryPoint(lat, lon);
});

/* ---------- 5. 72h 曲线(点位本地降尺度 + 监测点 LightGBM 对照虚线) ---------- */
function renderChart72({ local, ref }) {
  const P = chartPalette();
  // time 轴: ECharts 自动挑选不重叠的刻度(HH:mm 标签太长, category 轴会挤成一团)
  const toDate = (s) => new Date(String(s).replace(" ", "T").slice(0, 16));
  const localData = local.f.times.map((t, i) => [toDate(t), local.f.t2m_local[i]]);
  const hasRef = !!(ref && ref.hourly && ref.hourly.length);
  const series = [{
    name: "点位本地预报", type: "line", data: localData, smooth: true,
    symbol: "none", lineStyle: { color: P.primary, width: 2.2 },
    areaStyle: { color: {
      type: "linear", x: 0, y: 0, x2: 0, y2: 1,
      colorStops: [{ offset: 0, color: P.area }, { offset: 1, color: "rgba(0,0,0,0)" }] } },
    markLine: { silent: true, symbol: "none",
      label: { formatter: "受冻临界 2°C", color: P.danger, fontSize: 10, position: "insideEndTop" },
      lineStyle: { color: P.danger, type: "dashed" }, data: [{ yAxis: 2 }] },
  }];
  if (hasRef) {
    series.push({
      name: "监测点 LightGBM 对照", type: "line",
      data: ref.hourly.slice(0, 72).map(r => [toDate(r.time), r.t2m_p50]),
      smooth: true, symbol: "none",
      lineStyle: { color: P.ref, type: "dashed", width: 1.8 },
    });
  }
  chart72.setOption({
    backgroundColor: "transparent",
    textStyle: { fontFamily: "Noto Sans SC, sans-serif" },
    legend: hasRef ? { top: 0, textStyle: { color: P.muted, fontSize: 10 } } : undefined,
    grid: { left: 38, right: 14, top: hasRef ? 28 : 20, bottom: 24 },
    tooltip: { trigger: "axis",
      valueFormatter: v => (v == null ? "—" : v + "°C") },
    xAxis: { type: "time",
             axisLabel: { formatter: "{MM}-{dd} {HH}:00", color: P.muted, fontSize: 10,
                          hideOverlap: true },
             axisLine: { lineStyle: { color: P.grid } },
             splitLine: { show: false } },
    yAxis: { type: "value", name: "°C", nameTextStyle: { color: P.muted },
             axisLabel: { color: P.muted }, splitLine: { lineStyle: { color: P.grid, opacity: 0.6 } } },
    series,
  }, true);
}

async function fetchReference() {
  if (refForecast) return refForecast;
  try {
    const r = await fetch("/api/site/reference-forecast");
    refForecast = await r.json();
  } catch (e) { console.warn("监测点对照预报获取失败:", e); refForecast = null; }
  return refForecast;
}

/* ---------- 6. 运行模型 ---------- */
function buildContext(resp) {
  const mc = resp.microclimate, f = resp.forecast_72h, t = resp.terrain;
  return [
    `点位坐标: ${resp.lat.toFixed(4)}°N, ${resp.lon.toFixed(4)}°E`,
    `地形: 海拔 ${fmt(t.elevation_m, 0)} m, 坡度 ${fmt(t.slope_deg)}°, 坡向 ${aspectText(t.aspect_deg)}, TPI ${fmt(t.tpi_m)} m`,
    `土地覆盖: ${resp.landcover && resp.landcover.point ? resp.landcover.point.label : "未知"}${lcTop(resp.landcover)}`,
    `微气候指标: 明前GDD ${fmt(mc.gdd_spring)} °C·d, 春季霜冻 ${fmt(mc.frost_hours_6yr, 0)} h/6年, 春季昼夜温差 ${fmt(mc.dtr_spring, 2)} °C, 预计开采 ${doyDate(mc.first_pluck_doy)}`,
    `未来72h本地预报: 最低 ${fmt(f.min_72h)} °C, 最高 ${fmt(f.max_72h)} °C, 霜冻小时 ${fmt(f.frost_hours_next72h, 0)} h, 风险判定: ${f.frost_note}`,
    `(本地预报为物理降尺度模型的演示占位参数结果, 仅作技术展示)`,
  ].join("\n");
}

function renderResult(resp) {
  const mc = resp.microclimate, f = resp.forecast_72h, t = resp.terrain;
  const gradeCls = ["g0", "g1", "g2", "g3"][f.frost_grade] || "g0";
  const html = `
  <div class="map-grid3">
    <div class="map-card"><div class="k">明前积温 GDD</div><div class="v">${fmt(mc.gdd_spring)}<small> °C·d</small></div></div>
    <div class="map-card"><div class="k">春季霜冻 (6年)</div><div class="v">${fmt(mc.frost_hours_6yr, 0)}<small> h</small></div></div>
    <div class="map-card"><div class="k">春季昼夜温差</div><div class="v">${fmt(mc.dtr_spring, 2)}<small> °C</small></div></div>
    <div class="map-card"><div class="k">预计开采期</div><div class="v">${doyDate(mc.first_pluck_doy)}<small> DOY ${fmt(mc.first_pluck_doy, 0)}</small></div></div>
    <div class="map-card"><div class="k">未来72h最低</div><div class="v">${fmt(f.min_72h)}<small> °C</small></div></div>
    <div class="map-card"><div class="k">72h霜冻小时</div><div class="v">${fmt(f.frost_hours_next72h, 0)}<small> h</small></div></div>
  </div>
  <div class="map-card" style="margin-top:8px">
    <div class="k">霜冻风险 (未来 72h)</div>
    <div style="margin-top:6px"><span class="chip ${gradeCls}">${f.frost_note}</span></div>
  </div>
  <div class="map-card" style="margin-top:8px">
    <div class="k">点位地形 · 海拔 ${fmt(t.elevation_m, 0)} m (参考基准 ${fmt(resp.ref_elev_m, 0)} m)</div>
    <div class="v" style="font-size:12px;line-height:1.8">
      坡度 ${fmt(t.slope_deg)}° ｜ 坡向 ${aspectText(t.aspect_deg)} ｜ TPI ${fmt(t.tpi_m)} m
      <br>土地覆盖: ${resp.landcover && resp.landcover.point ? resp.landcover.point.label : "未知"}
      ${lcTop(resp.landcover)}
    </div>
  </div>`;
  $("result-box").innerHTML = html;
  $("win-size").textContent = resp.window.size_km;

  pointContext = buildContext(resp);
  lastChartData = { local: { f } };
  if (!chart72) chart72 = echarts.init($("chart-72h"), null, { renderer: "canvas" });

  // 叠加层
  const b = resp.window.bbox;
  const bounds = [[b[1], b[0]], [b[3], b[2]]];
  if (siteOverlay) map.removeLayer(siteOverlay);
  siteOverlay = L.imageOverlay(resp.overlays.frost72h + "?t=" + Date.now(), bounds,
                               { opacity: 0.75 }).addTo(map);
  currentOverlays = resp.overlays;
  currentOverlayInfo = resp.overlay_info || null;
  currentBounds = bounds;
  map.fitBounds(bounds, { padding: [40, 40], maxZoom: 16 });
  // 初始图层说明
  const info = currentOverlayInfo && currentOverlayInfo.frost72h;
  $("ov-layer-note").textContent = info
    ? (info.has_data ? info.title : `${info.title} — 该图层全为 0, 已显示为透明(底图可见)`)
    : "";
}

let currentOverlays = null, currentBounds = null, currentOverlayInfo = null;
$("ov-picker").addEventListener("click", (e) => {
  const chip = e.target.closest(".ov-chip");
  if (!chip || !currentOverlays) return;
  document.querySelectorAll(".ov-chip").forEach(c => c.classList.remove("on"));
  chip.classList.add("on");
  const name = chip.dataset.ov;
  siteOverlay.setUrl(currentOverlays[name] + "?t=" + Date.now());
  // 该图层数据说明(如: 未来72h无霜冻时全图层透明, 只显示底图)
  const info = currentOverlayInfo && currentOverlayInfo[name];
  const note = $("ov-layer-note");
  if (info && name !== "terrain") {
    note.textContent = info.has_data
      ? `${info.title}`
      : `${info.title} — 该图层全为 0, 已显示为透明(底图可见)`;
  } else {
    note.textContent = "";
  }
});
$("ov-opacity").addEventListener("input", (e) => {
  if (siteOverlay) siteOverlay.setOpacity(e.target.value / 100);
});

$("btn-run").addEventListener("click", async () => {
  if (!current) return;
  const btn = $("btn-run"), status = $("run-status");
  btn.disabled = true;
  status.innerHTML = "运行微气候模型中… 首次在此区域运行需下载历史气象数据 (10-60s)";
  const t0 = Date.now();
  const timer = setInterval(() => {
    status.textContent = `运行中… 已耗时 ${Math.round((Date.now() - t0) / 1000)}s`;
  }, 1000);
  try {
    const r = await fetch("/api/site/predict", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ lon: current.lon, lat: current.lat }),
    });
    if (!r.ok) throw new Error((await r.json()).detail || r.statusText);
    const resp = await r.json();
    clearInterval(timer);
    status.textContent = `完成 (耗时 ${resp.elapsed_s}s)`;
    renderResult(resp);
    const ref = await fetchReference();       // 监测点 LightGBM 对照线
    lastChartData = { local: { f: resp.forecast_72h }, ref };
    renderChart72(lastChartData);
    $("sec-result").hidden = false;
    $("sec-ai").hidden = false;
    $("param-note").textContent =
      "模型参数说明: " + resp.microclimate.params_note + "。" +
      (resp.warnings.length ? " 提示: " + resp.warnings.join("; ") : "") +
      (ref ? ` 蓝色虚线为${ref.label} 72h 预报(监测点高精度时序, 非本点外推)。` : "");
    if (chart72) chart72.resize();
  } catch (e) {
    clearInterval(timer);
    status.innerHTML = `<span class="warn">模型运行失败: ${e.message}</span>`;
  } finally {
    btn.disabled = false;
  }
});

/* ---------- 7. AI 解读(复用 /api/chat, 携带点位上下文) ---------- */
function addAiMsg(role, text) {
  const div = document.createElement("div");
  div.className = "chat-msg " + (role === "user" ? "user" : "agent");
  div.textContent = (role === "user" ? "我: " : "助手: ") + text;
  $("ai-box").appendChild(div);
  $("ai-box").scrollTop = $("ai-box").scrollHeight;
}

async function askAi(question) {
  const status = $("ai-status");
  status.innerHTML = `<span class="spinner"></span> 正在解读…`;
  aiHistory.push({ role: "user", content: question });
  try {
    const r = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ messages: [...aiHistory], context: pointContext }),
    });
    const d = await r.json();
    addAiMsg("assistant", d.reply);
    aiHistory.push({ role: "assistant", content: d.reply });
    status.innerHTML = `<small>引擎: ${d.engine || "未知"}</small>`;
  } catch (e) {
    status.innerHTML = `<span class="warn">解读失败: ${e.message}</span>`;
    aiHistory.pop();
  }
}

$("btn-ai").addEventListener("click", async () => {
  if (!pointContext) return;
  $("btn-ai").disabled = true;
  await askAi("请解读这个点位的微气候情况, 并给出农事建议。");
  $("btn-ai").disabled = false;
});
$("ai-form").addEventListener("submit", (e) => {
  e.preventDefault();
  const input = $("ai-input");
  const q = input.value.trim();
  if (!q) return;
  input.value = "";
  addAiMsg("user", q);
  askAi(q);
});

/* ---------- 8. 启动 ---------- */
initTheme();
queryPoint(VILLAGE[0], VILLAGE[1]);
