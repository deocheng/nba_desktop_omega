#!/usr/bin/env python3
"""Probe: fetch a 2023 Play-In BR boxscore and inspect parse-ability."""
import random
import sys
import time

sys.stdout.reconfigure(encoding="utf-8")
from bs4 import BeautifulSoup
from curl_cffi import requests

URL = "https://www.basketball-reference.com/boxscores/202304110MIA.html"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
}

def fetch(url):
    for attempt in range(3):
        try:
            r = requests.get(url, headers=HEADERS, timeout=25, impersonate="chrome124")
            if r.status_code == 200:
                return r.text
            print(f"HTTP {r.status_code}")
            if r.status_code == 403 and attempt < 2:
                time.sleep(5 + random.uniform(0, 2)); continue
        except Exception as e:
            print(f"err {e}")
    return None

html = fetch(URL)
if not html:
    print("FETCH FAILED")
    sys.exit(1)
print("HTML len:", len(html))
soup = BeautifulSoup(html, "html.parser")
# List all tables whose id contains 'box'
box_tables = [t.get("id") for t in soup.find_all("table") if t.get("id") and "box" in t.get("id")]
print("BOX TABLES:", box_tables)
# Try parsing the first basic box table for away team
for tid in box_tables:
    if "basic" in tid:
        tbl = soup.find("table", id=tid)
        if not tbl: continue
        rows = tbl.find_all("tr")
        print(f"\n=== TABLE {tid} : {len(rows)} rows ===")
        cnt = 0
        for tr in rows:
            th = tr.find("th")
            if th and th.get("data-stat") == "player":
                name = th.find("a")
                nm = name.get_text() if name else th.get_text()
                tds = tr.find_all("td")
                if not tds: continue
                mp = tds[0].get_text() if len(tds) > 0 else ""
                pts = tds[20].get_text() if len(tds) > 20 else (tds[-1].get_text() if tds else "")
                print(f"  {nm:22s} MP={mp} PTS={pts}")
                cnt += 1
                if cnt >= 4: break
        break
print("\nPROBE DONE")
