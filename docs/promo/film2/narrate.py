# -*- coding: utf-8 -*-
"""narrate.py — 2 分钟介绍片的旁白: 分句合成 → 测量时长 → 生成时间轴

做法: 每一句一个 wav(Windows SAPI, Microsoft Huihui zh-CN), 逐句测量时长,
按「句间 0.30s / 章间 1.30s」拼出整片时间轴, 写 assets/narration.js 供 comp.html 用
(字幕与章节边界全部由这份真实时长驱动)。 输出: assets/nar/*.wav 与 narration.js
"""
import json
import pathlib
import subprocess
import wave

HERE = pathlib.Path(__file__).parent
NA = HERE / "assets" / "narr"
NA.mkdir(parents=True, exist_ok=True)
FFMPEG = r"C:\Hackthon\AI4Climate\.tools\ffmpeg.exe"
VOICE = "Microsoft Huihui Desktop"
RATE = 4                      # -10..10, 1 ≈ 稍快但清楚
SENT_GAP, CH_GAP = 0.35, 1.50

# 章节 → 句子(字幕逐句显示; 章节边界由真实时长决定)
CH = [
    ("片头", ["杭州西湖梅家坞,茶园长在山地上——同一座山,阳坡和谷底的气候完全不同。",
             "我们把这个模型,做成了茶农手里的智能体。"]),
    ("实时大盘", ["先看大盘:实时气温、湿度和未来 24 小时最低温度。",
                "未来 72 小时逐小时的预报,不是一个数——P10 到 P90 的区间,不确定性直接画出来。",
                "下面是霜冻和高温风险,按等级给出结论。"]),
    ("农事对话", ["不懂就直接问,助手读的是同一份预报和风险结论。",
                "问会不会有霜冻,回答里的气温来自上面那条曲线。"]),
    ("地形图选点", ["茶园不在一个点上。地图上点任意位置,哪怕没有监测站:",
                  "海拔 297 米、坡度 22 度、坡向朝东,都是 30 米地形算出来的。",
                  "点运行,模型给出春季积温、六年累计霜冻 534 小时和预计开采期,72 小时本地气温一起出来;六张专题图层可叠加对比。"]),
    ("模型怎么练的", ["模型用真实数据训练:ERA5-Land 再分析,1950 到 2026 年六十七万小时,加 30 米地形和 10 米精度茶园分布图。",
                    "LightGBM 分位数回归,一次输出 P10、P50、P90,预报时效也是特征。",
                    "训练、验证、测试按时间严格切开,2025 年后的数据只测一次:平均误差 1.52 度,比持续性预报准 41%,24 小时最低温正负两度命中 74%。"]),
    ("传感器与手机", ["传感器随时接进来:上传一份 CSV,模型就用实测值锚定预测。",
                   "田里用手机看——小程序和大盘是同一套数据,地图底图就是这片山的真实地形。"]),
    ("落版", ["梅家坞茶园微气候智能体。", "把气候,变成农事。"]),
]


def tts(text, path):
    ps = ("Add-Type -AssemblyName System.Speech; "
          "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
          f"$s.SelectVoice('{VOICE}'); $s.Rate = {RATE}; "
          f"$s.SetOutputToWaveFile('{path}'); $s.Speak([Console]::In.ReadToEnd()); $s.Dispose()")
    subprocess.run(["powershell", "-NoProfile", "-Command", ps], input=text.encode("utf-8"), check=True,
                   capture_output=True)


def to48(path):
    out = path.with_suffix(".48.wav")
    subprocess.run([FFMPEG, "-v", "error", "-y", "-i", str(path), "-ar", "48000", "-ac", "1",
                    "-sample_fmt", "s16", str(out)], check=True)
    with wave.open(str(out)) as w:
        dur = w.getnframes() / w.getframerate()
    return out, dur


def main():
    rows, t = [], 0.0
    for ci, (chap, sents) in enumerate(CH):
        if ci:
            t += CH_GAP
        ch_start = t
        segs = []
        for si, s in enumerate(sents):
            raw = NA / f"c{ci}_s{si}.wav"
            tts(s, raw)
            w48, dur = to48(raw)
            segs.append({"text": s, "t": round(t, 3), "dur": round(dur, 3), "wav": w48.name})
            t += dur + (SENT_GAP if si < len(sents) - 1 else 0.0)
        rows.append({"chapter": chap, "t": round(ch_start, 3), "end": round(t, 3), "segs": segs, "dur": round(t - ch_start, 3)})
        print(f"{chap:8} {ch_start:6.2f} → {t:6.2f}  ({t - ch_start:5.2f}s, {len(sents)} 句)")
    total = t + 1.6                     # 落版后再停一拍
    js = ("window.NARR = " + json.dumps({"total": round(total, 2), "sentenceGap": SENT_GAP,
                                         "chapterGap": CH_GAP, "chapters": rows}, ensure_ascii=False) + ";\n")
    (HERE / "assets" / "narration.js").write_text(js, encoding="utf-8")
    print(f"旁白总长 {t:.2f}s; 影片总长 {total:.2f}s → assets/narration.js")


if __name__ == "__main__":
    main()
