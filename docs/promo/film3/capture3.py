# -*- coding: utf-8 -*-
"""capture3.py — 浅色版(第一部风格)素材: 地图选点页(浅色)、小程序三屏(浅色)、传感器卡

产出 docs/promo/film3/assets/shots/*.png 与 boxes3.json
"""
import json
import pathlib
import shutil

from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parents[3]
OUT = ROOT / "docs" / "promo" / "film3" / "assets"
SHOTS = OUT / "shots"
SHOTS.mkdir(parents=True, exist_ok=True)
BASE = "http://127.0.0.1:8000"
DSF = 2
PT = {"lat": 30.215, "lon": 120.095}

boxes = {}


def clip_shot(pg, rect, name, pad=0):
    r = rect if isinstance(rect, dict) else pg.evaluate(rect)
    if not r:
        print("  skip", name); return
    p = SHOTS / f"{name}.png"
    pg.screenshot(path=str(p), clip={"x": max(0, r["x"] - pad), "y": max(0, r["y"] + pg.evaluate("() => window.scrollY") - pad),
                                     "width": r["w"] + 2 * pad, "height": r["h"] + 2 * pad}, full_page=True)
    print(f"  shot {name}: {p.stat().st_size // 1024} KB")


def main():
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        pg = b.new_page(viewport={"width": 1920, "height": 1080}, device_scale_factor=DSF)
        pg.goto(BASE)
        pg.evaluate("() => localStorage.setItem('theme','light')")

        # 大盘(浅色整页) — 传感器卡从这里裁
        pg.goto(BASE, wait_until="networkidle", timeout=60000)
        pg.wait_for_timeout(4500)
        pg.screenshot(path=str(SHOTS / "dash_light_full.png"), full_page=True)
        boxes["apichart"] = pg.evaluate("""() => { const e=document.querySelector('#api-chart'); const r=e.getBoundingClientRect();
            return {x:r.x,y:r.y,w:r.width,h:r.height}; }""")
        boxes["sensors"] = pg.evaluate("""() => { const e=document.querySelector('#sensor-temp'); const r=e.getBoundingClientRect();
            return {x:r.x,y:r.y,w:r.width,h:r.height}; }""")
        boxes["chart"] = pg.evaluate("""() => { const e=document.querySelector('#chart'); const r=e.getBoundingClientRect();
            return {x:r.x,y:r.y,w:r.width,h:r.height}; }""")
        print("  shot dash_light_full")

        # 地图选点(浅色): 选点 → 运行模型
        pg.goto(BASE + "/map.html", wait_until="networkidle", timeout=60000)
        pg.wait_for_timeout(2500)
        pg.evaluate(f"() => {{ map.setView([{PT['lat']}, {PT['lon']}], 15); queryPoint({PT['lat']}, {PT['lon']}); }}")
        pg.wait_for_timeout(2500)
        pg.click("#btn-run")
        pg.wait_for_selector("#sec-result:not([hidden])", timeout=180000)
        pg.wait_for_timeout(2500)
        pg.screenshot(path=str(SHOTS / "map_light.png"))                 # 视口
        pg.screenshot(path=str(SHOTS / "map_light_full.png"), full_page=True)
        boxes["map"] = pg.evaluate("""() => { const r = document.querySelector('#map').getBoundingClientRect();
            return {x:r.x, y:r.y, w:r.width, h:r.height}; }""")
        boxes["panel"] = pg.evaluate("""() => { const r = document.querySelector('#panel').getBoundingClientRect();
            return {x:r.x, y:r.y, w:r.width, h:r.height}; }""")
        boxes["pointbox"] = pg.evaluate("""() => { const r = document.querySelector('#point-box').getBoundingClientRect();
            return {x:r.x, y:r.y, w:r.width, h:r.height}; }""")
        boxes["resultbox"] = pg.evaluate("""() => { const r = document.querySelector('#result-box').getBoundingClientRect();
            return {x:r.x, y:r.y, w:r.width, h:r.height}; }""")
        boxes["ovpicker"] = pg.evaluate("""() => { const r = document.querySelector('#ov-picker').getBoundingClientRect();
            return {x:r.x, y:r.y, w:r.width, h:r.height}; }""")
        print("  shot map_light(+full)")
        key = f"{PT['lat']:.5f}_{PT['lon']:.5f}"
        for f in ["terrain.png", "gdd.png", "frost6y.png", "dtr.png", "pluck.png", "frost72h.png"]:
            src = ROOT / "data" / "sites" / key / f
            if src.exists():
                shutil.copy(src, OUT / f"ov_{f}")
        print("  overlays copied")

        (OUT / "boxes3.json").write_text(json.dumps(boxes, ensure_ascii=False, indent=1), encoding="utf-8")
        b.close()

    # 小程序三屏(浅色): 原型默认深色, 这里改回浅色
    proto = ROOT / "docs" / "miniapp" / "prototype" / "index.html"
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        pg = b.new_page(viewport={"width": 1920, "height": 1200}, device_scale_factor=2, color_scheme="light")
        pg.goto(proto.as_uri(), wait_until="load")
        pg.evaluate("() => document.documentElement.setAttribute('data-theme','light')")
        pg.wait_for_timeout(1800)
        pg.screenshot(path=str(SHOTS / "miniapp_light.png"), full_page=True)
        print("  shot miniapp_light")
        b.close()


if __name__ == "__main__":
    main()
