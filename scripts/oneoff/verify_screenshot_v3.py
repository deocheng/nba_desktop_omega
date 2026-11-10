#!/usr/bin/env python3
"""Screenshot verify_v3.html with Playwright."""
from pathlib import Path

from playwright.sync_api import sync_playwright

#: 仓库根（脚本已收敛到 scripts/oneoff/，自身目录不再是仓库根）
#: 🔴 上溯**三层**：scripts/oneoff/x.py → oneoff → scripts → 仓库根
REPO_DIR = str(Path(__file__).resolve().parents[2])

html_path = Path(REPO_DIR) / "verify_v3.html"
out_path = Path(REPO_DIR) / "verify_v3_preview.png"


with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(viewport={"width": 1400, "height": 1300})
    page.goto(f"file://{html_path}")
    page.wait_for_timeout(500)
    page.screenshot(path=str(out_path), full_page=True)
    browser.close()

print(f"Wrote {out_path}")
