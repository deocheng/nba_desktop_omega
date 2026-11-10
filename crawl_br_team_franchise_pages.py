#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
crawl_br_team_franchise_pages.py
================================
以马刺(SAS)页为模板，爬取全部 30 支球队的 17 类 BR 球队 franchise 级页面，
创建/填充对应的表。严格遵循「爬虫铁律」：

  铁律① 原始页必落盘  —— 抓到 page_source 第一时间原子写到
                          raw_archive/br_teams_franchise/{slug}/{page}.html
                          （tempfile + os.replace，中途异常不留损坏文件）。
                          同时另存 {slug}/{page}.md 可读副本（纯本地 HTML→MD，
                          零线上请求；bs4 解析，含注释块内表格）。
  铁律② 缓存优先读取  —— 解析前先查本地缓存；命中即返，零线上请求。
                          未命中才 driver.get，抓到立即落盘。
  铁律③ 最大化抽取    —— 页面上每个单元格都抽出来（stat 表用
                          (row_label,data_stat,val)；list 表用
                          (row_idx,col_idx,col_header,val)），宁可多存不被用。
  + CF 熔断（common.browser.get() 已焊死 CFBreaker，零改动自动保护）
  + 限速（RATE_LIMIT_BASE_S + jitter，~7s/req，≤15 req/min 红线）
  + 数据四性·统一连贯（注入 franchise_id，NJN/BRK 等历史缩写归属同一 franchise）
  + §6 SQL 安全（execute_values + ON CONFLICT 参数化，无 f-string 拼 SQL）

页面 ↔ 表 映射（17 页 = 12 stat + 5 list）：
  ── 12 个统计表页 → team_franchise_stats（长表，table_id 标识来源页）──
    stats_basic_totals / stats_per_game_totals /
    opp_stats_basic_totals / opp_stats_per_game_totals /
    stats_basic_ranks / stats_per_game_ranks /
    opp_stats_basic_ranks / opp_stats_per_game_ranks /
    stats_basic_yr_yr / stats_per_game_yr_yr /
    opp_stats_basic_yr_yr / opp_stats_per_game_yr_yr
  ── 5 个列表页 → 各一张通用网格捕获表（table_seq,row_idx,col_idx,col_header,val）──
    players   → team_franchise_players
    numbers   → team_franchise_numbers
    head2head → team_franchise_head2head
    hof       → team_franchise_hof
    all_star  → team_franchise_all_star

URL 形态（franchise 级，无赛季）：
    https://www.basketball-reference.com/teams/{slug}/{page}.html

30 支现役队 BR slug（franchise 历史页用当前 slug，已含 NJN→BRK 等归并）：
    ATL BOS BRK CHI CHO CLE DAL DEN DET GSW HOU IND LAC LAL MEM MIA MIL
    MIN NOP NYK OKC ORL PHI PHO POR SAC SAS TOR UTA WAS

运行（纯 HTTP 抓取，经 curl_cffi impersonate chrome124，无需 CDP Chrome）：
    .venv/bin/python crawl_br_team_franchise_pages.py --team SAS --dry-run
    .venv/bin/python crawl_br_team_franchise_pages.py --team SAS          # 试点
    .venv/bin/python crawl_br_team_franchise_pages.py --all               # 全量 30×17
    .venv/bin/python crawl_br_team_franchise_pages.py --all --offline     # 仅本地缓存重解析（零线上）
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import random
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import psycopg2
import psycopg2.extras
from bs4 import BeautifulSoup, Comment

# ── 项目根入 sys.path，使 import common.* 可解析 ──
PROJECT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT)

from common.br_team_page import (  # noqa: E402
    CF_MARKERS,
    DB_CONFIG,
    NOT_FOUND_MARKERS,
    RATE_LIMIT_BASE_S,
    RATE_LIMIT_JITTER_S,
)
from common.cf_breaker import CFBreaker  # noqa: E402

# ── 纯 HTTP 抓取（系统 curl + 浏览器 UA，无需 CDP Chrome）──
# 实测：BR franchise 页对「系统 curl + 浏览器 UA」稳定返回 200；而
#   curl_cffi 的 chrome124 指纹反被 CF 识别（6094B 挑战页）、
#   Python requests 会读超时。故统一走系统 curl。先清代理环境变量，
# 避免 shell 里的 HTTP_PROXY 把 BR 请求代理走（项目出站须直连）。
for _pv in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy",
            "ALL_PROXY", "all_proxy"):
    os.environ.pop(_pv, None)

_BROWSER_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
               "(KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36")


def _curl_get(url: str) -> str:
    """系统 curl 直连抓取（--noproxy '*' + 浏览器 UA），返回响应文本。"""
    r = subprocess.run(
        ["curl", "--noproxy", "*", "-s", "-L", "--max-time", "40",
         "-A", _BROWSER_UA, url],
        capture_output=True, timeout=50,
    )
    return r.stdout.decode("utf-8", errors="replace")

# 熔断器（CF 撞墙→冷却→自恢复）：curl 通道也挂同一权威机制，撞墙不再空转。
_BREAKER = CFBreaker()
# 单页最多尝试次数（撞墙经熔断器退避/冷却后重试，仍墙则跳过该页，下一轮再补）
_CF_MAX_ATTEMPTS = int(os.environ.get("CF_MAX_ATTEMPTS", "4"))

logger = logging.getLogger("br_team_franchise")
if not logging.getLogger().handlers:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

# ── 30 支现役队 BR franchise slug（franchise 历史页权威集）──
TEAMS: List[str] = [
    "ATL", "BOS", "BRK", "CHI", "CHO", "CLE", "DAL", "DEN", "DET", "GSW",
    "HOU", "IND", "LAC", "LAL", "MEM", "MIA", "MIL", "MIN", "NOP", "NYK",
    "OKC", "ORL", "PHI", "PHO", "POR", "SAC", "SAS", "TOR", "UTA", "WAS",
]

# ── 17 页定义（page 名 ↔ 目标表）──
STAT_PAGES: List[str] = [
    "stats_basic_totals", "stats_per_game_totals",
    "opp_stats_basic_totals", "opp_stats_per_game_totals",
    "stats_basic_ranks", "stats_per_game_ranks",
    "opp_stats_basic_ranks", "opp_stats_per_game_ranks",
    "stats_basic_yr_yr", "stats_per_game_yr_yr",
    "opp_stats_basic_yr_yr", "opp_stats_per_game_yr_yr",
]
LIST_PAGES: Dict[str, str] = {  # page -> table
    "players": "team_franchise_players",
    "numbers": "team_franchise_numbers",
    "head2head": "team_franchise_head2head",
    "hof": "team_franchise_hof",
    "all_star": "team_franchise_all_star",
}
ALL_PAGES: List[str] = STAT_PAGES + list(LIST_PAGES.keys()) + ["index"]  # index=主页/teams/{slug}/

RAW = os.path.join(PROJECT, "raw_archive", "br_teams_franchise")
os.makedirs(RAW, exist_ok=True)


# ─────────────────────────────────────────────────────────────────────────
# HTML → 表格抽取（含 BR 注释块表格，JS 才取消隐藏）
# ─────────────────────────────────────────────────────────────────────────
def extract_tables(html: str) -> List[Tuple[str, List[List[dict]]]]:
    """返回 [(table_id, rows)]；rows 中每个 cell = {tag, data_stat, text}。

    同时扫描可见表格与注释块内表格（BR 关键做法：核心表包在 <!-- --> 内）。
    """
    soup = BeautifulSoup(html, "html.parser")
    out: List[Tuple[str, List[List[dict]]]] = []

    def _collect(soup_root):
        for t in soup_root.find_all("table"):
            tid = t.get("id") or ""
            rows: List[List[dict]] = []
            for tr in t.find_all("tr"):
                cells = []
                for cell in tr.find_all(["th", "td"]):
                    cells.append({
                        "tag": cell.name,
                        # BR 用连字符属性 data-stat（非下划线），此处务必用连字符
                        "data_stat": cell.get("data-stat", "") or "",
                        "text": cell.get_text(strip=True),
                    })
                if cells:
                    rows.append(cells)
            if rows:
                out.append((tid, rows))

    # 1) 注释块里的表格
    for c in soup.find_all(string=lambda s: isinstance(s, Comment)):
        if "<table" in c:
            _collect(BeautifulSoup(c, "html.parser"))
    # 2) 可见表格
    _collect(soup)
    return out


def parse_stat_table(rows: List[List[dict]]) -> List[Tuple[str, str, str]]:
    """stat 表 → [(row_label, data_stat, val)]。

    每行首个 cell 作 row_label；其后的带 data_stat 的 cell 作 (data_stat, val)。
    全 th 的行（表头）跳过。
    """
    out: List[Tuple[str, str, str]] = []
    for row in rows:
        if not row:
            continue
        if all(c["tag"] == "th" for c in row):  # 表头行
            continue
        label = row[0]["text"]
        if not label:
            continue
        for c in row[1:]:
            ds = c["data_stat"]
            # 跳过 BR 的占位/空列：data-stat="foo" 是 BR 用于分隔统计组群的
            # 空列（header 里可见 2 个 foo 空 th），无实际数据，绝不入库。
            if ds and ds != "foo":
                out.append((label, ds, c["text"]))
    return out


def parse_grid_table(rows: List[List[dict]]) -> List[Tuple[int, int, Optional[str], str]]:
    """list 表 → [(row_idx, col_idx, col_header, val)]（通用网格，零结构假设）。

    表头 = 单元格最多的「全 th 行」：BR 多级/重复表头把最细列名行做成列数最多的一行
    （players 页 30 列列名 vs 4 列组头；长表每 20 行重复一次表头，各页列名一致，
    取第一处即可）。所有全 th 行（组头+列名+重复表头）一律跳过，只取数据行。
    """
    if not rows:
        return []
    header_idx = -1
    best = -1
    for i, row in enumerate(rows):
        if row and all(c["tag"] == "th" for c in row):
            if len(row) > best:
                best = len(row)
                header_idx = i
    if header_idx < 0:
        header_idx = 0
    col_headers = [c["text"] for c in rows[header_idx]]
    out: List[Tuple[int, int, Optional[str], str]] = []
    for ri, row in enumerate(rows):
        if row and all(c["tag"] == "th" for c in row):  # 跳过所有表头行
            continue
        for ci, c in enumerate(row):
            ch = col_headers[ci] if ci < len(col_headers) else None
            out.append((ri, ci, ch, c["text"]))
    return out


def parse_leaderboard(html: str) -> List[Tuple[str, str, Optional[str], Optional[str]]]:
    """解析 BR「leaderboard_grid」div 模式（hof / all_star / numbers-Combinations）。

    每个 ``<div id="leaderboard_number-{key}">``：``<h4>``=key（赛季或号码），
    内部每个 ``<a href="/players/...">``=球员名+slug，可选 ``<span class="desc">``=年段。
    返回 [(key, player_name, br_slug, desc)]。
    """
    soup = BeautifulSoup(html, "html.parser")
    out: List[Tuple[str, str, Optional[str], Optional[str]]] = []
    for div in soup.find_all("div", id=lambda v: v and v.startswith("leaderboard_number-")):
        h4 = div.find("h4")
        key = h4.get_text(strip=True) if h4 else ""
        for a in div.find_all("a", href=True):
            href = a.get("href", "") or ""
            m = re.search(r"/players/[a-z]/([a-z0-9]+)", href)
            slug = m.group(1) if m else None
            name = a.get_text(strip=True)
            desc = None
            dspan = a.find("span", class_="desc") or a.find_next_sibling("span", class_="desc")
            if dspan:
                desc = dspan.get_text(strip=True)
            if name:
                out.append((key, name, slug, desc))
    return out


def parse_retired_numbers(html: str) -> List[Tuple[str, str]]:
    """解析 numbers 页「Retired or Honored Numbers」球衣链接。

    ``<a class="poptip" data-tip="球员" href="/friv/numbers.fcgi?number=NN">``
    → [(number, player_name)]。data-tip 的说明性后缀（— 之后）剥离。
    """
    soup = BeautifulSoup(html, "html.parser")
    out: List[Tuple[str, str]] = []
    for a in soup.find_all("a", class_="poptip", href=True):
        href = a.get("href", "") or ""
        m = re.search(r"number=([^&]+)", href)
        if not m:
            continue
        number = m.group(1)
        tip = (a.get("data-tip", "") or "").replace("&mdash;", "—")
        player = tip.split("—")[0].strip()
        if player:
            out.append((number, player))
    return out


# ─────────────────────────────────────────────────────────────────────────
# franchise 主页 /teams/{slug}/ 解析（第 18 类页）
#   三大块：Team Index（Year-by-Year 战绩+季后赛） / Coaches / Playoffs
# ─────────────────────────────────────────────────────────────────────────
def _to_int(s: Optional[str]) -> Optional[int]:
    s = (s or "").strip().replace(",", "")
    if not s or s == "-":
        return None
    try:
        return int(float(s))
    except ValueError:
        return None


def _to_float(s: Optional[str]) -> Optional[float]:
    s = (s or "").strip().replace("%", "").replace(",", "")
    if not s or s == "-":
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _season_end(label: Optional[str]) -> Optional[int]:
    """ "2025-26" → 2026；"1998-99" → 1999；"2026" → 2026；其余 → None。

    注意：必须以连字符**前半段**（4 位起始年）+1 求结束年，
    不能用后半段（"1998-99" 的后半 "99" 会误解析成 99）。
    """
    label = (label or "").strip()
    if not label:
        return None
    if "-" in label:
        base = label.split("-")[0].strip()
        try:
            return int(base) + 1
        except ValueError:
            pass
    try:
        return int(label)
    except ValueError:
        return None


def _split_record(cell: Optional[str]) -> Tuple[Optional[int], Optional[int], Optional[float]]:
    """ "62-20, .756" → (62, 20, 0.756)；"-"/空 → (None,None,None)。"""
    cell = (cell or "").strip()
    if not cell or cell == "-":
        return None, None, None
    parts = [p.strip() for p in cell.split(",")]
    wl = parts[0] if parts else ""
    pct = parts[1].replace("%", "").strip() if len(parts) > 1 else ""
    m = re.match(r"(\d+)\s*-\s*(\d+)", wl)
    w = int(m.group(1)) if m else None
    l = int(m.group(2)) if m else None
    p = None
    try:
        if pct:
            p = float(pct)
    except ValueError:
        p = None
    return w, l, p


def _table_headers(rows: List[List[dict]]) -> Tuple[Optional[List[str]], List[int]]:
    """取表头行（全 th 且列数最多）+ 归一化表头→列索引映射。"""
    hdr = None
    best = -1
    for r in rows:
        if r and all(c["tag"] == "th" for c in r):
            if len(r) > best:
                best = len(r)
                hdr = r
    if hdr is None:
        return None, {}
    headers = [c["text"].strip() for c in hdr]
    hn = [h.lower().replace(".", "").replace("%", "pct").replace(" ", "")
          for h in headers]
    ci = {h: i for i, h in enumerate(hn)}
    return headers, ci


def parse_landing_page(html: str
                       ) -> Tuple[List[dict], List[dict], List[dict]]:
    """解析 franchise 主页 → (index_recs, coach_recs, playoff_recs)。

    按表头列名路由（重要：Year-by-Year 战绩表自身含 'Coaches' 列，
    故 is_index 优先判定——含 season/year 即走 index，绝不能被
    'coach' 关键字劫持成独立 Coaches 累积表）：
      - 含 'season'/'year' 且含 'w'/'wlpct' → Team Index（Year-by-Year 战绩+Playoffs+Coaches 列）
      - 不含 season 且含 'coach' → 独立 Coaches 累积表（带队教练 + tenure）
      - 含 'opponent' 且含 'result' → Playoffs 明细
    列名归一（去点/去%/去空格）后匹配，容错 BR 表头微调。
    """
    tables = extract_tables(html)
    index_recs: List[dict] = []
    coach_recs: List[dict] = []
    po_recs: List[dict] = []
    for _tid, rows in tables:
        headers, ci = _table_headers(rows)
        if not headers:
            continue
        hn = list(ci.keys())
        data_rows = [r for r in rows
                     if not (r and all(c["tag"] == "th" for c in r))]
        if not data_rows:
            continue

        def _g(keywords):
            for k in keywords:
                if k in ci and ci[k] < len(data_rows[0]):
                    return data_rows[0][ci[k]]["text"].strip()
            return ""

        is_index = (
            any(h in ("season", "year") for h in hn)
            and any(h in ("w", "wlpct") for h in hn))
        is_coach = (not is_index) and any("coach" in h for h in hn)
        is_po = any("opponent" in h for h in hn) and any("result" in h for h in hn)

        if is_coach:
            for r in data_rows:
                def g(kws):
                    for k in kws:
                        if k in ci and ci[k] < len(r):
                            return r[ci[k]]["text"].strip()
                    return ""
                coach = g(["coach"])
                if not coach:
                    continue
                reg = _split_record(g(["regseason", "reg"]))
                po = _split_record(g(["playoffs"]))
                tot = _split_record(g(["total"]))
                coach_recs.append({
                    "coach_name": coach,
                    "years": g(["yrs", "years", "active"]),
                    "reg_w": reg[0], "reg_l": reg[1], "reg_wl_pct": reg[2],
                    "po_w": po[0], "po_l": po[1], "po_wl_pct": po[2],
                    "total_w": tot[0], "total_l": tot[1], "total_wl_pct": tot[2],
                })
        elif is_index:
            for r in data_rows:
                def g(kws):
                    for k in kws:
                        if k in ci and ci[k] < len(r):
                            return r[ci[k]]["text"].strip()
                    return ""
                season = _season_end(g(["season", "year"]))
                if season is None:
                    continue
                index_recs.append({
                    "season": season,
                    "lg": g(["lg"]),
                    "team_name": g(["tm", "team"]),
                    "w": _to_int(g(["w"])),
                    "l": _to_int(g(["l"])),
                    "wl_pct": _to_float(g(["wlpct", "w/lpct"])),
                    "finish": g(["finish"]),
                    "srs": _to_float(g(["srs"])),
                    "playoffs": g(["playoffs"]),
                    "coaches": g(["coaches"]),  # 每季带队教练（更替=相邻季异名/同季多行）
                })
        elif is_po:
            for r in data_rows:
                def g(kws):
                    for k in kws:
                        if k in ci and ci[k] < len(r):
                            return r[ci[k]]["text"].strip()
                    return ""
                season = _season_end(g(["season", "year"]))
                if season is None:
                    continue
                po_recs.append({
                    "season": season,
                    "opponent": g(["opponent"]),
                    "result": g(["result"]),
                })
    return index_recs, coach_recs, po_recs


# ─────────────────────────────────────────────────────────────────────────
# CDP 抓取（铁律①+②：缓存优先，未命中才线上抓并原子落盘）
# ─────────────────────────────────────────────────────────────────────────
def cache_path(slug: str, page: str) -> str:
    return os.path.join(RAW, slug, f"{page}.html")


def _is_real_html(html: str) -> bool:
    """判断 HTML 是否为真内容（非 CF 桩/空页/JS 空壳）。

    真页必有表格或 leaderboard 结构（stat 页含 <table>/data-stat；
    list 页含 leaderboard）。旧 CDP 卡 CF 时落过 316 字节空桩（空标题、零表格），
    必须识别出来当作未命中重抓，否则 cache-first 会永久跳过。

    修正（2026-08-21）：
      · CF 挑战页（含 CF_MARKERS）一律判非真，避免把挑战页当真缓存。
      · 长度 >50KB 且非 CF 的大页兜底判真——BR 真人页普遍 >50KB，
        而桩/空壳均 <1KB。此兜底覆盖 hof 等用 JS/leaderboard_grid 渲染、
        初始 HTML 无标准 table 标记的真页（如 NOP→NOH 的 hof 页 135KB
        但无 <table>/leaderboard/data-stat），避免其被误判为桩而反复重抓撞墙。
    """
    if not html or len(html) < 1024:
        return False
    low = html.lower()
    if any(mk.lower() in low for mk in CF_MARKERS):
        return False
    if ("<table" in low) or ("data-stat" in low) or ("leaderboard" in low):
        return True
    if len(html) > 50000:
        return True
    return False


# ─────────────────────────────────────────────────────────────────────────
# HTML → Markdown 副本（纯本地 bs4 解析，零线上请求；在 HTML 之外另存 .md）
# ─────────────────────────────────────────────────────────────────────────
def cache_md_path(slug: str, page: str) -> str:
    return os.path.join(RAW, slug, f"{page}.md")


def _md_cell_text(cell) -> str:
    """取单元格纯文本，管道符转斜杠避免破坏 md 表格列边界。"""
    if cell is None:
        return ""
    return cell.get_text(" ", strip=True).replace("\n", " ").replace("|", "/")


def _table_to_md(table) -> str:
    """单个 <table> → markdown 表格（首行作表头分隔）。"""
    rows = table.find_all("tr")
    out: List[str] = []
    for tr in rows:
        cells = tr.find_all(["th", "td"])
        if not cells:
            continue
        vals = [_md_cell_text(c) for c in cells]
        if all(v == "" for v in vals):
            continue  # 跳空行
        out.append("| " + " | ".join(vals) + " |")
    if not out:
        return ""
    ncol = out[0].count("|") - 1  # 首行列数
    if ncol < 1:
        return ""
    sep = "| " + " | ".join(["---"] * ncol) + " |"
    return "\n".join([out[0], sep] + out[1:]) + "\n"


def html_to_markdown(html: str) -> str:
    """把 BR franchise 页 HTML → 可读 Markdown（纯本地解析，零线上请求）。

    覆盖：主 DOM 表格 + 注释块内表格（BR 核心表包在 <!-- -->，JS 才显形）、
    列表(ul/ol)、标题(h1-h4)。脚本/样式已剔除。供「HTML 之外另存 md 副本」。
    """
    if not html:
        return ""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style"]):
        tag.decompose()
    parts: List[str] = []
    # 标题结构
    for h in soup.find_all(["h1", "h2", "h3", "h4"]):
        txt = _md_cell_text(h)
        if txt:
            level = int(h.name[1])
            parts.append(f"\n{'#' * level} {txt}\n")
    # 收集所有 table（含注释内的）
    tables = list(soup.find_all("table"))
    for c in soup.find_all(string=lambda s: isinstance(s, Comment)):
        try:
            csoup = BeautifulSoup(c, "html.parser")
            tables.extend(csoup.find_all("table"))
        except Exception:  # noqa: BLE001
            pass
    # 去重（优先 table id，无 id 用对象 id）
    seen = set()
    uniq = []
    for t in tables:
        key = t.get("id") or id(t)
        if key in seen:
            continue
        seen.add(key)
        uniq.append(t)
    if uniq:
        parts.append("\n## Tables\n")
        for i, t in enumerate(uniq, 1):
            name = t.get("id") or f"table_{i}"
            parts.append(f"\n### {name}\n")
            md = _table_to_md(t)
            if md:
                parts.append(md + "\n")
    # 列表（leaderboard 等 div 页可能无 table，但有列表）
    lists = soup.find_all(["ul", "ol"])
    if lists:
        parts.append("\n## Lists\n")
        for lst in lists:
            for li in lst.find_all("li"):
                parts.append(f"- {_md_cell_text(li)}\n")
    return "\n".join(parts).strip() + "\n"


def save_markdown(slug: str, page: str, html: str) -> None:
    """铁律①原子落盘的 MD 副本：在 HTML 之外另存一份可读 MD。

    纯本地 bs4 解析，零线上请求；tempfile + os.replace 中途异常不留损坏文件。
    MD 副本为「附加可读副本」，生成失败绝不冒泡影响爬取主流程。
    """
    md = html_to_markdown(html)
    if not md.strip():
        return
    mp = cache_md_path(slug, page)
    os.makedirs(os.path.dirname(mp), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(mp), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(md)
        os.replace(tmp, mp)
    except Exception:  # noqa: BLE001
        try:
            os.unlink(tmp)
        except Exception:  # noqa: BLE001
            pass


def _extract_redirect(html: str) -> Optional[str]:
    """BR franchise 页重定向桩检测：<meta refresh> + window.location 指向 /teams/XXX/。

    例：/teams/BRK/ → 桩指向 /teams/NJN/（篮网历史 franchise 码为 NJN）。
    返回目标队码（大写），非重定向返回 None。
    """
    low = html.lower()
    if 'http-equiv="refresh"' in low or 'window.location.href' in low:
        m = re.search(r'/teams/([A-Za-z]{2,4})/', html)
        if m:
            return m.group(1).upper()
    return None


def fetch_page(slug: str, page: str,
               offline: bool = False) -> Tuple[Optional[str], str]:
    """返回 (html_or_None, status)。status ∈ {ok, cached, cf, 404, err, miss}。

    纯 HTTP（subprocess 调系统 curl + 浏览器 UA，franchise 页可直连、无需 CDP）。
    offline=True 时只读缓存，绝不线上抓。
    撞 CF 挑战页 → 经 CFBreaker 退避/冷却后重试（自恢复），仍墙则返回 "cf"。
    BR 重定向桩（/teams/BRK/ → /teams/NJN/）→ 跟随权威 franchise 页。
    抓取结果须过 _is_real_html 校验，桩/空页不缓存、当失败重试。
    """
    if page == "index":
        url = f"https://www.basketball-reference.com/teams/{slug}/"
    else:
        url = f"https://www.basketball-reference.com/teams/{slug}/{page}.html"
    cp = cache_path(slug, page)
    # 铁律②：缓存优先读取（但须是真内容，桩文件当未命中重抓）
    if os.path.exists(cp) and os.path.getsize(cp) > 0:
        with open(cp, "r", encoding="utf-8") as fh:
            html = fh.read()
        if _is_real_html(html):
            # 命中且真内容：若 MD 副本缺失则补生成（零线上请求，符合缓存优先）
            mp = cache_md_path(slug, page)
            if not os.path.exists(mp) or os.path.getsize(mp) == 0:
                try:
                    save_markdown(slug, page, html)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("MD 副本补生成失败(忽略): %s/%s: %s", slug, page, exc)
            return html, "cached"
        logger.warning("缓存为桩文件，重抓: %s/%s", slug, page)
    if offline:
        return None, "miss"
    current = slug  # 已解析到的权威队码（随重定向更新），用于判自引用
    for _attempt in range(_CF_MAX_ATTEMPTS):
        # 限速
        time.sleep(RATE_LIMIT_BASE_S + random.uniform(0, RATE_LIMIT_JITTER_S))
        try:
            html = _curl_get(url)
        except Exception as exc:  # noqa: BLE001
            logger.warning("抓取失败 %s/%s: %s", slug, page, exc)
            return None, "err"
        if not html:
            return None, "err"
        low = html.lower()
        if any(mk.lower() in low for mk in CF_MARKERS):
            dec = _BREAKER.on_breach()
            logger.warning("CF 挑战页，跳过/重试: %s/%s（决策=%s）", slug, page, dec)
            if dec == "giveup":
                return None, "cf"
            continue  # 熔断器已退避/冷却，重试
        # BR 重定向桩：跟随权威 franchise 页（内容落原 slug 缓存，保持队属一致）。
        # 关键：只在本页指向「不同于当前已解析队码」时才跟随——否则 NJN 真页
        # 里含自引用 /teams/NJN/ 会被反复误判成重定向，陷入死循环到不了缓存。
        canon = _extract_redirect(html)
        if canon and canon != current.upper():
            logger.info("重定向跟随: %s/%s → %s", slug, page, canon)
            current = canon
            if page == "index":
                url = f"https://www.basketball-reference.com/teams/{canon}/"
            else:
                url = f"https://www.basketball-reference.com/teams/{canon}/{page}.html"
            continue
        if any(mk.lower() in low for mk in NOT_FOUND_MARKERS):
            logger.warning("BR 404，隔离: %s/%s", slug, page)
            return None, "404"
        # 真内容校验：桩/空页（如非 CF 的空响应）不缓存，当失败重试
        if not _is_real_html(html):
            logger.warning("非真内容响应(桩/空)，重试: %s/%s", slug, page)
            dec = _BREAKER.on_breach()
            if dec == "giveup":
                return None, "cf"
            continue
        # 成功：重置熔断计数
        _BREAKER.on_success()
        # 铁律①：原子落盘
        os.makedirs(os.path.dirname(cp), exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(cp), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(html)
            os.replace(tmp, cp)
            # 铁律①补充：HTML 之外另存 MD 副本（纯本地 bs4 解析，零线上请求）
            try:
                save_markdown(slug, page, html)
            except Exception as exc:  # noqa: BLE001
                logger.warning("MD 副本生成失败(忽略): %s/%s: %s", slug, page, exc)
        except Exception:
            try:
                os.unlink(tmp)
            except Exception:
                pass
            raise
        return html, "ok"
    return None, "cf"


# ─────────────────────────────────────────────────────────────────────────
# 参数化入库（§6：execute_values + ON CONFLICT，注入 franchise_id）
# ─────────────────────────────────────────────────────────────────────────
def build_franchise_map(conn) -> Dict[str, Optional[int]]:
    cur = conn.cursor()
    cur.execute(
        "SELECT DISTINCT abbreviation, franchise_id FROM team_summaries "
        "WHERE franchise_id IS NOT NULL")
    m = {ab: fid for ab, fid in cur.fetchall()}
    cur.close()
    return m


def upsert_rows(conn, table: str, rows: List[dict],
                conflict_cols: Tuple[str, ...]) -> int:
    if not rows:
        return 0
    # 去重：同一冲突键在单批次出现多次会触发
    # "ON CONFLICT DO UPDATE command cannot affect row a second time"。
    # 冲突键即唯一约束，重复即同一逻辑单元格 → 保留最后一次，幂等入库。
    _dedup: dict = {}
    for r in rows:
        _dedup[tuple(r.get(c) for c in conflict_cols)] = r
    rows = list(_dedup.values())
    cols: List[str] = []
    for r in rows:
        for k in r.keys():
            if k not in cols:
                cols.append(k)
    update_cols = [c for c in cols if c not in conflict_cols]
    col_sql = ", ".join(cols)
    placeholders = "%s"
    if update_cols:
        upd_sql = ", ".join([f"{c}=EXCLUDED.{c}" for c in update_cols])
        conflict_sql = (f"ON CONFLICT ({', '.join(conflict_cols)}) "
                        f"DO UPDATE SET {upd_sql}")
    else:
        conflict_sql = f"ON CONFLICT ({', '.join(conflict_cols)}) DO NOTHING"
    sql = (f"INSERT INTO {table} ({col_sql}) VALUES {placeholders} "
           f"{conflict_sql}")
    data = [tuple(r.get(c) for c in cols) for r in rows]
    cur = conn.cursor()
    psycopg2.extras.execute_values(cur, sql, data, page_size=1000)
    cur.close()
    return len(data)


# ─────────────────────────────────────────────────────────────────────────
# 单 (slug, page) 处理
# ─────────────────────────────────────────────────────────────────────────
def process_one(conn, slug: str, page: str,
                fmap: Dict[str, Optional[int]], offline: bool = False
                ) -> Tuple[int, str]:
    """返回 (落库行数, fetch状态)。fetch状态∈{ok,cached,cf,404,err,miss}。

    cf/err/miss/404 → 行数 0，且状态非 ok，供 run() 判定是否需重试。
    """
    fid = fmap.get(slug)
    html, status = fetch_page(slug, page, offline)
    if status in ("cf", "404", "err", "miss") or html is None:
        return 0, status
    n = 0
    if page in ("hof", "all_star"):
        # div：leaderboard（赛季 → 球员）
        table = LIST_PAGES[page]
        conflict = ("team_abbr", "season", "player_name")
        recs = [{
            "team_abbr": slug,
            "franchise_id": fid,
            "season": key,
            "player_name": name,
            "br_slug": slug_,  # noqa: F821
        } for (key, name, slug_, desc) in parse_leaderboard(html)]
        n = upsert_rows(conn, table, recs, conflict)
    elif page == "numbers":
        # div：retired（球衣链接） + combinations（leaderboard）
        table = LIST_PAGES[page]
        conflict = ("team_abbr", "section", "number", "player_name")
        recs = []
        for (number, player) in parse_retired_numbers(html):
            recs.append({"team_abbr": slug, "franchise_id": fid,
                         "section": "retired", "number": number,
                         "player_name": player, "br_slug": None, "years": None})
        for (number, player, slug_, years) in parse_leaderboard(html):
            recs.append({"team_abbr": slug, "franchise_id": fid,
                         "section": "combinations", "number": number,
                         "player_name": player, "br_slug": slug_, "years": years})
        n = upsert_rows(conn, table, recs, conflict)
    elif page == "index":
        # franchise 主页 /teams/{slug}/：Index(战绩+季后赛) + Coaches + Playoffs
        idx_recs, coach_recs, po_recs = parse_landing_page(html)
        n = 0
        for rec in idx_recs:
            rec.update({"team_abbr": slug, "franchise_id": fid})
            n += upsert_rows(conn, "team_franchise_index", [rec],
                             ("team_abbr", "season"))
        for rec in coach_recs:
            rec.update({"team_abbr": slug, "franchise_id": fid})
            n += upsert_rows(conn, "team_franchise_coaches", [rec],
                             ("team_abbr", "coach_name", "years"))
        for rec in po_recs:
            rec.update({"team_abbr": slug, "franchise_id": fid})
            n += upsert_rows(conn, "team_franchise_playoffs", [rec],
                             ("team_abbr", "season", "opponent"))
        logger.info("  [index] %s → index=%d coaches=%d playoffs=%d",
                    slug, len(idx_recs), len(coach_recs), len(po_recs))
    elif page in LIST_PAGES:
        # 真表格页（players / head2head）→ 通用网格捕获
        table = LIST_PAGES[page]
        conflict = ("team_abbr", "table_seq", "row_idx", "col_idx")
        for seq, (tid, rows) in enumerate(extract_tables(html)):
            grid = parse_grid_table(rows)
            recs = [{
                "team_abbr": slug,
                "franchise_id": fid,
                "table_seq": seq,
                "row_idx": ri,
                "col_idx": ci,
                "col_header": ch,
                "val": v,
            } for (ri, ci, ch, v) in grid]
            n += upsert_rows(conn, table, recs, conflict)
    else:  # stat 页 → team_franchise_stats
        table = "team_franchise_stats"
        conflict = ("team_abbr", "table_id", "table_seq", "row_label", "data_stat")
        for seq, (tid, rows) in enumerate(extract_tables(html)):
            parsed = parse_stat_table(rows)
            recs = [{
                "team_abbr": slug,
                "franchise_id": fid,
                "table_id": page,
                "table_seq": seq,
                "row_label": label,
                "data_stat": ds,
                "val": v,
            } for (label, ds, v) in parsed]
            n += upsert_rows(conn, table, recs, conflict)
    conn.commit()
    return n, "ok"


# ─────────────────────────────────────────────────────────────────────────
# 主流程（含末轮 gap 重试：撞 CF 墙的页不静默丢弃，冷却恢复后补抓）
# ─────────────────────────────────────────────────────────────────────────
def run(targets: List[str], pages: List[str], offline: bool = False,
        max_retry_passes: int = 8) -> None:
    conn = psycopg2.connect(**DB_CONFIG)
    fmap = build_franchise_map(conn)
    total = 0
    pending: List[Tuple[str, str]] = [(s, p) for s in targets for p in pages]
    try:
        for rpass in range(1 + max_retry_passes):
            if not pending:
                break
            if rpass > 0:
                # 重试轮：给 CF 熔断器恢复窗口（撞墙已触发冷却，静等其自恢复）
                wait = int(os.environ.get("GAP_RETRY_WAIT_S", "420"))
                logger.info("=== 缺口重试轮 #%d：%d 个 (队,页)，冷却恢复等待 %ds ===",
                            rpass, len(pending), wait)
                time.sleep(wait)
            failed: List[Tuple[str, str]] = []
            for slug, page in pending:
                try:
                    n, status = process_one(conn, slug, page, fmap, offline)
                    total += n
                    if status in ("cf", "err", "miss", "404"):
                        failed.append((slug, page))
                        # cf/err 需重试；miss(offline) / 404 不再重试
                        if status in ("miss", "404"):
                            logger.warning("  [放弃] %s/%s 状态=%s", slug, page, status)
                            failed.remove((slug, page))
                    else:
                        logger.info("  [ok] %s/%s → %d 行", slug, page, n)
                except Exception as exc:  # noqa: BLE001
                    logger.error("  [失败] %s/%s: %s", slug, page, exc)
                    conn.rollback()
                    failed.append((slug, page))
            pending = failed
            if not pending:
                logger.info("缺口重试轮 #%d 后已清零", rpass)
                break
    finally:
        conn.close()
    logger.info("完成：累计落库 %d 行；最终残留缺口 %d 个 (队,页)",
                total, len(pending))


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--team", type=str, default=None,
                   help="只爬指定队（BR slug，如 SAS），用于试点")
    p.add_argument("--all", action="store_true", help="爬全部 30 队")
    p.add_argument("--pages", type=str, default=None,
                   help="限定页（逗号分隔，如 players,hof）；默认全部 17 页")
    p.add_argument("--offline", action="store_true",
                   help="仅从本地缓存解析入库，绝不线上抓（缓存缺失的页跳过）")
    p.add_argument("--dry-run", action="store_true",
                   help="只打印 (slug,page) 计划，不取浏览器、不写库")
    args = p.parse_args()

    if args.team:
        targets = [args.team.upper()]
    elif args.all:
        targets = TEAMS
    else:
        print("需指定 --team <slug> 或 --all")
        return

    pages = ALL_PAGES
    if args.pages:
        pages = [p.strip() for p in args.pages.split(",") if p.strip()]

    if args.dry_run:
        for s in targets:
            for pg in pages:
                logger.info("[dry-run] 计划抓取 %s/%s", s, pg)
        logger.info("计划总数：%d 队 × %d 页 = %d",
                    len(targets), len(pages), len(targets) * len(pages))
        return

    logger.info("启动：%d 队 × %d 页 = %d 目标（offline=%s）",
                len(targets), len(pages), len(targets) * len(pages), args.offline)
    run(targets, pages, args.offline)


if __name__ == "__main__":
    main()
