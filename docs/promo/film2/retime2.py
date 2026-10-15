# -*- coding: utf-8 -*-
"""retime2.py — 把 comp2.html 的镜头重排成"走一段—停一段", 静止窗内关掉手持浮动,
并把画面元素(标注/图解/图层卡/落版字)的出现时间对齐到运镜段(motion 段)。"""
import pathlib
import re

p = pathlib.Path(__file__).parent / "comp2.html"
s = p.read_text(encoding="utf-8")

KEYS = """const KEYS = [
  { t: 0,     y: 540,  zoom: 1.0 },
  { t: 3.5,   y: 572,  zoom: 1.05, curve: E.sineInOut },
  { t: 6.1,   y: 572,  zoom: 1.05 },
  { t: 7.9,   y: 585,  zoom: 1.06, curve: E.sineInOut },
  { t: 10.5,  y: 585,  zoom: 1.06 },
  { t: 12.3,  y: 600,  zoom: 1.07, curve: E.sineInOut },
  { t: 13.9,  y: 600,  zoom: 1.07 },
  { t: 15.4,  y: 780,  zoom: 1.02, curve: E.expoInOut },
  { t: 16.9,  y: 1620, zoom: 0.99, curve: E.expoInOut },
  { t: 19.9,  y: 1620, zoom: 0.99 },
  { t: 21.3,  y: 1660, zoom: 1.0, curve: E.sineInOut },
  { t: 23.6,  y: 2540, zoom: 0.97, curve: E.quintInOut },
  { t: 27.0,  y: 2540, zoom: 0.97 },
  { t: 28.4,  y: 2630, zoom: 1.1, curve: E.sineInOut },
  { t: 32.0,  y: 2630, zoom: 1.1 },
  { t: 33.4,  y: 2700, zoom: 1.06, curve: E.sineInOut },
  { t: 36.4,  y: 3250, zoom: 1.02, curve: E.expoInOut },
  { t: 38.6,  y: 4010, zoom: 0.97, curve: E.expoInOut },
  { t: 41.6,  y: 4010, zoom: 0.97 },
  { t: 42.6,  y: 4030, zoom: 1.0, curve: E.sineInOut },
  { t: 45.4,  y: 4030, zoom: 1.0 },
  { t: 46.6,  y: 4400, zoom: 0.93, curve: E.quintInOut },
  { t: 48.4,  y: 4400, zoom: 0.93 },
  { t: 50.9,  y: 5240, zoom: 1.0, curve: E.expoInOut },
  { t: 54.1,  y: 5240, zoom: 1.0 },
  { t: 55.5,  y: 5300, zoom: 0.94, curve: E.sineInOut },
  { t: 59.3,  y: 5300, zoom: 0.94 },
  { t: 60.7,  y: 6080, zoom: 1.06, curve: E.quintInOut },
  { t: 64.5,  y: 6080, zoom: 1.06 },
  { t: 65.9,  y: 6100, zoom: 1.09, curve: E.sineInOut },
  { t: 69.5,  y: 6100, zoom: 1.09 },
  { t: 70.9,  y: 6140, zoom: 1.07, curve: E.sineInOut },
  { t: 74.3,  y: 6140, zoom: 1.07 },
  { t: 77.4,  y: 6900, zoom: 0.99, curve: E.expoInOut },
  { t: 80.2,  y: 6900, zoom: 0.99 },
  { t: 81.6,  y: 7000, zoom: 1.02, curve: E.sineInOut },
  { t: 84.8,  y: 7000, zoom: 1.02 },
  { t: 86.2,  y: 7100, zoom: 1.03, curve: E.sineInOut },
  { t: 89.6,  y: 7100, zoom: 1.03 },
  { t: 91.0,  y: 7250, zoom: 1.02, curve: E.sineInOut },
  { t: 94.2,  y: 7250, zoom: 1.02 },
  { t: 95.6,  y: 7440, zoom: 1.05, curve: E.sineInOut },
  { t: 99.0,  y: 7440, zoom: 1.05 },
  { t: 100.4, y: 7470, zoom: 1.08, curve: E.sineInOut },
  { t: 104.6, y: 7470, zoom: 1.08 },
  { t: 106.0, y: 7500, zoom: 1.05, curve: E.sineInOut },
  { t: 110.0, y: 7500, zoom: 1.05 },
  { t: 111.6, y: 7900, zoom: 0.99, curve: E.quintInOut },
  { t: 112.9, y: 8140, zoom: 1.0, curve: E.expoInOut },
  { t: 116.1, y: 8140, zoom: 1.0 },
  { t: 117.5, y: 8200, zoom: 0.93, curve: E.sineInOut },
  { t: 121.1, y: 8200, zoom: 0.93 },
  { t: 122.5, y: 8215, zoom: 0.94, curve: E.sineInOut },
  { t: 126.1, y: 8215, zoom: 0.94 },
  { t: 128.2, y: 8860, zoom: 1.0, curve: E.quintInOut },
  { t: 131.6, y: 8860, zoom: 1.0 },
  { t: 133.0, y: 8880, zoom: 1.02, curve: E.sineInOut },
  { t: 143.1, y: 8880, zoom: 1.02 },
];"""
s2 = re.sub(r"const KEYS = \[.*?\n\];", KEYS, s, count=1, flags=re.S)
assert s2 != s, "KEYS 未替换"

REPS = [
    ("""const handEnv = t => (1 - ssstep(NE(6) - 0.4, NC(6) + 0.3, t)) * ssstep(0.2, 1.2, t);""",
     """const HOLD_WIN = KEYS.slice(0, -1).map((k, i) => [k, KEYS[i + 1]])
  .filter(([a, b]) => Math.abs(a.y - b.y) < 0.5 && Math.abs(a.zoom - b.zoom) < 0.002 && b.t - a.t > 0.8)
  .map(([a, b]) => [a.t, b.t]);
const inHold = t => HOLD_WIN.some(([a, b]) => t > a + 0.05 && t < b - 0.05);
const handEnv = t => (inHold(t) ? 0 : 1) * (1 - ssstep(NE(6) - 0.4, NC(6) + 0.3, t)) * ssstep(0.2, 1.2, t);"""),
    ("const k = E.cubicOut(seg(t, NC(0) + 1.0, NC(0) + 4.2));", "const k = E.cubicOut(seg(t, 0.6, 3.4));"),
    ("label(P.x + P.w + 20, P.y + 240, NC(1) + 3.4, t, '预报 P50', '中位数曲线');",
     "label(P.x + P.w + 20, P.y + 240, NC(1) + 6.3, t, '预报 P50', '中位数曲线');"),
    ("label(P.x + P.w + 20, P.y + 340, NC(1) + 3.9, t, 'P10–P90', '80% 区间,不确定性');",
     "label(P.x + P.w + 20, P.y + 340, NC(1) + 6.5, t, 'P10–P90', '80% 区间,不确定性');"),
    ("label(P.x + P.w + 20, P.y + 440, NC(1) + 4.4, t, '近 48h 实况', '实测与预报在同一条轴上');",
     "label(P.x + P.w + 20, P.y + 440, NC(1) + 6.7, t, '近 48h 实况', '实测与预报在同一条轴上');"),
    ("const k = sstep(NE(2) - 6.4, NE(2) - 5.4, t);", "const k = sstep(NC(2) + 4.3, NC(2) + 5.1, t);"),
    ("label(L.risk2.x + 500, L.risk2.y - 36, NE(2) - 6.2, t, '同一份风险结论', null);",
     "label(L.risk2.x + 500, L.risk2.y - 36, NC(2) + 4.5, t, '同一份风险结论', null);"),
    ("const ringK = sstep(NC(3) + 1.0, NC(3) + 1.8, t);", "const ringK = sstep(NC(3) + 0.5, NC(3) + 1.2, t);"),
    ("ctx.beginPath(); ctx.arc(mx, my, 26 + 6 * Math.sin(t * 2.2), 0, Math.PI * 2);",
     "ctx.beginPath(); ctx.arc(mx, my, 26 + 6 * Math.sin(t * 2.2) * (1 - sstep(NC(3) + 1.3, NC(3) + 1.9, t)), 0, Math.PI * 2);"),
    ("const lk = sstep(NC(3) + 12.8, NC(3) + 13.6, t);", "const lk = sstep(NC(3) + 5.3, NC(3) + 6.0, t);"),
    ("label(L.panel.x - 470, L.panel.y + 268, NC(3) + 13.0, t, '该点现有栅格值', 'GDD 92.2 · 霜冻 1060 h/6 年 · 开采 4/3');",
     "label(L.panel.x - 470, L.panel.y + 268, NC(3) + 5.5, t, '该点现有栅格值', 'GDD 92.2 · 霜冻 1060 h/6 年 · 开采 4/3');"),
    ("const t0 = NC(4);\n  const A = [", "  const A = ["),
    ("t0 + 0.6, 'ERA5-Land 再分析'", "77.7, 'ERA5-Land 再分析'"),
    ("t0 + 1.0, 'NASADEM 30m'", "77.9, 'NASADEM 30m'"),
    ("t0 + 1.4, '全国茶园地图 10m'", "78.1, '全国茶园地图 10m'"),
    ("t0 + 4.6, '特征工程'", "81.7, '特征工程'"),
    ("t0 + 9.4, 'LightGBM 分位数回归'", "86.3, 'LightGBM 分位数回归'"),
    ("t0 + 15.6, '训练 1981–2020'", "91.1, '训练 1981–2020'"),
    ("t0 + 16.0, '验证 2021–2024'", "91.25, '验证 2021–2024'"),
    ("t0 + 16.4, '测试 2025–2026'", "91.4, '测试 2025–2026'"),
    ("t0 + 20.4, 'MAE 1.52 ℃'", "95.7, 'MAE 1.52 ℃'"),
    ("t0 + 20.8, '技巧 +41%'", "95.85, '技巧 +41%'"),
    ("t0 + 21.2, '74%'", "96.0, '74%'"),
    ("t0 + 21.6, '0.98 / 0.19'", "96.15, '0.98 / 0.19'"),
    ("arrow(960, 6772, 6832, t0 + 4.3, t); arrow(960, 6972, 7032, t0 + 9.1, t);",
     "arrow(960, 6772, 6832, 81.5, t); arrow(960, 6972, 7032, 86.1, t);"),
    ("arrow(960, 7182, 7212, t0 + 15.3, t); arrow(960, 7352, 7412, t0 + 20.1, t);",
     "arrow(960, 7182, 7212, 91.0, t); arrow(960, 7352, 7412, 95.5, t);"),
    ("label(L.sensor.x + L.sensor.w + 40, L.sensor.y + 150, NC(5) + 1.2, t, '传感器实测 + 天气站互补', '上传 CSV 即用实测值锚定');",
     "label(L.sensor.x + L.sensor.w + 40, L.sensor.y + 150, NC(5) + 0.4, t, '传感器实测 + 天气站互补', '上传 CSV 即用实测值锚定');"),
    ("label(L.phone.x0 - 30, L.phone.y - 60, NC(5) + 7.0, t, '微信小程序 · 同一套界面', '地形图底图 · 四个页面');",
     "label(L.phone.x0 - 30, L.phone.y - 60, NC(5) + 5.4, t, '微信小程序 · 同一套界面', '地形图底图 · 四个页面');"),
    ("const kk = E.cubicOut(clamp((t - (NC(6) + 1.2)) / 1.4));", "const kk = E.cubicOut(clamp((t - (NC(6) - 1.0)) / 1.5));"),
    ("  [['c2a', NC(1) + 3.2], ['c2b', NC(1) + 15.6], ['c3a', NC(2) + 0.4], ['c4a', NC(3) + 0.4],\n  ['c4b', NC(3) + 14.4], ['c6a', NC(5) + 0.6], ['c6b', NC(5) + 7.2]]",
     "  [['c2a', NC(1) + 6.2], ['c2b', NC(1) + 17.0], ['c3a', NC(2) + 0.4], ['c4a', NC(3) + 0.5],\n  ['c4b', NC(3) + 6.1], ['c6a', NC(5) + 0.5], ['c6b', NC(5) + 5.3]]"),
    ("    const kk = sstep(NC(3) + 13.6 + i * 0.16, NC(3) + 14.2 + i * 0.16, t);",
     "    const kk = sstep(NC(3) + 10.4 + i * 0.14, NC(3) + 11.0 + i * 0.14, t);"),
    ("  const w = OM.wordRise(t, NC(6) + 1.8 + i * 0.25, { dist: 18 });",
     "  const w = OM.wordRise(t, NC(6) - 0.6 + i * 0.25, { dist: 18 });"),
    ("""  const gk = 1 - ssstep(NC(6) - 1.4, NC(6) + 0.5, t);
  ['pSensor', 'pMap', 'pPanel'].forEach(id => { if (id !== 'pMap' && id !== 'pPanel') $(id).style.opacity = gk; });
  document.querySelectorAll('#world > img.plate').forEach(e => {
    if (['pMap', 'pPanel', 'pSensor'].includes(e.id)) return;
    if (e.id === 'pSensor') return;
    e.style.opacity = 1;
  });
  document.querySelectorAll('#world img').forEach(e => {
    if (e.src.includes('phone')) e.style.opacity = gk;
  });""",
     """  const gk = 1 - ssstep(NC(6) - 1.1, NC(6) + 0.7, t);
  const rise = -ssstep(NC(6) - 1.1, NC(6) + 0.7, t) * 150;
  { const sc = $('pSensor'); sc.style.opacity = gk; sc.style.transform = `translateY(${(rise * 0.7).toFixed(1)}px)`; }
  document.querySelectorAll('#world img').forEach(e => {
    if (!e.src.includes('phone')) return;
    e.style.opacity = gk;
    e.style.transform = `translateY(${rise.toFixed(1)}px)`;
  });"""),
]
miss = []
for a, b in REPS:
    if a in s2:
        s2 = s2.replace(a, b, 1)
    else:
        miss.append(a[:70])
p.write_text(s2, encoding="utf-8")
print("替换失败:", miss if miss else "无")
print("HOLD 段:", len(re.findall(r"curve: E\.sineInOut \}", s2)))
