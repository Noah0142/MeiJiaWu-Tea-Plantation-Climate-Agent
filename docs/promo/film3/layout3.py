# -*- coding: utf-8 -*-
"""layout3.py — 把 comp3.html 的版面与词语定位改成"图不重叠"的显式分区:
图片带 y 140–860 / 词语带 y 900 / 导轨 y 1000 / 章名带 y 40–120。"""
import pathlib
import re

p = pathlib.Path(__file__).parent / "comp3.html"
s = p.read_text(encoding="utf-8")

NEW_L = """const L = {
  dash: { x: 40, y: 150, w: 1840, h: 700 },          // 大盘顶部: 只取上 65%, 不与词语带重叠
  chart: { x: 300, y: 132, w: 1270, h: 677 },
  risk: { x: 200, y: 200, w: 740, h: 411 },
  advice: { x: 980, y: 200, w: 740, h: 255 },
  chat: { x: 110, y: 250, w: 1200, h: 316 },
  risk2: { x: 1360, y: 260, w: 440, h: 245 },
  map: { x: 60, y: 145, w: 980, h: 720 },
  panel: { x: 1290, y: 145, w: 280, h: 693 },
  row: { y: 420, x0: 205, w: 200, gap: 60 },
  sensor: { x: 130, y: 200, w: 900, h: 642 },
  phoneA: { x: 1180, y: 200, w: 290, h: 585 },
  phoneB: { x: 1520, y: 250, w: 290, h: 585 },
};"""
s2 = re.sub(r"const L = \{.*?\n\};", NEW_L, s, count=1, flags=re.S)
assert s2 != s
s = s2
# 大盘整页改为"上半页"视图(1840×700 的裁切: 用 object-fit 覆盖)
s = s.replace(".plate{position:absolute;left:0;top:0;display:block;border-radius:14px;background:#fff;z-index:3;will-change:transform,opacity;",
              ".plate{position:absolute;left:0;top:0;display:block;border-radius:14px;background:#fff;z-index:3;object-fit:cover;object-position:50% 0;will-change:transform,opacity;")
# 词语带固定 y=900, 第二段用测量宽度排位
old_words = re.search(r"  // 词语\(同一位置依次顶出\)\n.*?\n  \}\);", s, re.S).group(0)
new_words = """  // 词语(底部词语带 y=900, 依次顶出; 段内两部分并排不重叠)
  WORDS.forEach((w0) => {
    const out = w0.out == null ? 0 : ssstep(w0.out, w0.out + 0.24, t);
    w0.els.forEach((s2, j) => {
      const w = OM.wordRise(t, w0.t + j * 0.22, { dist: 22 });
      const x = 250 + (j ? (w0.w0 + 26) : 0);
      s2.style.left = '0px'; s2.style.top = '0px'; s2.style.transformOrigin = '0 0';
      s2.style.opacity = w.op * (1 - out);
      s2.style.transform = `translate(${x}px,${(900 + w.y).toFixed(1)}px) scale(${w.s.toFixed(4)})`;
    });
  });"""
s = s.replace(old_words, new_words, 1)
# 测量第一段宽度(buildDom 里, 字体已就位)
s = s.replace("""  const w = $('words');
  WORDS.forEach((w0, i) => {
    w0.els = w0.parts.map((txt, j) => {
      const s = document.createElement('span');
      s.textContent = txt; s.className = j ? 'mut' : '';
      s.style.left = (250 + j * 0) + 'px';
      w.appendChild(s); return s;
    });
  });""",
"""  const w = $('words');
  WORDS.forEach((w0) => {
    w0.els = w0.parts.map((txt, j) => {
      const sp = document.createElement('span');
      sp.textContent = txt; sp.className = j ? 'mut' : '';
      w.appendChild(sp); return sp;
    });
    w0.w0 = Math.ceil(w0.els[0].getBoundingClientRect().width);
  });""")
# 词语时间: 大盘/地图这类整页画面期间不出词语(避免压在图上看不清)
s = s.replace("  { t: 13.00, parts: ['实时大盘', '气温湿度 · 72h 区间 · 风险分级'], out: T.s2_dashOut },",
              "  { t: 17.40, parts: ['实时大盘', '72h 逐小时 · P10–P90 区间'], out: T.s2_chartOut },")
s = s.replace("  { t: 23.10, parts: ['霜冻与高温', '按等级给结论'], out: T.s2_riskOut },",
              "  { t: 23.30, parts: ['霜冻与高温', '按等级给结论'], out: T.s2_riskOut },")
s = s.replace("  { t: 40.00, parts: ['地形图选点', '点任意位置, 模型现场算'], out: T.s4_mapOut },",
              "  { t: 39.80, parts: ['地形图选点', '点任意位置, 30m 地形现场算'], out: T.s4_mapOut },")
s = s.replace("  { t: 47.60, parts: ['六张专题图层', '叠加对比'], out: T.s4_rowOut },",
              "  { t: 47.80, parts: ['六张专题图层', '积温 · 霜冻 · 温差 · 开采期'], out: T.s4_rowOut },")
s = s.replace("  { t: 57.00, parts: ['模型怎么练的', '真实数据 · 严格切分'], out: T.s5_hold },",
              "  { t: 57.00, parts: ['模型怎么练的', '真实数据 · 严格切分'], out: T.s5_d },")
s = s.replace("  { t: 66.80, parts: ['在没见过的年份上', '只测一次'], out: T.s5_hold },",
              "  { t: 67.20, parts: ['在没见过的年份上', '只测一次'], out: T.s6_sensorIn },")
s = s.replace("  { t: 75.00, parts: ['传感器与手机', '实测锚定 · 小程序同源'], out: T.s6_out },",
              "  { t: 75.00, parts: ['传感器与手机', '实测锚定 · 小程序同源'], out: T.s6_out },")
# S5 图解行位压进 y160–860 的图片带
NEWA = """  const A = [
    [140, 160, 520, 100, T.s5_a, 'ERA5-Land 再分析', '1950–2026 · 672,840 小时'],
    [700, 160, 420, 100, T.s5_a + 0.18, 'NASADEM 30m', '坡度 · 坡向 · TPI'],
    [1160, 160, 620, 100, T.s5_a + 0.36, '全国茶园地图 10m', '2022 · 茶园分布特征'],
    [140, 300, 1640, 100, T.s5_b, '特征工程', '时间谐波 · 历史滞后 · 邻站 · 地形 · 预报时效 horizon'],
    [140, 440, 1640, 110, T.s5_c, 'LightGBM 分位数回归', 'P10 · P50 · P90 · 相对湿度 → 未来 72 小时逐小时', 'a'],
    [140, 590, 520, 100, T.s5_d, '训练 1981–2020', '拟合权重'],
    [700, 590, 420, 100, T.s5_d + 0.18, '验证 2021–2024', '早停 · 诊断'],
    [1160, 590, 620, 100, T.s5_d + 0.36, '测试 2025–2026', '只评估一次'],
    [140, 740, 380, 120, T.s5_e, 'MAE 1.52 ℃', '测试集 · 持续性 2.69', 'a'],
    [560, 740, 380, 120, T.s5_e + 0.16, '技巧 +41%', '相对持续性预报', 'a'],
    [980, 740, 380, 120, T.s5_e + 0.32, '74%', '24h 最低温 ±2℃ 以内', 'a'],
    [1400, 740, 380, 120, T.s5_e + 0.48, '0.98 / 0.19', '霜冻预警 POD / FAR', 'a'],
  ];
  for (const [x, y, w, h, tt, ti, su, tone] of A) box(x, y, w, h, tt, t, ti, su, tone);
  arrow(960, 262, 296, T.s5_b - 0.25, t); arrow(960, 402, 436, T.s5_c - 0.25, t);
  arrow(960, 552, 586, T.s5_d - 0.25, t); arrow(960, 692, 736, T.s5_e - 0.25, t);"""
s = re.sub(r"  const A = \[.*?arrow\(960, 650, 675.*?\n", NEWA + "\n", s, count=1, flags=re.S)
p.write_text(s, encoding="utf-8")
print("版面无重叠重排完成")
