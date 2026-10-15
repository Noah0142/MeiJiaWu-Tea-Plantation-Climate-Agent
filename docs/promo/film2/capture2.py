# -*- coding: utf-8 -*-
"""capture2.py — 为 2 分钟介绍片抓网页版「深色」真实素材

产出 docs/promo/film2/assets/shots/*.png 与 boxes2.json
用法: python docs/promo/film2/capture2.py   (需后端在 127.0.0.1:8000)
"""
import json
import pathlib
import shutil

from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parents[3]
OUT = ROOT / "docs" / "promo" / "film2" / "assets"
SHOTS = OUT / "shots"
SHOTS.mkdir(parents=True, exist_ok=True)
BASE = "http://127.0.0.1:8000"
DSF = 2
PT = {"lat": 30.215, "lon": 120.095, "name": "梅家坞北坡"}

boxes = {}


def clip_shot(pg, sel_or_js, name, pad=0):
    """按 JS 取的 rect 裁剪截图(2x)"""
    r = sel_or_js if isinstance(sel_or_js, dict) else pg.evaluate(sel_or_js)
    if not r:
        print("  skip", name); return
    p = SHOTS / f"{name}.png"
    pg.screenshot(path=str(p), clip={"x": max(0, r["x"] - pad), "y": max(0, r["y"] + pg.evaluate("() => window.scrollY") - pad),
                                     "width": r["w"] + 2 * pad, "height": r["h"] + 2 * pad}, full_page=True)
    print(f"  shot {name}: {p.stat().st_size // 1024} KB")


def rect_of(sel):
    return f"""() => {{ const e = document.querySelector('{sel}'); if (!e) return null;
        const b = e.getBoundingClientRect(); return {{x: b.x, y: b.y, w: b.width, h: b.height}}; }}"""


def main():
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        pg = b.new_page(viewport={"width": 1920, "height": 1080}, device_scale_factor=DSF)
        pg.goto(BASE)
        pg.evaluate("() => localStorage.setItem('theme','dark')")

        # ── 1. 大盘(深色) ────────────────────────────────────────────────
        pg.goto(BASE, wait_until="networkidle", timeout=60000)
        pg.wait_for_timeout(4500)
        pg.screenshot(path=str(SHOTS / "dash_dark.png"))
        pg.screenshot(path=str(SHOTS / "dash_dark_full.png"), full_page=True)
        print("  shot dash_dark(+full)")
        for key, sel in [("chart", "#chart"), ("riskbox", "#risk-panel"), ("advice", "#agent-summary"),
                         ("chatcard", "#chat-box"), ("sensors", "#sensor-temp"), ("apicard", "#api-chart")]:
            boxes[key] = pg.evaluate(rect_of(sel))
        boxes["sections"] = pg.evaluate("""() => [...document.querySelectorAll('article.panel')].map((s,i) => {
            const r = s.getBoundingClientRect(); const h = s.querySelector('h3,h2');
            return {i, x: r.x*2, y: r.y*2, w: r.width*2, h: r.height*2, title: (h?h.textContent:'').trim().slice(0,20)}; })""")

        # ── 2. 农事对话: 问霜冻, 等真实回复 ─────────────────────────────
        pg.locator("#quick-chips .chip", has_text="霜冻").first.click(timeout=8000)
        for _ in range(40):                       # 轮询等真实回复(最多 120s)
            pg.wait_for_timeout(3000)
            t = pg.evaluate("() => (document.querySelector('#chat-box')||{}).innerText || ''")
            n = pg.evaluate("() => document.querySelectorAll('#chat-box .chat-msg.agent').length")
            if n >= 2 and '思考中' not in t:
                break
        pg.wait_for_timeout(1000)
        boxes["chat_reply_frost"] = pg.evaluate("""() => { const a=[...document.querySelectorAll('#chat-box .chat-msg.agent')];
            return a.length ? a[a.length-1].innerText : ''; }""")
        print("  frost reply:", boxes["chat_reply_frost"][:90].replace("\n", " "))
        pg.screenshot(path=str(SHOTS / "dash_dark_chat.png"))
        clip_shot(pg, rect_of("#chat-box"), "card_chat_dark", pad=14)

        # ── 3. 地图选点(深色): 选点 → 查询 → 运行微气候模型 ───────────
        pg.goto(BASE + "/map.html", wait_until="networkidle", timeout=60000)
        pg.wait_for_timeout(2500)
        pg.evaluate(f"() => {{ map.setView([{PT['lat']}, {PT['lon']}], 15); queryPoint({PT['lat']}, {PT['lon']}); }}")
        pg.wait_for_timeout(2500)
        pg.screenshot(path=str(SHOTS / "map_point.png"))
        clip_shot(pg, rect_of("#point-box"), "card_point", pad=10)
        pg.click("#btn-run")
        pg.wait_for_selector("#sec-result:not([hidden])", timeout=180000)
        pg.wait_for_timeout(2500)
        pg.screenshot(path=str(SHOTS / "map_result.png"))
        clip_shot(pg, rect_of("#result-box"), "card_result", pad=10)
        boxes["map_result"] = pg.evaluate("""() => { const o = {};
            const q = s => { const e = document.querySelector(s); if(!e) return null; const r = e.getBoundingClientRect();
                return {x: r.x*2, y: r.y*2, w: r.width*2, h: r.height*2}; };
            o.win = {w: innerWidth*2, h: innerHeight*2};
            o.chart = q('#chart-72h'); o.ov = q('#ov-picker'); o.result = q('#result-box'); o.panel = q('#panel');
            o.ovUrls = [...document.querySelectorAll('#ov-picker .ov-chip')].map(c => c.dataset.ov);
            return o; }""")
        boxes["map_text"] = pg.evaluate("""() => ({ cards: [...document.querySelectorAll('#result-box .card')].map(c => c.innerText.replace(/\\n/g,' ')),
            frost: (document.querySelector('.badge')||{}).innerText || '', win: (document.querySelector('#win-size')||{}).innerText || '' })""")
        print("  map result:", json.dumps(boxes["map_text"], ensure_ascii=False)[:260])

        # 叠加层 PNG(霜冻 / GDD / 地形)直接取后端产物
        key = f"{PT['lat']:.5f}_{PT['lon']:.5f}"
        src = ROOT / "data" / "sites" / key
        if src.exists():
            for f in ["frost72h.png", "gdd.png", "terrain.png"]:
                if (src / f).exists():
                    shutil.copy(src / f, OUT / f"ov_{f}")
            print("  overlays copied:", [p.name for p in src.glob("*.png")][:6])

        (OUT / "boxes2.json").write_text(json.dumps(boxes, ensure_ascii=False, indent=1), encoding="utf-8")
        print("boxes2.json ok:", list(boxes))
        b.close()

    # ── 4. 小程序高保真原型(深色) ────────────────────────────────────
    proto = ROOT / "docs" / "miniapp" / "prototype" / "index.html"
    if proto.exists():
        with sync_playwright() as pw:
            b = pw.chromium.launch()
            pg = b.new_page(viewport={"width": 1920, "height": 1200}, device_scale_factor=2, color_scheme="dark")
            pg.goto(proto.as_uri(), wait_until="load")
            pg.wait_for_timeout(2000)
            pg.screenshot(path=str(SHOTS / "miniapp_proto.png"), full_page=True)
            print("  miniapp prototype shot")
            b.close()


if __name__ == "__main__":
    main()
