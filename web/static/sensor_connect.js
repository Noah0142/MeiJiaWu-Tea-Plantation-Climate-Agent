// ============================================================
// 传感器数据接入卡 · 控制器
// 茶园传感器实测 CSV 上传 -> 与 Open-Meteo 气象站背景场互补融合 -> 刷新预报。
// 接口: POST /api/sensor/upload | GET /api/sensor/status | DELETE /api/sensor
// ============================================================
"use strict";

function initSensorConnect() {
  $sensor("sensor-upload-btn").addEventListener("click", onSensorUpload);
  $sensor("sensor-remove-btn").addEventListener("click", onSensorRemove);
  refreshSensorStatus();
}

const $sensor = (id) => document.getElementById(id);

async function refreshSensorStatus() {
  const chip = $sensor("sensor-status-chip");
  const info = $sensor("sensor-info");
  try {
    const st = await (await fetch("/api/sensor/status")).json();
    if (st.connected) {
      const m = st.meta;
      chip.textContent = `已接入: ${m.filename || "传感器数据"}`;
      chip.className = "chip g0";
      info.textContent =
        `${m.rows_hourly} 条逐小时记录 · ${String(m.time_from).slice(0, 16)} ~ ${String(m.time_to).slice(0, 16)} · ` +
        `栏目: ${(m.columns || []).join(", ")} · 上传于 ${m.uploaded_at || "—"}; 预报输入 = 传感器实测(锚定) + 气象站背景场(兜底)`;
      $sensor("sensor-remove-btn").hidden = false;
    } else {
      chip.textContent = "未接入(预报使用 Open-Meteo 气象站)";
      chip.className = "chip";
      info.textContent = "";
      $sensor("sensor-remove-btn").hidden = true;
    }
  } catch (e) {
    chip.textContent = "状态获取失败";
    console.warn("传感器状态获取失败:", e);
  }
}

async function onSensorUpload() {
  const status = $sensor("sensor-status");
  const fileInput = $sensor("sensor-file");
  const f = fileInput.files && fileInput.files[0];
  if (!f) {
    status.innerHTML = `<span class="chip g1">请先选择 CSV 文件</span>`;
    return;
  }
  status.innerHTML = `<span class="spinner"></span> 正在解析并接入 ${f.name} …`;
  $sensor("sensor-upload-btn").disabled = true;
  try {
    const fd = new FormData();
    fd.append("file", f, f.name);
    const r = await fetch("/api/sensor/upload", { method: "POST", body: fd });
    const d = await r.json();
    if (!r.ok || !d.ok) throw new Error(d.error || `HTTP ${r.status}`);
    const m = d.meta;
    status.innerHTML =
      `<span class="chip g0">接入成功</span>` +
      `<small>${m.rows_hourly} 条逐小时记录(${String(m.time_from).slice(0, 16)} ~ ${String(m.time_to).slice(0, 16)})已用于预报</small>`;
    fileInput.value = "";
    await refreshSensorStatus();
    await loadForecast();  // 立刻用新输入重算预报(app.js 提供)
  } catch (e) {
    status.innerHTML = `<span class="chip g3">接入失败</span> <small>${e.message}</small>`;
  } finally {
    $sensor("sensor-upload-btn").disabled = false;
  }
}

async function onSensorRemove() {
  const status = $sensor("sensor-status");
  status.innerHTML = `<span class="spinner"></span> 正在移除 …`;
  try {
    await fetch("/api/sensor", { method: "DELETE" });
    status.innerHTML = `<span class="chip g0">已移除</span> <small>预报输入回到纯 Open-Meteo 气象站</small>`;
    await refreshSensorStatus();
    await loadForecast();
  } catch (e) {
    status.innerHTML = `<span class="chip g3">移除失败</span> <small>${e.message}</small>`;
  }
}

document.addEventListener("DOMContentLoaded", initSensorConnect);
