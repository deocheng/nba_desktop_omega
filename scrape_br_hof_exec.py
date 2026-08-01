#!/usr/bin/env python3
"""Faithful scrape of BR team HoF + Executives pages via UC Chrome.

Both pages hide their data tables inside HTML comment blocks (like the stat
tables). UC Chrome executes the JS so the page fully renders, then we
parse every <table> from BOTH the main doc and the comment blocks.
Outputs raw HTML + per-table CSV + a combined JSON under det2026_br/.
"""
import os, re, sys, time, json
import undetected_chromedriver as uc
from bs4 import BeautifulSoup, Comment

BASE = "https://www.basketball-reference.com/teams/DET"
PAGES = {
    "hof":        f"{BASE}/hof.html",
    "executives": f"{BASE}/executives.html",
}
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "det2026_br")
os.makedirs(OUT, exist_ok=True)


def extract_tables(soup):
    """Return list of (table_id, headers, rows) from a soup (incl. comment blocks)."""
    tables = []
    # main doc
    for tbl in soup.find_all("table"):
        tables.append(tbl)
    # comment blocks
    for c in soup.find_all(string=lambda s: isinstance(s, Comment)):
        sub = BeautifulSoup(str(c), "html.parser")
        for tbl in sub.find_all("table"):
            tables.append(tbl)
    out = []
    for idx, tbl in enumerate(tables):
        # caption / id for naming
        name = tbl.get("id") or (tbl.find_previous(["h2", "h3", "h4"]) or {}).get_text and \
               (tbl.find_previous(["h2", "h3", "h4"]).get_text(" ", strip=True))
        name = re.sub(r"\W+", "_", str(name or f"table_{idx}"))[:40]
        head = tbl.find("thead")
        if head:
            headers = [th.get_text(" ", strip=True) for th in head.find_all("th")]
        else:
            first = tbl.find("tr")
            headers = [th.get_text(" ", strip=True) for th in (first.find_all(["th", "td"]) if first else [])]
        rows = []
        for tr in tbl.find("tbody").find_all("tr") if tbl.find("tbody") else []:
            cells = [td.get_text(" ", strip=True) for td in tr.find_all(["th", "td"])]
            if cells:
                rows.append(cells)
        if headers or rows:
            out.append((name, headers, rows))
    return out


def _is_cf_challenge(html):
    low = html.lower()
    return ("请稍候" in html) or ("just a moment" in low) or ("attention required" in low) \
        or ("verify you are human" in low) or ("ray id:" in low and "cloudflare" in low)

def scrape(url, warm=BASE, retries=4):
    opts = uc.ChromeOptions()
    opts.headless = True
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument(
        "--user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36")
    for attempt in range(1, retries + 1):
        d = uc.Chrome(options=opts)
        try:
            # warm up: get root domain first to obtain a session cookie
            if warm:
                try:
                    d.get(warm); time.sleep(3)
                except Exception:
                    pass
            d.get(url)
            time.sleep(8)
            html = d.page_source
            if not _is_cf_challenge(html):
                print(f"    [attempt {attempt}] OK, got {len(html)} bytes")
                return html
            print(f"    [attempt {attempt}] CF challenge, retrying...")
        finally:
            d.quit()
        time.sleep(3)
    # last resort: return whatever (caller will detect)
    return html


def main():
    summary = {}
    for key, url in PAGES.items():
        print(f"[i] scraping {key}: {url}")
        html = scrape(url)
        raw = os.path.join(OUT, f"DET_{key}.html")
        with open(raw, "w", encoding="utf-8") as f:
            f.write(html)
        soup = BeautifulSoup(html, "html.parser")
        tables = extract_tables(soup)
        print(f"    found {len(tables)} tables")
        page_json = []
        for name, headers, rows in tables:
            fn = os.path.join(OUT, f"DET_{key}_{name}.csv")
            with open(fn, "w", encoding="utf-8") as f:
                if headers:
                    f.write(",".join(f'"{h}"' for h in headers) + "\n")
                for r in rows:
                    f.write(",".join(f'"{c}"' for c in r) + "\n")
            page_json.append({"name": name, "headers": headers, "rows": rows})
        jf = os.path.join(OUT, f"DET_{key}_tables.json")
        with open(jf, "w", encoding="utf-8") as f:
            json.dump(page_json, f, ensure_ascii=False, indent=1)
        summary[key] = {"raw": raw, "tables": len(tables),
                        "rows_total": sum(len(t[2]) for t in tables)}
        # print a quick peek
        for name, headers, rows in tables[:1]:
            print(f"    [{name}] headers={headers[:8]}")
            for r in rows[:3]:
                print(f"        {r[:6]}")
    print("[i] DONE", json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
