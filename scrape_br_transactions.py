#!/usr/bin/env python3
"""Faithful scrape of BR team transactions page -> verbatim sentence list.

Uses undetected-chromedriver (UC) so Cloudflare JS challenge is passed.
Saves:
  det2026_br/DET_2026_transactions_raw.html   (raw page source)
  det2026_br/DET_2026_transactions_verbatim.txt  (one sentence per line, date prefix stripped)
"""
import os, re, sys, time
import undetected_chromedriver as uc
from bs4 import BeautifulSoup

URL = "https://www.basketball-reference.com/teams/DET/2026_transactions.html"
OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "det2026_br")
os.makedirs(OUT_DIR, exist_ok=True)

RAW = os.path.join(OUT_DIR, "DET_2026_transactions_raw.html")
TXT = os.path.join(OUT_DIR, "DET_2026_transactions_verbatim.txt")

def main():
    opts = uc.ChromeOptions()
    opts.headless = True
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    # realistic UA helps with CF; uc sets its own but be explicit
    opts.add_argument(
        "--user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36"
    )
    print("[i] launching UC Chrome ...")
    d = uc.Chrome(options=opts)
    try:
        print("[i] GET", URL)
        d.get(URL)
        # let CF/JS settle + list render
        time.sleep(6)
        html = d.page_source
        with open(RAW, "w", encoding="utf-8") as f:
            f.write(html)
        print(f"[i] raw html saved: {len(html)} bytes -> {RAW}")

        soup = BeautifulSoup(html, "html.parser")
        # BR transactions are <li> items inside .section_content; grab all <li>
        lis = soup.find_all("li")
        sentences = []
        seen = set()
        for li in lis:
            txt = li.get_text(" ", strip=True)
            # keep only transaction-like lines
            if re.search(r"Pistons?\b.*\b(signed|traded|waived|claimed|converted|re-signed|released|assigned|appointed)\b",
                         txt, re.I):
                # strip the leading "Month Day, Year: " date prefix
                cleaned = re.sub(r"^[A-Z][a-z]+\.?\s*\d{1,2},?\s*\d{4}\s*:\s*", "", txt).strip()
                if cleaned and cleaned not in seen:
                    seen.add(cleaned)
                    sentences.append(cleaned)
        print(f"[i] extracted {len(sentences)} transaction sentences")
        with open(TXT, "w", encoding="utf-8") as f:
            for s in sentences:
                f.write(s + "\n")
        print(f"[i] verbatim saved -> {TXT}")
    finally:
        d.quit()
        print("[i] done")

if __name__ == "__main__":
    main()
