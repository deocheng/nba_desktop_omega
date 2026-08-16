#!/usr/bin/env python3
"""在线清理 CDP Chrome 的 HTTP 缓存（广告资源大头），不中断正在跑的爬虫。

背景：BR 每个页面带 ~50 个广告 iframe（doubleclick / adtrafficquality /
googlesyndication / pubmatic / rubicon / 3lift / hadronid / voltaxam …），
长时间爬取后 Chrome 的 Default/Cache 会堆到 GB 级（实测 1.2G / 158,299 文件），
挤占内存与磁盘，并与 createTarget 失败（HTTP 500 空转）相关。

安全边界（重要）：
  * 只调 ``Network.clearBrowserCache``（清 HTTP 缓存）。
  * **绝不调** ``Network.clearBrowserCookies`` —— 那会抹掉 cf_clearance，
    导致必须人工重过 Cloudflare 验证。
  * 不碰 Cookies / Local Storage / IndexedDB。

用法:
    python3 cdp_clear_ad_cache.py [--cdp http://127.0.0.1:9223]
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.request

try:
    import websocket  # websocket-client
except ImportError:  # pragma: no cover
    sys.exit("需要 websocket-client：pip install websocket-client")

# 广告/追踪域名（仅用于清理前后的统计展示，不参与删除决策）
AD_DOMAINS = (
    "doubleclick", "googlesyndication", "adtrafficquality", "ad-delivery",
    "pubmatic", "rubiconproject", "3lift", "adnxs", "indexww", "criteo",
    "openx", "smartadserver", "amazon-adsystem", "hadronid", "voltaxam",
    "pub.network", "lijit", "a-mx", "media.net", "freestar",
)


def _http_get(base: str, path: str):
    """走本地直连的 CDP HTTP 调用（绕开可能存在的死代理）。"""
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(base.rstrip("/") + path, timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _http_put(base: str, path: str):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    req = urllib.request.Request(base.rstrip("/") + path, method="PUT", data=b"")
    with opener.open(req, timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _close_target(base: str, tid: str) -> None:
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        opener.open(base.rstrip("/") + f"/json/close/{tid}", timeout=10).read()
    except Exception:  # noqa: BLE001 - 清理失败不影响主流程
        pass


def clear_cache(cdp_base: str) -> bool:
    """在一个临时 target 上执行 Network.clearBrowserCache。

    Returns:
        True 表示缓存清理命令已被 Chrome 接受。
    """
    tgt = _http_put(cdp_base, "/json/new?about:blank")
    tid, ws_url = tgt.get("id"), tgt.get("webSocketDebuggerUrl")
    if not ws_url:
        print("!! 无法创建临时 target（Chrome 可能内存耗尽）")
        return False
    print(f"临时 target: {tid}")
    ok = False
    try:
        # suppress_origin: Chrome 151+ 校验 Origin 头，带 Origin 会被 403 拒绝
        ws = websocket.create_connection(ws_url, timeout=30, suppress_origin=True)
        try:
            for mid, method in ((1, "Network.enable"), (2, "Network.clearBrowserCache")):
                ws.send(json.dumps({"id": mid, "method": method}))
                while True:
                    msg = json.loads(ws.recv())
                    if msg.get("id") == mid:
                        if "error" in msg:
                            print(f"!! {method} 失败: {msg['error']}")
                        else:
                            print(f"OK  {method}")
                            if mid == 2:
                                ok = True
                        break
        finally:
            ws.close()
    finally:
        if tid:
            _close_target(cdp_base, tid)
    return ok


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cdp", default="http://127.0.0.1:9223")
    args = ap.parse_args()

    ver = _http_get(args.cdp, "/json/version")
    print(f"已连接 {ver.get('Browser')}")
    targets = _http_get(args.cdp, "/json")
    ads = sum(1 for t in targets
              if any(d in t.get("url", "") for d in AD_DOMAINS))
    print(f"当前 target 数: {len(targets)}（其中广告域 {ads} 个）")

    if clear_cache(args.cdp):
        print("HTTP 缓存已清理（cookies / cf_clearance 未触碰）")
    else:
        print("清理未成功，请检查 Chrome 状态")


if __name__ == "__main__":
    main()
