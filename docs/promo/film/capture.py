# -*- coding: utf-8 -*-
"""capture.py — 抓取茶园智能体网页版真实素材(截图 + 元素坐标 + 真实问答)

用法: python docs/promo/film/capture.py   (需后端已启动在 127.0.0.1:8000)
产出: docs/promo/film/assets/shots/*.png 与 boxes.json
"""
import json
import pathlib
import sys

from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parents[3]
OUT = ROOT / "docs" / "promo" / "film" / "assets"
SHOTS = OUT / "shots"
SHOTS.mkdir(parents=True, exist_ok=True)
BASE = "http://127.0.0.1:8000/"
DSF = 2

boxes = {}


def box(page, sel, key):
    try:
        loc = page.locator(sel).first
        bb = loc.bounding_box(timeout=5000)
        if bb:
            boxes[key] = {k: round(v * DSF) for k, v in bb.items()}
    except Exception as e:  # noqa: BLE001
        print(f"  box miss {key}: {e}")


def shot(page, sel, name):
    """元素截图(2x): sel 为空整屏; 否则取该元素所在 article 卡片的裁剪区"""
    p = SHOTS / f"{name}.png"
    if sel:
        r = page.evaluate(
            """(sel) => { const el = document.querySelector(sel); const a = el.closest('article') || el;
                 const b = a.getBoundingClientRect();
                 return { x: b.x, y: b.y + window.scrollY, w: b.width, h: b.height }; }""", sel)
        page.screenshot(path=str(p), clip={"x": r["x"], "y": r["y"], "width": r["w"], "height": r["h"]},
                        full_page=True, timeout=20000)
    else:
        page.screenshot(path=str(p))
    print(f"  shot {name}: {p.stat().st_size // 1024} KB")


def main():
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        pg = b.new_page(viewport={"width": 1920, "height": 1080}, device_scale_factor=DSF)
        pg.goto(BASE, wait_until="networkidle", timeout=60000)
        pg.wait_for_timeout(4500)              # ECharts 动画结束
        pg.evaluate("() => window.scrollTo(0, 0)")
        pg.wait_for_timeout(400)

        shot(pg, None, "dash_light")
        pg.screenshot(path=str(SHOTS / "dash_full.png"), full_page=True)   # 整页(窗口内滚动用)
        print("  shot dash_full")
        boxes["chips"] = pg.evaluate("""() => [...document.querySelectorAll('#quick-chips .chip')].map(c => {
            const r = c.getBoundingClientRect();
            return {text: c.textContent.trim(), x: r.x*2, y: r.y*2, w: r.width*2, h: r.height*2}; })""")
        for sel, key in [
            ("header", "header"),
            ("#chat-box", "chatbox"),
            ("#chat-form", "chatform"),
            ("#quick-chips", "quickchips"),
            ("#chart", "chart"),
            ("#risk-panel", "riskpanel"),
            ("#agent-summary", "agentsummary"),
            ("#api-chart", "apichart"),
        ]:
            box(pg, sel, key)
        for sel, name in [
            ("#chart", "card_chart"),
            ("#risk-panel", "card_risk"),
            ("#agent-summary", "card_advice"),
        ]:
            shot(pg, sel, name)

        # 整块卡片容器: 依次取每个 section 的位置, 便于合成时引用
        secs = pg.evaluate("""() => [...document.querySelectorAll('section.card, section')].map((s,i) => {
            const r = s.getBoundingClientRect();
            const t = (s.querySelector('h2,h3')||{}).textContent || '';
            return {i, x: r.x, y: r.y, w: r.width, h: r.height, title: t.trim().slice(0,24)};
        })""")
        boxes["sections"] = secs

        # 真实问答: 点"什么时候采摘?", 等助手回复
        q = None
        try:
            pg.locator("#quick-chips .chip", has_text="采摘").first.click(timeout=8000)
            q = "什么时候可以采摘?"
            print("  asked:", q)
            # 等真正的回复(排除"思考中…"占位气泡)
            pg.wait_for_function(
                """() => { const a=[...document.querySelectorAll('#chat-box .chat-msg.agent')];
                    if (a.length < 2) return false;
                    const t = a[a.length-1].innerText || '';
                    return t.length > 40 && !t.includes('思考中'); }""",
                timeout=120000)
            pg.wait_for_timeout(1500)
            reply = pg.evaluate("""() => {
                const a=[...document.querySelectorAll('#chat-box .chat-msg.agent')];
                return a.length? a[a.length-1].innerText : '';
            }""")
            boxes["chat_reply"] = reply
            print("  reply:", reply[:120].replace("\n", " "), "...")
            shot(pg, None, "dash_after_chat")
            pg.screenshot(path=str(SHOTS / "dash_full_after.png"), full_page=True)
            shot(pg, "#chat-box", "card_chat")
            box(pg, "#chat-box", "chatbox_after")
        except Exception as e:  # noqa: BLE001
            print("  chat capture failed:", e)
        boxes["question"] = q

        # 模板词条(左上角说明/标题)位置
        boxes["title"] = pg.evaluate("""() => {
            const h=[...document.querySelectorAll('header h1, header .brand, h1')][0];
            if(!h) return null; const r=h.getBoundingClientRect();
            return {x:r.x*2, y:r.y*2, w:r.width*2, h:r.height*2, text:h.textContent.trim().slice(0,30)};
        }""")

        (OUT / "boxes.json").write_text(json.dumps(boxes, ensure_ascii=False, indent=1), encoding="utf-8")
        print("boxes.json written:", list(boxes))
        b.close()


if __name__ == "__main__":
    sys.exit(main())
