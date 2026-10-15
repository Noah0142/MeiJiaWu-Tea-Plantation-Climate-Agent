// 格式化与主题工具
const GRADE_TEXT = ["无", "轻度关注", "中度预警", "重度预警"];
const FROST_TEXT = ["无霜冻", "轻度霜冻", "中度霜冻", "重度霜冻"];
const HEAT_TEXT = ["无热害", "高温关注", "中度热害", "重度热害"];

// 将后端时间字符串(2026-10-13T23:00 / 2026-10-13 23:00)格式化为 "10-13 23时"
function fmtTime(s) {
  if (!s) return "";
  const t = String(s).replace("T", " ");
  return `${t.slice(5, 10)} ${t.slice(11, 13)}时`;
}

// 只取 "MM-DD HH:MM"
function fmtShort(s) {
  if (!s) return "";
  return String(s).replace("T", " ").slice(5, 16);
}

function gradeText(g) {
  return GRADE_TEXT[g] || "无";
}

// 主题色(与 app.wxss 令牌一致, canvas 绘制用)
function palette() {
  const info = wx.getAppBaseInfo ? wx.getAppBaseInfo() : wx.getSystemInfoSync();
  const dark = info.theme === "dark";
  return dark
    ? { bg: "#060e09", surface: "#101a13", text: "#ebe8dc", muted: "#a19e94",
        primary: "#51af6f", amber: "#e7b551", frost: "#6eb7ce", danger: "#e8605b",
        grid: "#223028", band: "rgba(81,175,111,0.16)" }
    : { bg: "#f8f7f1", surface: "#ffffff", text: "#132419", muted: "#536257",
        primary: "#267543", amber: "#b47825", frost: "#357b95", danger: "#c92f33",
        grid: "#e2e6e0", band: "rgba(38,117,67,0.13)" };
}

module.exports = { fmtTime, fmtShort, gradeText, palette, GRADE_TEXT, FROST_TEXT, HEAT_TEXT };
