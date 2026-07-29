import re, json, sys
from collections import defaultdict
from playwright.sync_api import sync_playwright

SLUGS = "ATL,BOS,BRK,CHI,CHO,CLE,DAL,DEN,DET,GSW,HOU,IND,LAC,LAL,MEM,MIA,MIL,MIN,NOP,NYK,OKC,ORL,PHI,PHO,POR,SAC,SAS,TOR,UTA,WAS".split(",")

def extract(slug):
    url = f"https://www.basketball-reference.com/teams/{slug}/"
    with sync_playwright() as p:
        b = p.chromium.connect_over_cdp("http://127.0.0.1:9223")
        ctx = b.contexts[0]
        pg = ctx.new_page()
        try:
            pg.goto(url, wait_until="domcontentloaded", timeout=30000)
            pg.wait_for_timeout(3500)
            html = pg.content()
        finally:
            pg.close(); b.close()
    pairs = re.findall(r'/teams/([A-Z]{2,4})/(\d{4})', html)
    d = defaultdict(set)
    for ab, yr in pairs:
        d[ab].add(int(yr))
    return {ab: [min(y), max(y)] for ab, y in d.items() if min(y) < 2025}

result = {}
for s in SLUGS:
    try:
        result[s] = extract(s)
        print(s, "->", sorted(result[s].keys()), flush=True)
    except Exception as e:
        print(f"ERR {s}: {e}", flush=True)
        result[s] = {}

with open("/tmp/franchise_map.json", "w") as f:
    json.dump(result, f, indent=2)
print("SAVED /tmp/franchise_map.json", flush=True)
