#!/usr/bin/env python3
"""探测 BR 三种 Play-In 页面结构 + 验证 PHX->PHO。每抓开新标签、用完关闭。"""
import sys, json, time, urllib.request, urllib.parse
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, "/Volumes/12T/NBA/nba_desktop_omega_mac_migrate_2026-07-13")
import websocket
from bs4 import BeautifulSoup

CDP = "http://127.0.0.1:9223"

def fetch(url, wait=5.0):
    """开新标签加载 url -> HTML -> 关闭标签。"""
    req = urllib.request.Request(f"{CDP}/json/new?{urllib.parse.quote(url, safe='')}", data=b"", method="PUT")
    with urllib.request.urlopen(req, timeout=8) as r:
        tab = json.load(r)
    tab_id = tab["id"]
    ws = websocket.create_connection(tab["webSocketDebuggerUrl"], timeout=30)
    _id = 0
    def send(method, params=None):
        nonlocal _id; _id += 1
        ws.send(json.dumps({"id": _id, "method": method, "params": params or {}}))
        return _id
    def recv_id(want):
        while True:
            msg = json.loads(ws.recv())
            if msg.get("id") == want:
                return msg
    send("Page.enable"); send("Runtime.enable")
    send("Page.navigate", {"url": url})
    deadline = time.time() + 25
    while time.time() < deadline:
        try:
            ws.settimeout(2)
            msg = json.loads(ws.recv())
            if msg.get("method") == "Page.loadEventFired":
                break
        except Exception:
            continue
    time.sleep(wait)
    eid = send("Runtime.evaluate", {"expression": "document.documentElement.outerHTML", "returnByValue": True})
    res = recv_id(eid)
    html = res.get("result", {}).get("result", {}).get("value", "")
    ws.close()
    try:
        urllib.request.urlopen(f"{CDP}/json/close/{tab_id}", timeout=5)
    except Exception:
        pass
    return html

def report(url, html):
    low = html.lower()
    if "just a moment" in low or "attention required" in low:
        print(f"  CF_BLOCKED len={len(html)}"); return
    soup = BeautifulSoup(html, "lxml")
    tables = soup.find_all("table")
    tids = [t.get("id") for t in tables]
    h1 = soup.find("h1")
    print(f"  len={len(html)} h1={h1.get_text(strip=True)[:60] if h1 else None} tables={len(tids)} ids={tids}")
    if "page not found" in low or "404 error" in low or "not found" in low[:3000]:
        print("  *** looks like 404 ***")

def main():
    base = "https://www.basketball-reference.com/boxscores"
    for label, url in [
        ("PBP 202404190MIA", f"{base}/pbp/202404190MIA.html"),
        ("SHOT 202404190MIA", f"{base}/shot-chart/202404190MIA.html"),
        ("PM 202404190MIA", f"{base}/plus-minus/202404190MIA.html"),
        ("PBP 202604140PHO (was 404 as PHX)", f"{base}/pbp/202604140PHO.html"),
    ]:
        print(f"=== {label} ===")
        try:
            report(url, fetch(url))
        except Exception as e:
            print(f"  ERROR: {e}")
        time.sleep(4.5)

if __name__ == "__main__":
    main()
