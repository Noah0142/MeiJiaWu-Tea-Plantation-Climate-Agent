# -*- coding: utf-8 -*-
"""crop2.py — 从整页截图里裁出介绍片各章要用的真实画面块

用 capture2.py 记录的 boxes2.json(2x 坐标)裁切, 产出 assets/plates/*.png
"""
import json
import pathlib

from PIL import Image

HERE = pathlib.Path(__file__).parent
SH = HERE / "assets" / "shots"
PL = HERE / "assets" / "plates"
PL.mkdir(parents=True, exist_ok=True)
B = json.loads((HERE / "assets" / "boxes2.json").read_text(encoding="utf-8"))
full = Image.open(SH / "dash_dark_full.png")          # 3840 × 8502 (整页, 2x)
view = Image.open(SH / "dash_dark_chat.png")          # 3840 × 2160 (视口, 2x)
mapv = Image.open(SH / "map_result.png")              # 3840 × 2160 (视口, 2x)
print("full", full.size, "view", view.size, "map", mapv.size)


def clip(im, x, y, w, h, name, maxw=None):
    x, y, w, h = [int(v) for v in (x, y, w, h)]
    x0, y0 = max(0, x), max(0, y)
    im2 = im.crop((x0, y0, min(im.width, x + w), min(im.height, y + h)))
    if maxw and im2.width > maxw:
        im2 = im2.resize((maxw, round(im2.height * maxw / im2.width)), Image.LANCZOS)
    p = PL / f"{name}.png"
    im2.save(p)
    print(f"  {name:16} {im2.size} {p.stat().st_size // 1024} KB  (css {im2.width // 2}×{im2.height // 2})")


def rect(key, pad=0):
    """boxes2.json 存的是 CSS 坐标(视口 2x 截图), 裁切要 ×2"""
    r = B[key]
    return (r["x"] - pad) * 2, (r["y"] - pad) * 2, (r["w"] + 2 * pad) * 2, (r["h"] + 2 * pad) * 2


# 大盘顶部(视口)
clip(view, 0, 0, 3840, 2160, "dash_top")
# 预报曲线卡(含标题与图例): 从整页里取曲线元素上下各留白
clip(full, *rect("chart", 90), name="card_chart")
# 风险 + AI 建议 两张卡
clip(full, 220, *[0,0,0,0], name="x") if False else None
clip(full, *rect("riskbox", 60), name="card_risk")
clip(full, *rect("advice", 60), name="card_advice")
# 传感器实测卡(历史实况曲线第一张小图, 带标题)
clip(full, B["sensors"]["x"] - 60, B["sensors"]["y"] - 330, 2 * 900, B["sensors"]["h"] + 420, "card_sensor")
# 农事对话卡(视口截图里的)
clip(view, *rect("chatcard", 46), name="card_chat")
# 地图页: 地图(左) 与 右侧面板
clip(mapv, 0, 0, 3030, 2160, "map_full", maxw=3030)
clip(mapv, 3000, 0, 840, 2160, "map_panel")
# 专题图层缩略(后端真实产物)
for f in ["terrain", "gdd", "frost6y", "dtr", "pluck", "frost72h"]:
    src = HERE / "assets" / f"ov_{f}.png"
    if src.exists():
        im = Image.open(src)
        im.thumbnail((900, 900), Image.LANCZOS)
        p = PL / f"ov_{f}.png"
        im.save(p)
        print(f"  ov_{f:14} {im.size} {p.stat().st_size // 1024} KB")
