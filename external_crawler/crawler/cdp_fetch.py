#!/usr/bin/env python3
"""通过 CDP (127.0.0.1:9223, 已带 cf_clearance 的 chrome_cdp_profile) 抓取网页 HTML。
用法: cdp_fetch.py <url>
返回页面 outerHTML。用于 BR 等被 Cloudflare 墙的站点(已手动过 CF)。"""
import json
import sys
import time

import websocket

sys.stdout.reconfigure(encoding="utf-8")

CDP = "http://127.0.0.1:9223"

def _list_targets():
    import urllib.request
    with urllib.request.urlopen(f"{CDP}/json/list", timeout=5) as r:
        return json.load(r)

def fetch_url(url, wait=4.0, timeout=30):
    # 打开新标签页(真实 URL, 非 about:blank)
    import urllib.parse
    import urllib.request
    req = urllib.request.Request(f"{CDP}/json/new?{urllib.parse.quote(url, safe='')}",
                                 data=b"", method="PUT")
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            tab = json.load(r)
    except Exception as e:
        # 回退: 复用现有 page target
        tabs = [t for t in _list_targets() if t.get("type") == "page"]
        tab = tabs[0] if tabs else None
        if not tab:
            raise RuntimeError("无可用 CDP 标签页")
    ws = tab["webSocketDebuggerUrl"]
    sock = websocket.create_connection(ws, timeout=timeout)
    _id = 0
    def send(method, params=None):
        nonlocal _id
        _id += 1
        sock.send(json.dumps({"id": _id, "method": method, "params": params or {}}))
        return _id
    def recv_id(want):
        while True:
            msg = json.loads(sock.recv())
            if msg.get("id") == want:
                return msg
    send("Page.enable"); send("Runtime.enable")
    nav_id = send("Page.navigate", {"url": url})
    recv_id(nav_id)  # navigate 回包(不一定有)
    # 等待加载
    deadline = time.time() + timeout
    loaded = False
    while time.time() < deadline:
        try:
            sock.settimeout(2)
            msg = json.loads(sock.recv())
        except Exception:
            continue
        if msg.get("method") == "Page.loadEventFired":
            loaded = True
            break
    time.sleep(wait)
    # 取 HTML
    ev_id = send("Runtime.evaluate",
                 {"expression": "document.documentElement.outerHTML", "returnByValue": True})
    res = recv_id(ev_id)
    html = res.get("result", {}).get("result", {}).get("value", "")
    sock.close()
    return html

if __name__ == "__main__":
    url = sys.argv[1] if len(sys.argv) > 1 else "https://www.basketball-reference.com/boxscores/202404190MIA.html"
    html = fetch_url(url)
    # 诊断
    low = html.lower()
    if "just a moment" in low or "attention required" in low or "cf-browser-verification" in low:
        print("CF_BLOCKED len=", len(html))
    elif "boxscore" in low and ("class=\"stats_table" in html or "table_wrapper" in html or "per_game" in html):
        print("OK_BOXSCORE len=", len(html))
    else:
        print("UNKNOWN len=", len(html))
    # 打印前 200 字符诊断
    print(html[:200])
