# -*- coding: utf-8 -*-
"""
geosite/net.py — 网络请求统一入口 (代理/直连自动切换 + 重试)
============================================================
本机 (Windows + Clash) 与队友机器的网络状态各异:
- 系统代理 (注册表 127.0.0.1:7897) 在 Clash 启动/关闭过渡期会瞬时失败;
- 直连访问 open-meteo / Azure Blob 偶发 TLS 干扰;
因此依次尝试 代理 → 直连, 循环重试, 覆盖两种状态。
"""
import json
import time
import urllib.error
import urllib.request


def _opener(use_proxy):
    if use_proxy:
        return urllib.request.build_opener()                 # 系统代理
    return urllib.request.build_opener(urllib.request.ProxyHandler({}))  # 直连


def urlopen_json(url, timeout=240, retries=6):
    """请求并解析 JSON (重试: 代理/直连交替)"""
    last = None
    for i in range(retries):
        try:
            with _opener(i % 2 == 0).open(url, timeout=timeout) as r:
                return json.load(r)
        except (urllib.error.URLError, urllib.error.HTTPError,
                TimeoutError, ConnectionError, OSError) as e:
            last = e
            detail = ""
            if isinstance(e, urllib.error.HTTPError):
                body = ""
                try:
                    body = e.read(300).decode("utf-8", "replace")
                except Exception:  # noqa: BLE001
                    pass
                detail = (f" | server={e.headers.get('Server')} "
                          f"| body={body[:200]!r}")
            print(f"[net] 尝试{i + 1}/{'代理' if i % 2 == 0 else '直连'} "
                  f"失败: {type(e).__name__}: {e}{detail}", flush=True)
            time.sleep(1.0 + i)
    raise last


def download(url, dest, timeout=300, retries=4, min_bytes=100_000):
    """下载文件到本地 (幂等: 已存在且足够大则跳过; 失败自动换通道重试)"""
    import os
    if os.path.exists(dest) and os.path.getsize(dest) > min_bytes:
        return dest
    last = None
    for i in range(retries):
        try:
            _opener(i % 2 == 0).retrieve(url, dest)
            if os.path.getsize(dest) > min_bytes:
                return dest
        except (urllib.error.URLError, urllib.error.HTTPError,
                TimeoutError, ConnectionError, OSError) as e:
            last = e
            time.sleep(1.5 * (i + 1))
    raise last
