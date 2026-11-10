#!/usr/bin/env python3
"""抓 202404190MIA 三页存盘 + 离线打印投篮图/正负值表结构。"""
import json
import os
import sys
import time
import urllib.parse
import urllib.request

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, "/Volumes/12T/NBA/nba_desktop_omega_mac_migrate_2026-07-13")
import websocket
from bs4 import BeautifulSoup

CDP = "http://127.0.0.1:9223"
OUT = "/tmp/playin_sample"
os.makedirs(OUT, exist_ok=True)

def fetch(url, wait=5.0, retries=2):
    for att in range(retries + 1):
        try:
            req = urllib.request.Request(f"{CDP}/json/new?{urllib.parse.quote(url, safe='')}", data=b"", method="PUT")
            with urllib.request.urlopen(req, timeout=8) as r:
                tab = json.load(r)
            tab_id = tab["id"]
            ws = websocket.create_connection(tab["webSocketDebuggerUrl"], timeout=30)
            _id = 0
            def send(m, p=None):
                nonlocal _id; _id += 1
                ws.send(json.dumps({"id": _id, "method": m, "params": p or {}})); return _id
            def recv_id(w):
                while True:
                    msg = json.loads(ws.recv())
                    if msg.get("id") == w: return msg
            send("Page.enable"); send("Runtime.enable"); send("Page.navigate", {"url": url})
            dl = time.time() + 25
            while time.time() < dl:
                try:
                    ws.settimeout(2); msg = json.loads(ws.recv())
                    if msg.get("method") == "Page.loadEventFired": break
                except Exception: continue
            time.sleep(wait)
            eid = send("Runtime.evaluate", {"expression": "document.documentElement.outerHTML", "returnByValue": True})
            html = recv_id(eid).get("result", {}).get("result", {}).get("value", "")
            ws.close()
            try: urllib.request.urlopen(f"{CDP}/json/close/{tab_id}", timeout=5)
            except Exception: pass
            if len(html) > 5000: return html
        except Exception as e:
            print(f"  retry {att}: {e}"); time.sleep(2)
    return ""

def dump_table(tbl, label, n=3):
    rows = tbl.find_all("tr")
    print(f"  [{label}] id={tbl.get('id')} class={tbl.get('class')} rows={len(rows)}")
    # header
    hdr = [c.get_text(strip=True) for c in rows[0].find_all(['th','td'])] if rows else []
    print(f"    header: {hdr}")
    for tr in rows[1:1+n]:
        cells = [c.get_text(strip=True) for c in tr.find_all(['th','td'])]
        print(f"    row: {cells}")

def main():
    base = "https://www.basketball-reference.com/boxscores"
    pages = [("pbp","pbp"), ("shot","shot-chart"), ("pm","plus-minus")]
    for tag, kind in pages:
        url = f"{base}/{kind}/202404190MIA.html"
        print(f"=== fetch {tag} ===")
        html = fetch(url)
        path = f"{OUT}/{tag}.html"
        with open(path, "w", encoding="utf-8") as f: f.write(html)
        print(f"  saved {len(html)} -> {path}")
        time.sleep(4.5)
    # offline inspect shot + pm
    for tag in ["shot", "pm"]:
        print(f"\n=== inspect {tag} ===")
        soup = BeautifulSoup(open(f"{OUT}/{tag}.html", encoding="utf-8").read(), "lxml")
        for tbl in soup.find_all("table"):
            tid = tbl.get("id")
            if tid and tid.startswith("shooting-"):
                dump_table(tbl, tid)
            elif tag == "pm":
                dump_table(tbl, "pm-table")

if __name__ == "__main__":
    main()
