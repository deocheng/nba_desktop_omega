#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
crawl_br_team_pages.py
======================
忠实抓取 BR 球队页（含「注释块表格」）的原始 HTML 并解析。

为什么需要这个脚本（环境限制）：
  - 沙箱内 curl 被 Cloudflare 挡（403 "Just a moment"）。
  - WebFetch 能过 CF，但会把 BR 标准做法里的「注释块表格」
    （<table> 包在 <!-- --> 内，JS 才取消隐藏）直接丢弃 → 只回页头。
  - 因此 executives / hub / stats_basic_ranks / hof / all_star /
    leaders_career / players / opp_stats_basic_ranks 这些页，只能靠
    真实浏览器拿原始 HTML 后再解析注释块。

运行环境（必须）：
  - 用户 Mac（/Applications/Google Chrome.app 在位）
  - 项目 .venv 已装 undetected_chromedriver + bs4
    （bs4 若缺：.venv/bin/pip install bs4）

用法：
  cd /Users/deocheng/Downloads/nba_desktop_omega_mac_migrate_2026-07-13
  .venv/bin/python crawl_br_team_pages.py

输出：
  det2026_br/raw/<page>.html        原始 HTML（留底审计）
  det2026_br/<page>_<table>.csv   每张表一个 CSV（表 id 或 caption 命名）
  det2026_br/all.json               全部表汇总（便于程序化 diff）
"""
import os
import time
import json
import csv

from bs4 import BeautifulSoup, Comment
import undetected_chromedriver as uc

PROJECT = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(PROJECT, "det2026_br")
RAW = os.path.join(OUT, "raw")
os.makedirs(RAW, exist_ok=True)

# 11 个目标页（name -> url）
URLS = [
    ("2026_main", "https://www.basketball-reference.com/teams/DET/2026.html"),
    ("transactions", "https://www.basketball-reference.com/teams/DET/2026_transactions.html"),
    ("hub", "https://www.basketball-reference.com/teams/DET/"),
    ("stats_basic_ranks", "https://www.basketball-reference.com/teams/DET/stats_basic_ranks.html"),
    ("hof", "https://www.basketball-reference.com/teams/DET/hof.html"),
    ("all_star", "https://www.basketball-reference.com/teams/DET/all_star.html"),
    ("leaders_career", "https://www.basketball-reference.com/teams/DET/leaders_career.html"),
    ("opp_stats_basic_ranks", "https://www.basketball-reference.com/teams/DET/opp_stats_basic_ranks.html"),
    ("players", "https://www.basketball-reference.com/teams/DET/players.html"),
    ("coaches", "https://www.basketball-reference.com/teams/DET/coaches.html"),
    ("executives", "https://www.basketball-reference.com/teams/DET/executives.html"),
]

CF_MARKERS = ("cf-browser-verification", "Just a moment", "cf-chl", "challenge-platform")


def wait_cf(driver, timeout: int = 45) -> str:
    """轮询直到 Cloudflare 挑战页消失，返回最终 page_source。"""
    end = time.time() + timeout
    last = driver.page_source
    while time.time() < end:
        last = driver.page_source
        if any(m in last for m in CF_MARKERS):
            time.sleep(2.5)
            continue
        return last
    return last


def get_html(driver, url: str) -> str:
    driver.get(url)
    time.sleep(3.0)  # 等首屏
    return wait_cf(driver)


def table_key(t) -> str:
    tid = t.get("id")
    if tid:
        return tid
    cap = t.find("caption")
    if cap and cap.get_text(strip=True):
        return cap.get_text(strip=True)
    prev = t.find_previous()
    if prev and prev.get("id"):
        return prev.get("id")
    return "table"


def table_to_rows(t):
    rows = []
    for tr in t.find_all("tr"):
        cells = [c.get_text(strip=True) for c in tr.find_all(["th", "td"])]
        if cells:
            rows.append(cells)
    return rows


def tables_from_html(html: str):
    """提取所有表格：注释块里的 + 可见的。返回 [(key, rows)]。"""
    soup = BeautifulSoup(html, "html.parser")
    out = []
    # 1) 注释块里的表格（BR 关键做法）
    for c in soup.find_all(string=lambda s: isinstance(s, Comment)):
        if "<table" in c:
            cs = BeautifulSoup(c, "html.parser")
            for t in cs.find_all("table"):
                out.append((table_key(t), table_to_rows(t)))
    # 2) 可见表格
    for t in soup.find_all("table"):
        out.append((table_key(t), table_to_rows(t)))
    return out


def safe_name(s: str) -> str:
    return "".join(ch for ch in s if ch.isalnum() or ch in "-_") or "table"


def save_csv(path: str, rows):
    if not rows:
        return
    with open(path, "w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerows(rows)


def main():
    # 真实浏览器；headless=False 便于过 CF（与项目其它 BR 爬虫一致）
    driver = uc.Chrome(version_main=149, headless=False)
    try:
        all_json = {}
        for name, url in URLS:
            print(f"[fetch] {name} <- {url}", flush=True)
            html = get_html(driver, url)
            raw_path = os.path.join(RAW, f"{name}.html")
            with open(raw_path, "w", encoding="utf-8") as f:
                f.write(html)

            tables = tables_from_html(html)
            page_out = {}
            for key, rows in tables:
                sk = safe_name(key)
                csv_path = os.path.join(OUT, f"{name}_{sk}.csv")
                save_csv(csv_path, rows)
                page_out[sk] = rows
                print(f"  table[{sk}] rows={len(rows)} -> {csv_path}", flush=True)

            all_json[name] = page_out
            time.sleep(6.0)  # CF 限速：页间停顿，避免被封

        with open(os.path.join(OUT, "all.json"), "w", encoding="utf-8") as f:
            json.dump(all_json, f, ensure_ascii=False, indent=1)
        print(f"[done] 全部表格 -> {OUT}", flush=True)
    finally:
        driver.quit()


if __name__ == "__main__":
    main()
