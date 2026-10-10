"""把训练好的 LightGBM 模型导出为纯 JavaScript(零 Python 依赖部署)。

用途: 与 microclimate-sensor-network(Express/Node 后端)直接集成 ——
其上游项目同样用 LightGBM + m2cgen 导出 JS 在服务端跑预报。
导出后把 JS 模型 + features.json 放进其后端, 输入按 features.json 顺序给特征即可。

用法:
  python scripts/export_to_js.py --config config.yaml            # 导出 P10/P50/P90 + RH
  python scripts/export_to_js.py --config config.yaml --suffix _ft_s1
产物: web/models/lgbm_t2m_p{10,50,90}{suffix}.js + web/models/features{suffix}.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import joblib
import m2cgen as m2c
import yaml


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--suffix", default="", help="如 _ft_s1 导出微调模型")
    args = ap.parse_args()

    with open(args.config, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    outdir = Path(cfg["model"]["output_dir"])
    out = Path("web/models")
    out.mkdir(parents=True, exist_ok=True)

    feat_list = json.loads((outdir / "features.json").read_text())
    exported = []
    for q in ("p10", "p50", "p90"):
        p = outdir / f"lgbm_t2m_{q}{args.suffix}.joblib"
        if not p.exists():
            continue
        mdl = joblib.load(p)
        js = m2c.export_to_javascript(mdl)
        (out / f"lgbm_t2m_{q}{args.suffix}.js").write_text(
            f"// 梅家坞茶园微气候模型 · {q} 分位数(残差口径, 特征顺序见 features.json)\n{js}\n",
            encoding="utf-8")
        exported.append(f"lgbm_t2m_{q}{args.suffix}.js")

    with open(out / f"features{args.suffix}.json", "w", encoding="utf-8") as f:
        json.dump({"features": feat_list}, f, ensure_ascii=False, indent=2)
    print(f"[export] 已导出 {exported} -> {out}")
    print(f"[export] 特征顺序清单 -> {out / ('features' + args.suffix + '.json')}")


if __name__ == "__main__":
    main()
