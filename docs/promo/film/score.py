# -*- coding: utf-8 -*-
"""score.py — 梅家坞茶园微气候智能体 17.4s 的声音(五件材料一副房间, 事件少于节拍)

按 templates/sfx_score.example.py 的写法: 每个节拍一次触碰, 静止段留白; 平移跟随画面中的位置。
依赖 onetake 的 scripts/sfx_palette.py (环境变量 ONETAKE_DIR, 默认下面的路径)。
用法: python score.py   → sfx.wav (48 kHz, 峰值 -8 dBFS)
"""
import os
import pathlib
import sys

ONETAKE = os.environ.get("ONETAKE_DIR", r"C:\Users\Noah1\AppData\Local\Temp\onetake")
sys.path.insert(0, str(pathlib.Path(ONETAKE) / "scripts"))
import numpy as np                                    # noqa: E402
from sfx_palette import Score, air, glass, wood, sub, bubble, wobble, pan_of   # noqa: E402

DUR = 17.4
rng = np.random.default_rng(17)
s = Score(dur=DUR, T60=0.95)
place = s.place

# 1 · 开场: 房间打开 + 笔尖落纸, 一次划过纸面的气流跟着笔尖走
place(sub(52, 0.9), 0.06, 0.20)
place(wood(150, 0.07), 0.42, 0.30, -0.5, 0.2)
place(air(0.95, 700, 2600, 0.75), 0.46, 0.30, -0.55, 0.45, pan_to=0.55)
place(bubble(520, 0.20), 1.42, 0.26, 0.5, 0.3)
# 2 · 剖面上抬成气温曲线, 坐标轴落位
place(air(0.55, 240, 1500, 0.7), 1.62, 0.34, 0.0, 0.5)
place(sub(64, 0.5), 1.74, 0.22)
place(glass(784, 0.9, 0.6), 2.40, 0.16, -0.2, 0.45)
place(glass(1046, 0.9, 0.5), 2.46, 0.12, -0.15, 0.5)
# 3 · 区间从线上长出来(一次呼吸), 长完一声玻璃, 然后静止 1.4 s
place(air(0.6, 300, 2200, 0.8), 2.82, 0.34, -0.3, 0.5, pan_to=0.6)
place(glass(1174, 1.1, 0.45), 4.02, 0.14, 0.3, 0.6)
# 4 · 受冻临界线射入 / 落地 / 风险胶囊
place(air(0.24, 2600, 380, 1.0), 5.52, 0.42, 0.7, 0.35, pan_to=-0.8)
place(sub(66, 0.55), 5.72, 0.46)
place(wood(240, 0.08), 5.73, 0.30, -0.2, 0.2)
place(wood(190, 0.07), 5.79, 0.20, -0.2, 0.2)
place(glass(1318, 0.8, 0.5), 5.95, 0.15, 0.25, 0.5)
place(bubble(420, 0.22), 6.00, 0.24, 0.3, 0.3)
# 5 · 胶囊张开成浏览器窗口(一次吸气 + 底音)
place(air(0.68, 220, 1900, 0.85), 7.05, 0.42, 0.0, 0.6)
place(sub(58, 0.7), 7.18, 0.24)
# 6 · 指针到位、点击, 回答出现
place(air(0.30, 900, 400, 0.7), 8.66, 0.16, 0.2, 0.4)
place(wood(200, 0.08), 9.08, 0.30, pan_of(700), 0.2)
place(wood(160, 0.06), 9.15, 0.22, pan_of(700), 0.2)
place(bubble(600, 0.22), 9.45, 0.24, 0.1, 0.35)
place(glass(990, 0.9, 0.45), 9.52, 0.15, 0.05, 0.55)
# 7 · 下滚到真实预报图
place(air(0.55, 180, 1700, 0.75), 11.55, 0.34, 0.0, 0.5)
place(glass(660, 1.0, 0.6), 12.40, 0.14, 0.0, 0.6)
place(sub(70, 0.45), 12.50, 0.22)
# 8 · 窗口收成卡片、地图卡片进来、线上地形
place(air(0.5, 1500, 380, 0.75), 13.42, 0.30, 0.3, 0.45, pan_to=-0.3)
place(bubble(480, 0.24), 13.88, 0.26, 0.35, 0.3)
place(glass(587, 0.85, 0.55), 14.48, 0.15, 0.4, 0.5)
# 9 · 折向落版: 线落下去, 字一排排落下(每两字一声轻木), 最后一个和弦
place(air(0.78, 170, 1300, 0.9), 15.26, 0.42, 0.0, 0.55)
place(sub(54, 0.9), 15.32, 0.30)
for i in range(0, 11, 2):
    place(wood(300 + rng.uniform(-24, 24), 0.055), 15.82 + i * 0.055,
          0.085 * rng.uniform(0.8, 1.2), -0.15, 0.25)
place(glass(392, 1.8, 0.35), 16.36, 0.13, 0.0, 0.7)
place(sub(44, 1.4), 16.40, 0.34)

s.write(os.path.join(os.path.dirname(os.path.abspath(__file__)), "sfx.wav"))
