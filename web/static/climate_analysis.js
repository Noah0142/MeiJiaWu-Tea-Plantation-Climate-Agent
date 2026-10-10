// ============================================================
// 分析模块: 对 Open-Meteo 返回数据做基础统计与趋势解读
// analyzeClimateData(qpi, data) -> { timeRange, stats[], trend, tips[], summary }
// ============================================================

const CLIMATE_UNITS = {
  temperature_2m: "℃", apparent_temperature: "℃", relative_humidity_2m: "%",
  precipitation: "mm", rain: "mm", snowfall: "cm",
  wind_speed_10m: "m/s", wind_direction_10m: "°", wind_gusts_10m: "m/s",
  pm2_5: "μg/m³", pm10: "μg/m³", european_aqi: "(EU AQI)",
};

const _mean = (arr) => arr.reduce((a, b) => a + b, 0) / arr.length;

/** EU AQI 等级(0-20 优 / 20-40 良 / 40-60 中等 / 60-80 较差 / >80 差) */
function aqiLevel(value) {
  if (value <= 20) return "优";
  if (value <= 40) return "良";
  if (value <= 60) return "中等";
  if (value <= 80) return "较差";
  return "差";
}

/**
 * 输入: QPI 识别结果 + 接口返回数据(hourly 结构)
 * 输出: 时间范围、各变量统计(最小/最大/平均)、趋势、茶园域提示、总结文本
 */
function analyzeClimateData(qpi, data) {
  const h = data.hourly || {};
  const times = h.time || [];

  // 1) 关键变量统计
  const stats = [];
  for (const v of qpi.variables) {
    const arr = (h[v] || []).filter((x) => x != null);
    if (!arr.length) continue;
    stats.push({
      variable: v, unit: CLIMATE_UNITS[v] || "",
      min: Math.min(...arr), max: Math.max(...arr), mean: _mean(arr),
    });
  }

  const timeRange = times.length
    ? `${times[0].replace("T", " ")} ~ ${times[times.length - 1].replace("T", " ")}`
    : "未知";

  // 2) 趋势: 后半段均值 vs 前半段均值
  const primary = stats[0];
  let trend = "数据不足, 无法判断趋势";
  if (primary) {
    const arr = (h[primary.variable] || []).filter((x) => x != null);
    if (arr.length >= 8) {
      const half = Math.floor(arr.length / 2);
      const delta = _mean(arr.slice(half)) - _mean(arr.slice(0, half));
      const unit = CLIMATE_UNITS[primary.variable] || "";
      trend = Math.abs(delta) < 0.5
        ? "基本平稳"
        : delta > 0
          ? `整体上升约 ${delta.toFixed(1)} ${unit}`
          : `整体下降约 ${Math.abs(delta).toFixed(1)} ${unit}`;
    }
  }

  // 3) 茶园领域提示(结合已核实阈值)
  const tips = [];
  const t2m = (h.temperature_2m || []).filter((x) => x != null);
  if (t2m.some((x) => x <= 4)) tips.push("出现 ≤4℃ 低温时段, 茶园需关注霜冻风险(注意防霜布/熏烟)");
  if (t2m.some((x) => x >= 35)) tips.push("出现 ≥35℃ 高温时段, 需注意高温热害(遮荫/早晚喷灌)");
  const aqi = (h.european_aqi || []).filter((x) => x != null);
  if (aqi.length) tips.push(`欧洲 AQI 均值 ${_mean(aqi).toFixed(0)}, 空气质量${aqiLevel(_mean(aqi))}`);
  if ((h.precipitation || []).some((x) => x != null && x > 5)) tips.push("有小时降水超过 5mm 的时段, 注意田间排水");

  // 4) 总结文本
  const statText = primary
    ? `主要变量 ${primary.variable}: 最低 ${primary.min.toFixed(1)} ${primary.unit}、最高 ${primary.max.toFixed(1)} ${primary.unit}、平均 ${primary.mean.toFixed(1)} ${primary.unit}; 趋势: ${trend}。`
    : "未获取到有效数据。";
  const summary =
    `查询位置: 梅家坞茶园(30.23°N, 120.10°E)。数据时间范围: ${timeRange}。${statText}${tips.length ? tips.join("; ") + "。" : ""}`;

  return { timeRange, stats, trend, tips, summary };
}
