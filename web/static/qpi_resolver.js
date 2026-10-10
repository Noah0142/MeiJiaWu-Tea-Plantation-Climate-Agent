// ============================================================
// QPI 特征识别模块
// resolveQPI(input) -> { type, label, endpoint, variables, confidence }
// 支持中英文混合、不区分大小写; 规则可扩展(在 QPI_RULES 加条目即可)。
// 历史(/archive)作为"修饰符": 命中历史词时保留所识别变量的集合, 只换端点。
// ============================================================

const QPI_RULES = [
  {
    type: "airQuality", label: "空气质量", endpoint: "/air-quality",
    variables: ["pm2_5", "pm10", "european_aqi"],
    keywords: ["air", "aqi", "quality", "空气", "污染", "雾霾", "pm2.5", "pm25", "pm10", "pm 2.5"],
  },
  {
    type: "precipitation", label: "降水", endpoint: "/forecast",
    variables: ["precipitation", "rain", "snowfall"],
    keywords: ["precip", "rain", "snow", "降水", "降雨", "雨", "雪", "下雪", "暴雨"],
  },
  {
    type: "wind", label: "风力", endpoint: "/forecast",
    variables: ["wind_speed_10m", "wind_direction_10m", "wind_gusts_10m"],
    keywords: ["wind", "gust", "风", "风速", "风力", "阵风"],
  },
  {
    type: "temperature", label: "温度", endpoint: "/forecast",
    variables: ["temperature_2m", "apparent_temperature", "relative_humidity_2m"],
    keywords: ["temp", "temperature", "温度", "气温", "warm", "cold", "hot", "heat", "热", "冷", "高温", "低温"],
  },
];

const QPI_HISTORY_KEYWORDS = ["history", "历史", "archive", "past", "过去", "昨天", "上周", "上月", "去年", "回顾"];

const QPI_DEFAULT_VARIABLES = QPI_RULES.find((r) => r.type === "temperature").variables;

/**
 * 输入 QPI 字符串或自然语言, 输出识别结果。
 * 无法匹配时返回 type: 'general'(默认按温度预报查询, confidence 0.2)。
 */
function resolveQPI(input) {
  const text = String(input || "").toLowerCase();
  if (!text.trim()) return qpiResult("general", "综合(默认温度)", "/forecast", QPI_DEFAULT_VARIABLES, 0.2);

  // 逐规则打分: 多词关键词(如 "pm 2.5")命中权重更高
  let best = null;
  let bestScore = 0;
  for (const rule of QPI_RULES) {
    let score = 0;
    for (const kw of rule.keywords) {
      if (text.includes(kw)) score += kw.includes(" ") ? 2 : 1;
    }
    if (score > bestScore) {
      bestScore = score;
      best = rule;
    }
  }

  const isHistory = QPI_HISTORY_KEYWORDS.some((kw) => text.includes(kw));
  const confidence = Math.min(0.95, 0.45 + bestScore * 0.18);

  if (best) {
    // 历史修饰: 变量集合保留, 端点切到 /archive(如"过去一周的降水")
    if (isHistory) {
      return qpiResult("history", `${best.label}·历史`, "/archive", best.variables, confidence);
    }
    return qpiResult(best.type, best.label, best.endpoint, best.variables, confidence);
  }
  if (isHistory) {
    return qpiResult("history", "历史", "/archive", QPI_DEFAULT_VARIABLES, 0.6);
  }
  // 无法识别 -> general, 默认温度预报
  return qpiResult("general", "综合(默认温度)", "/forecast", QPI_DEFAULT_VARIABLES, 0.2);
}

function qpiResult(type, label, endpoint, variables, confidence) {
  return { type, label, endpoint, variables, confidence };
}
