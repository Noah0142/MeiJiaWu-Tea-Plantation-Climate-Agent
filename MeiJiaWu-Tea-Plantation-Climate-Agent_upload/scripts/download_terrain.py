# -*- coding: utf-8 -*-
"""
download_terrain.py — 梅家坞茶园地形数据下载 (幂等, 可重复运行)
=============================================================
数据源:
  1) NASADEM 30m (NASA, 2020) — SRTM 重处理版, 首选 DEM
     经 Microsoft Planetary Computer 公开 STAC 获取 (无需注册)
  2) CGIAR SRTM v4.1 90m (2008) — 交叉验证备份
     https://srtm.csi.cgiar.org

运行: py -3.9 scripts/download_terrain.py

以后如需更高精度 (12.5m ALOS AW3D30 / FABDEM), 需在对应官网注册:
  ALOS: https://www.eorc.jaxa.jp/ALOS/en/aw3d30/
  FABDEM: https://www.fathom.global/product/fabdem/
"""
import json
import os
import sys
import urllib.parse
import urllib.request
import zipfile

TERRAIN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "data", "terrain")

NASADEM_ITEM = "NASADEM_HGT_n30e120"            # 覆盖 120-121E, 30-31N
NASADEM_URL = ("https://nasademeuwest.blob.core.windows.net/nasadem-cog/v001/"
               f"{NASADEM_ITEM}.tif")
SIGN_API = "https://planetarycomputer.microsoft.com/api/sas/v1/sign"
SRTM_URL = ("https://srtm.csi.cgiar.org/wp-content/uploads/files/srtm_5x5/TIFF/"
            "srtm_61_06.zip")                    # 覆盖 120-125E, 30-35N


def fetch(url, dest, desc):
    if os.path.exists(dest) and os.path.getsize(dest) > 100_000:
        print(f"[跳过] {desc} 已存在: {dest}")
        return
    print(f"[下载] {desc} ...")
    urllib.request.urlretrieve(url, dest)
    print(f"[完成] {desc}: {os.path.getsize(dest):,} bytes")


def main():
    os.makedirs(TERRAIN, exist_ok=True)

    # 1) NASADEM: 先签名再下载
    nasadem_path = os.path.join(TERRAIN, "nasadem_N30E120.tif")
    if not (os.path.exists(nasadem_path) and os.path.getsize(nasadem_path) > 100_000):
        sign_url = SIGN_API + "?href=" + urllib.parse.quote(NASADEM_URL, safe="")
        with urllib.request.urlopen(sign_url, timeout=30) as r:
            signed = json.load(r)["href"]
        fetch(signed, nasadem_path, "NASADEM 30m N30E120")

    # 2) CGIAR SRTM v4.1
    zip_path = os.path.join(TERRAIN, "srtm_61_06.zip")
    fetch(SRTM_URL, zip_path, "CGIAR SRTM 90m srtm_61_06")
    tif_path = os.path.join(TERRAIN, "srtm_61_06.tif")
    if not os.path.exists(tif_path):
        print("[解压] srtm_61_06.zip ...")
        with zipfile.ZipFile(zip_path) as z:
            z.extractall(TERRAIN)

    print("\n数据就绪。下一步: py -3.9 scripts/process_dem.py")


if __name__ == "__main__":
    sys.exit(main())
