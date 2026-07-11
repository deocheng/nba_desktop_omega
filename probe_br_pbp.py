"""Probe the BR PBP table structure from saved sample to design the parser."""
from __future__ import annotations
from bs4 import BeautifulSoup

HTML = "br_pbp_sample.html"
with open(HTML, encoding="utf-8") as f:
    soup = BeautifulSoup(f.read(), "html.parser")

tbl = soup.find("table", id="pbp")
print("table found:", tbl is not None)
if not tbl:
    # fallback: any table with pbp in id
    tbl = soup.find("table", id=lambda x: x and "pbp" in x.lower())
    print("fallback table:", tbl is not None)

thead = tbl.find("thead")
headers = [th.get_text(strip=True) for th in thead.find_all("th")] if thead else []
print("HEADERS:", headers)

tbody = tbl.find("tbody")
rows = tbody.find_all("tr") if tbody else []
print("data rows:", len(rows))

# Print first 8 rows with all cell texts
for i, tr in enumerate(rows[:8]):
    cells = [td.get_text(strip=True) for td in tr.find_all(["th", "td"])]
    print(f"  row{i}: {cells}")

# Find example rows containing keywords to understand description formats
import re
texts = []
for tr in rows:
    cells = [td.get_text(strip=True) for td in tr.find_all(["th", "td"])]
    joined = " | ".join(cells)
    texts.append(cells)

def find_example(keyword, n=2):
    out = []
    for cells in texts:
        if any(keyword.lower() in c.lower() for c in cells):
            out.append(cells)
            if len(out) >= n:
                break
    return out

for kw in ["makes", "misses", "Free Throw", "Rebound", "Turnover", "SUB:", "Foul", "Steal", "Block"]:
    ex = find_example(kw, 1)
    if ex:
        print(f"\nEXAMPLE [{kw}]: {ex[0]}")
