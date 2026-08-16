#!/usr/bin/env python3
"""Screenshot verify_user_version.html with Playwright."""
from pathlib import Path

from playwright.sync_api import sync_playwright

html_path = Path(__file__).parent / "verify_user_version.html"
out_path = Path(__file__).parent / "verify_user_version_preview.png"

with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(viewport={"width": 1400, "height": 1300})
    page.goto(f"file://{html_path}")
    page.wait_for_timeout(500)
    page.screenshot(path=str(out_path), full_page=True)
    browser.close()

print(f"Wrote {out_path}")
