# -*- coding: utf-8 -*-
"""make_cjk_css.py — 生成 cjk.css: 中文字体(Noto Serif SC / Noto Sans SC, SIL OFL 1.1)子集

做法: 扫描 comp.html 用到的全部非 ASCII 字符, 走 Google Fonts CSS API 的 text= 参数取子集,
base64 内联进 cjk.css —— 改文案后重跑本脚本即可(与 look.py apply 同一个道理)。
用法: python make_cjk_css.py
"""
import base64
import pathlib
import re
import urllib.parse
import urllib.request

HERE = pathlib.Path(__file__).parent
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
EXTRA = "0123456789℃%·–—+,.:;()（）、。「」"
SERIF_TEXT = "梅家坞茶园微气候智能体"          # 落版衬线用的字


def comp_chars():
    txt = (HERE / "comp.html").read_text(encoding="utf-8")
    chars = {c for c in txt if ord(c) > 0x7E}
    return "".join(sorted(chars)), "".join(sorted(set(chars) | set(EXTRA)))


def fetch(family, text):
    url = ("https://fonts.googleapis.com/css2?family=" + family.replace(" ", "+") +
           ":wght@400;600&text=" + urllib.parse.quote(text) + "&display=block")
    css = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60).read().decode()
    urls = re.findall(r"url\((https://[^)]+)\)\s*format\('(\w+)'\)", css)
    if not urls:
        raise SystemExit("no font url in CSS:\n" + css[:400])
    return urls[-1][0]          # 最后一个 = 最大权重


def face(fam, weight, data, fmt):
    return (f"@font-face{{font-family:'{fam}';font-style:normal;font-weight:{weight};font-display:block;"
            f"src:url(data:font/{fmt};base64,{base64.b64encode(data).decode()}) format('{fmt}');}}\n")


def main():
    cjk_all, sans_text = comp_chars()
    print("comp 用到的非 ASCII 字符 %d 个" % len(cjk_all))
    out = ["/* 中文字体: Noto Serif SC / Noto Sans SC (SIL OFL 1.1, Google Fonts) 子集, 仅含本片用到的字 */\n"]
    for fam, text, weight in [("Noto Serif SC", SERIF_TEXT, "100 900"), ("Noto Sans SC", sans_text, "100 900")]:
        u = fetch(fam, text)
        data = urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=180).read()
        fmt = "woff2" if data[:4] == b"wOF2" else "truetype"
        out.append(face("SerifSC" if "Serif" in fam else "SansSC", weight, data, fmt))
        print("  %-14s %5d 字符 → %6.1f KB (%s)" % (fam, len(text), len(data) / 1024, fmt))
    (HERE / "cjk.css").write_text("".join(out), encoding="utf-8")
    print("cjk.css:", (HERE / "cjk.css").stat().st_size // 1024, "KB")


if __name__ == "__main__":
    main()
