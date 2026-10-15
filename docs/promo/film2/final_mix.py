# -*- coding: utf-8 -*-
"""final_mix.py — 把旁白叠到环境床上(带闪避), 输出 sfx2.wav 交给 render.py 混进成片

旁白: assets/narr/*.48.wav(逐句, 时间点来自 narration.js)——说话时把床压下去, 说完抬回来;
最后统一留 4.5 dB 余量, 不削顶(verify 会查峰值与削波)。
"""
import json
import pathlib
import wave

import numpy as np

HERE = pathlib.Path(__file__).parent
SR = 48000
NARR = json.loads((HERE / "assets" / "narration.js").read_text(encoding="utf-8")
                  .replace("window.NARR = ", "").rstrip(";\n"))
DUR = NARR["total"] + 5.6
N = int(SR * DUR)


def read_wav(p):
    with wave.open(str(p)) as w:
        assert w.getsampwidth() == 2
        x = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float64) / 32768
        if w.getnchannels() == 2:
            x = x.reshape(-1, 2)
        else:
            x = np.stack([x, x], 1)
        return x, w.getframerate()


bed, sr = read_wav(HERE / "bed.wav")
assert sr == SR
bed = np.resize(bed, (N, 2))

voice = np.zeros((N, 2))
segs = [sg for c in NARR["chapters"] for sg in c["segs"]]
for sg in segs:
    x, sr2 = read_wav(HERE / "assets" / "narr" / sg["wav"])
    assert sr2 == SR
    x = x[: int(SR * sg["dur"])]
    # 逐句归一: 峰值到 -7 dBFS, 让整片响度一致
    x = x / (np.abs(x).max() + 1e-9) * 0.45
    i0 = int(sg["t"] * SR)
    n = min(len(x), N - i0)
    voice[i0:i0 + n] += x[:n]

# 闪避: 有旁白时床降到 0.45, 前后各 0.35s 过渡
act = (np.abs(voice).max(axis=1) > 0.02).astype(np.float64)
k = int(SR * 0.35)
env = np.convolve(act, np.ones(k) / k, mode="same")
duck = 1.0 - 0.55 * np.clip(env * 1.6, 0, 1)
mix = bed * duck[:, None] * 0.62 + voice * 0.92

peak = np.abs(mix).max()
mix = mix / (peak + 1e-9) * (10 ** (-4.5 / 20))
print(f"旁白 {len(segs)} 句, 混音峰值 -4.5 dBFS(原 {20 * np.log10(peak + 1e-9):.1f} dB), 时长 {DUR:.2f}s")
out = HERE / "sfx2.wav"
with wave.open(str(out), "wb") as w:
    w.setnchannels(2)
    w.setsampwidth(2)
    w.setframerate(SR)
    w.writeframes((mix * 32767).astype(np.int16).tobytes())
print(out, out.stat().st_size // 1024 // 1024, "MB")
