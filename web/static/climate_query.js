// ============================================================
// 实时气候数据小卡 · 控制器
// 无需用户输入: 页面加载时自动调用 Open-Meteo /forecast 取梅家坞
// 未来 72h 气温数据, 直接用返回数据画曲线 + 一行统计结论。
// 调用链: climate_card.js -> climate_api.js + climate_analysis.js
// ============================================================

const API_CARD_QPI = {
  type: "temperature", label: "温度", endpoint: "/forecast",
  variables: ["temperature_2m", "apparent_temperature"],
};

let apiCardChart = null;

function initClimateCard() {
  apiCardChart = echarts.init(document.getElementById("api-chart"));
  document.getElementById("api-card-refresh").addEventListener("click", loadClimateCard);
  loadClimateCard();
  setInterval(loadClimateCard, 10 * 60 * 1000); // 每 10 分钟自动更新
}

async function loadClimateCard() {
  const status = document.getElementById("climate-status");
  status.innerHTML = `<span class="spinner"></span> 正在获取 Open-Meteo 数据 …`;
  try {
    const params = buildClimateParams(API_CARD_QPI);
    const data = await fetchClimateData(API_CARD_QPI.endpoint, params);
    const analysis = analyzeClimateData(API_CARD_QPI, data);
    renderApiCard(API_CARD_QPI, data, analysis);
    status.innerHTML = "";
  } catch (err) {
    status.innerHTML = `<span class="chip g3">获取失败</span> <small>${err.message}。可点「更新数据」重试。</small>`;
  }
}

function renderApiCard(qpi, data, analysis) {
  const h = data.hourly || {};
  const times = (h.time || []).map((s) => new Date(s.replace("T", " ")));
  const temps = (h.temperature_2m || []).map((v, i) => (v == null ? null : [times[i], v]));

  const P = chartPalette();  // hex/rgba 调色板, 不用 oklch(悬停重绘会丢面积)

  apiCardChart.setOption({
    backgroundColor: "transparent",
    textStyle: { fontFamily: "Noto Sans SC, sans-serif" },
    grid: { left: 40, right: 16, top: 20, bottom: 30 },
    xAxis: {
      type: "time",
      axisLabel: { formatter: "{MM}-{dd} {HH}:00", color: P.muted },
      axisLine: { lineStyle: { color: P.grid } },
      splitLine: { show: true, lineStyle: { color: P.grid, opacity: 0.5 } },
    },
    yAxis: {
      type: "value", scale: true, name: "℃",
      nameTextStyle: { color: P.muted },
      axisLabel: { color: P.muted },
      splitLine: { lineStyle: { color: P.grid, opacity: 0.5 } },
    },
    tooltip: { trigger: "axis", valueFormatter: (v) => (v == null ? "—" : v + "℃") },
    series: [{
      name: "气温", type: "line", data: temps, smooth: true, symbol: "none",
      lineStyle: { width: 2.2, color: P.primary },
      areaStyle: { color: P.area },
      markPoint: { data: [{ type: "max", name: "最高" }, { type: "min", name: "最低" }],
        label: { fontSize: 10, color: P.text } },
      markLine: { data: [{ type: "average", name: "平均" }],
        label: { fontSize: 10, color: P.muted }, lineStyle: { type: "dashed", color: P.muted } },
    }],
  }, true);

  document.getElementById("api-card-source").textContent =
    `接口: ${qpi.endpoint}(Open-Meteo)`;
  document.getElementById("api-card-updated").textContent =
    `更新于 ${new Date().toLocaleTimeString("zh-CN", { hour12: false })}`;
  const t2m = analysis.stats.find((s) => s.variable === "temperature_2m");
  document.getElementById("api-caption").textContent = t2m
    ? `未来 72h 茶园气温: 最低 ${t2m.min.toFixed(1)}℃ · 最高 ${t2m.max.toFixed(1)}℃ · 平均 ${t2m.mean.toFixed(1)}℃; ${analysis.trend}。${analysis.tips.join("; ")}`
    : analysis.summary;
}

document.addEventListener("DOMContentLoaded", initClimateCard);
