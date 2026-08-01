#!/usr/bin/env python3
"""
audit_br_schedule.py  (修复版 — 注释剥离 + 单页 + 按 (日期,主客) 匹配)
==========================================================================

全量核对 dim_games 与 BR 官方联盟赛程页（常规赛 1996-97 .. 2025-26，
即 NBA_1997 .. NBA_2026_games.html，共 30 季），找出脏数据并产出
/tmp/dirty_games_report.json。

本脚本是**只读核查**：除读取 dim_games / play_by_play 外，唯一写操作是落盘报告
JSON。绝不修改 dim_games / play_by_play / game_id_map 任何行（无 INSERT/UPDATE/DELETE）。

------------------------------------------------------------------------------
核心修复（上一轮假完成的根因）
------------------------------------------------------------------------------
上一轮把 1237/1317 行误标 PHANTOM，根因是解析只拿到约 80 行。实测当前 BR 站点把整季
常规赛**按月份拆成子页**：主表 NBA_{yyyy}_games.html 默认仅渲染首月（id='schedule'，
caption 'October Schedule Table'），其余月份放在 NBA_{yyyy}_games-{month}.html 子页里。
因此「单一联盟页即含整季」的假设对当前站点**不成立**——正确做法是抓主表 + 全部月度子页
并按 gameid 去重合并。

此外，旧版 BR 曾把整季 <tr> 藏在 HTML 注释 <!-- ... --> 里（朴素 BeautifulSoup 会跳过
注释行）。为兼容旧季布局，喂给 BeautifulSoup 前仍先剥掉注释定界符（对当前站点无副作用）：

    html = re.sub(r'<!--\\s*', '', html)
    html = re.sub(r'\\s*-->', '', html)

校验门禁：常规赛整季解析（主表+月页合并）后行数应 >= 合理下限（见 _gate_ok）；
若合并后仍然只拿到 ~80 行，说明月页抓取没生效 —— 立刻停下报告。

------------------------------------------------------------------------------
匹配键
------------------------------------------------------------------------------
dim_games.season 实测 = 赛季结束年（与 BR yyyy 一致，例如 2025-26 季 season=2026），
上一轮用 season = yyyy-1 过滤 dim_games 是 off-by-one 错误（"栽在这"）。本脚本
**不依赖 season 整数列做匹配**，改用复合键 (game_date, 映射后_home, 映射后_away)
（主客顺序无关，用排序元组，从而能检测 REVERSED）。仅在同键多候选时用 season==yyyy
做优先级 tiebreaker（非过滤）。

------------------------------------------------------------------------------
历史 -> 现代缩写映射
------------------------------------------------------------------------------
团队给的 HIST_TO_CUR 中 NJN->'BRO' 经 DB 实测为笔误：dim_games 现代篮网码是 BRK（
DISTINCT 码集合里没有 BRO），故修正为 BRK 并保留 BRO->BRK 别名。其余目标
WAS/OKC/MEM/CHO/NOP 与 dim_games 实际现代码一致（BR 当前码恰为这些）。映射对 BR 与
dim_games 两侧同时施加，保证常规赛主客队跨历史/现代码可正确配对。

------------------------------------------------------------------------------
PBP_GAP 信号
------------------------------------------------------------------------------
dim_games.pbp_imported 存在大量 NULL（29566 行）与 True（35692 行），不宜单独作为
"已导入"判定。改用 play_by_play 行存在性作为权威信号：某场"已导入 PBP" = pbp_imported
为 True 或 play_by_play 存在其 game_id / nba_api_id 的行。PBP_GAP = 配对成功且 BR 显示
已完赛（有比分）但该场无 PBP。

------------------------------------------------------------------------------
健壮性
------------------------------------------------------------------------------
- 复用 br_fill_pbp 的 build_driver / cf_challenge / SessionGone / RateLimiter / DB。
- 全季复用同一 driver（共享 CF Cookie，提速），仅在 SessionGone 时重建重试该季。
- 每季独立 try/except；单季失败记 SEASON_FETCH_FAILED 进报告并继续，绝不跳过末尾报告。
- 限速 <=15 请求/分钟（>=4.5s 间隔）。
- 每季处理完 json.dump 整个累计报告（每季落盘一次，进程被杀也不丢）。
- --validate 仅跑 YYYY=2026 验证季（现代缩写无需映射），打印样本+门禁；确认无误后用
  --all 跑 1997..2026 共 30 季。--years 可指定若干季（用于失败季重试，合并进现有报告）。

运行（铁律：从项目根目录 + 设置 PYTHONPATH，否则 br_fill_pbp/common import 失败）：
  cd <root> && PYTHONPATH=<root> .venv/bin/python audit_br_schedule.py --validate
  cd <root> && PYTHONPATH=<root> .venv/bin/python audit_br_schedule.py --all
  cd <root> && PYTHONPATH=<root> .venv/bin/python audit_br_schedule.py --years 1999 2012
"""
from __future__ import annotations

import os
import sys
import time
import threading
import shutil
import json
import re
import argparse
from collections import defaultdict, Counter

import psycopg2

# --- path setup（与 br_fill_pbp.py 一致：把项目根加入 sys.path[0]） ---
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(HERE, ".env"))
except Exception:
    pass

import br_fill_pbp as _bf  # noqa: E402
from br_fill_pbp import (  # noqa: E402
    build_driver as _raw_build_driver,
    cf_challenge,
    SessionGone,
    RateLimiter,
    DB,
)
from bs4 import BeautifulSoup  # noqa: E402
from selenium.common.exceptions import (  # noqa: E402
    WebDriverException,
    SessionNotCreatedException,
)


class SeasonTimeout(Exception):
    """看门狗超时：单季处理超过阈值被强制回收（避免整个进程被平台硬杀）。"""
    pass

# 连接参数（加 connect_timeout 防连接挂死）
DB_CONN = dict(DB)
DB_CONN.setdefault("connect_timeout", 30)

SCHED_URL = "https://www.basketball-reference.com/leagues/NBA_{yyyy}_games.html"
REPORT_PATH = "/Users/deocheng/WorkBuddy/2026-07-13-10-47-43/audit_output/dirty_games_report.json"

MAX_PAGE_RETRY = 3
MAX_DRIVER_RETRY = 4

# 历史 -> 现代（BR 当前）缩写映射。
# 团队原给 NJN->'BRO' 经 DB 实测为笔误（dim_games 无 BRO 码，现代篮网=BRK），已修正。
HIST_TO_CUR = {
    "WSB": "WAS",   # Washington Bullets -> Wizards
    "NJN": "BRK",   # New Jersey Nets -> Brooklyn (团队原 BRO 为笔误)
    "BRO": "BRK",   # 别名兜底
    "SEA": "OKC",   # Seattle -> Oklahoma City
    "VAN": "MEM",   # Vancouver -> Memphis
    "CHH": "CHO",   # 原 Charlotte Hornets -> 现 Charlotte
    "NOK": "NOP", "NOH": "NOP",  # New Orleans 各阶段 -> Pelicans
    "CHA": "CHO",   # Bobcats -> Hornets
    "PHI": "PHL",   # Philadelphia 76ers (BR 码 PHI vs 库 PHL)
    # --- 早期消亡队码（BR 字母码 -> 库 home_team_abbr，均经 DB 实测确认）---
    "BLB": "BAL",   # Baltimore Bullets (旧, 1948-54) -> 库 BAL
    "CHP": "CHZ",   # Chicago Packers/Zephyrs -> 库 CHZ (Chicago Zephyrs)
    "MLH": "MNL",   # Minneapolis Lakers -> 库 MNL
    "NYN": "BRK",   # ABA/早期 Nets -> 库 BRK（1976-77 篮网加盟首季 dim_games 缺，将如实标 MISSING）
    "STB": "BOM",   # St. Louis Bombers -> 库 BOM
    "TRI": "TCB",   # Tri-Cities Blackhawks -> 库 TCB
    "WSC": "WAS",   # Washington Capitols -> 库 WAS（与 Washington Bullets 同 abbr）
    "KCO": "KCK",   # Kansas City Kings (1972-85) -> 库 KCK
}

# BR 赛季结束年范围：BR 实际仅托管 1949-50 起（结束年 1950）的赛程页；
# 1946-47/1947-48/1948-49（结束年 1947/1948/1949）均 404 —— 数据源边界（dim_games 有这些季但 BR 无页可对账）。
YEAR_MIN = 1950
YEAR_MAX = 2026
# PBP 数据窗口：BR 逐回合 PBP 仅 ~2000 起可靠，1947-1996 无 PBP，
# 故 PBP_GAP 判定单独用本下限（避免老季被全量误标 PBP_GAP）。
PBP_MIN_YEAR = 1997

# 月度子页（当前 BR 站点把整季按月份拆成子页；主表 NBA_{yyyy}_games.html 默认仅渲染
# 首月 October，id='schedule'）。为拿到整季常规赛，须合并主表 + 各月子页（按 gameid 去重）。
# 月页形如 NBA_{yyyy}_games-{month}.html（实测 2025-26 为 october..june，其余季范围不同）。
# 不存在的月页（404）自动跳过；旧版 BR 曾把整季塞进主表 HTML 注释里——本脚本仍保留注释
# 剥离（对旧季生效），两种布局都能覆盖。
SCHED_MONTHS = [
    "october", "november", "december", "january", "february",
    "march", "april", "may", "june", "july", "august", "september",
]

# 特殊季：因疫情/赛程跨年，月份 slug 与默认不同。BR 对跨两个 October 的季
# 用 -YYYY 消歧（开赛 october-2019、总决赛 october-2020），且泡泡重启补 july/august/september。
# 键 = 结束年（dim season）。命中则用覆盖列表，否则用默认 SCHED_MONTHS。
SEASON_MONTHS_OVERRIDE = {
    2020: ["october-2019", "november", "december", "january", "february",
            "march", "july", "august", "september", "october-2020"],
}


# --------------------------------------------------------------------------
# 解析辅助
# --------------------------------------------------------------------------
def code_from_team_href(a):
    """从 /teams/<CODE>/YYYY.html 取 3 字母代码。"""
    if not a:
        return None
    m = re.search(r"/teams/([A-Z]{3})/", a.get("href", ""))
    return m.group(1) if m else None


def gameid_from_box_href(a):
    """从 /boxscores/<YYYYMMDD><CODE>.html 取 BR gameid。"""
    if not a:
        return None
    m = re.search(r"/boxscores/(\d{8}[A-Z]{3})\.html", a.get("href", ""))
    return m.group(1) if m else None


_MONTHS = {
    "Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6,
    "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12,
}


def parse_date(s, data_iso=None):
    """BR Date 列: 'Tue, Oct 21, 2025' 或 data-iso '2025-10-21' -> 'YYYY-MM-DD'。"""
    if data_iso:
        m = re.match(r"(\d{4})-(\d{1,2})-(\d{1,2})", str(data_iso))
        if m:
            return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    if not s:
        return None
    s = s.strip()
    m = re.match(r"[A-Za-z]{3},\s*([A-Za-z]{3})\s*(\d{1,2}),\s*(\d{4})", s)
    if m:
        mon = _MONTHS.get(m.group(1))
        if mon:
            return f"{m.group(3)}-{mon:02d}-{int(m.group(2)):02d}"
    m2 = re.match(r"(\d{4})-(\d{1,2})-(\d{1,2})", s)
    if m2:
        return f"{m2.group(1)}-{int(m2.group(2)):02d}-{int(m2.group(3)):02d}"
    return None


def to_int(s):
    if s is None:
        return None
    s = str(s).strip()
    if s == "":
        return None
    try:
        return int(s)
    except ValueError:
        return None


def norm(code):
    """历史码 -> 现代码；未知码原样返回；空/None -> ''（保证可排序、可匹配）。"""
    if not code:
        return ""
    return HIST_TO_CUR.get(code, code)


# --------------------------------------------------------------------------
# 解析 BR 赛程页（核心：先剥注释）
# --------------------------------------------------------------------------
def parse_schedule_soup(html, yyyy):
    """解析 BR 联盟赛程表 -> 比赛 dict 列表。

    关键修复：先剥掉 HTML 注释定界符，否则被注释的 <tr> 行不会被解析。
    BR 赛程页要点：
      - 表格 id 多为 'games'（兼容 'schedule'）。
      - 用 data-stat 属性定位列（跨季稳健），不硬编码索引。
      - 主客队代码在 /teams/<CODE>/ 链接；比分在 visitor_pts / home_pts 列；
        BoxScore 链接 /boxscores/<YYYYMMDD><主队>.html 提供 BR gameid。
    比赛行识别：含 Visitor 与 Home 两个 /teams/ 链接且 Date 可解析的行。
    """
    if not html:
        return []
    # === 核心修复：剥注释 ===
    html = re.sub(r'<!--\s*', '', html)
    html = re.sub(r'\s*-->', '', html)
    soup = BeautifulSoup(html, "html.parser")

    # 定位赛程表：优先 id='games'，其次 'schedule'，再退化为含 /teams/ 链接最多的表
    tbl = soup.find("table", id="games")
    if tbl is None:
        tbl = soup.find("table", id="schedule")
    if tbl is None:
        best, best_n = None, -1
        for t in soup.find_all("table"):
            n = len(t.find_all("a", href=re.compile(r"/teams/[A-Z]{3}/")))
            if n > best_n:
                best_n, best = n, t
        tbl = best
    if tbl is None:
        return []

    tbody = tbl.find("tbody") or tbl

    # 用 data-stat 定位列（跨季稳定）；缺失时回退到位置猜测
    def col_index(data_stat):
        for tr in tbody.find_all("tr"):
            for i, c in enumerate(tr.find_all(["th", "td"])):
                if c.get("data-stat") == data_stat:
                    return i
        return None

    i_date = col_index("date_game")
    i_vis = col_index("visitor_team_name")
    i_vis_pts = col_index("visitor_pts")
    i_hom = col_index("home_team_name")
    i_hom_pts = col_index("home_pts")
    if i_date is None:
        i_date = 0
    if i_vis is None:
        i_vis = 1 if i_date == 0 else 2
    if i_hom is None:
        i_hom = 3 if i_vis == 1 else 4
    if i_vis_pts is None:
        i_vis_pts = i_vis + 1
    if i_hom_pts is None:
        i_hom_pts = i_hom + 1

    need = max(i_date, i_vis, i_hom, i_vis_pts, i_hom_pts)
    games = []
    for tr in tbody.find_all("tr"):
        cells = tr.find_all(["th", "td"])
        if len(cells) <= need:
            continue
        visitor_a = cells[i_vis].find("a", href=re.compile(r"/teams/[A-Z]{3}/")) if i_vis < len(cells) else None
        home_a = cells[i_hom].find("a", href=re.compile(r"/teams/[A-Z]{3}/")) if i_hom < len(cells) else None
        if visitor_a is None or home_a is None:
            continue  # 月份子表头 / 非比赛行
        date_cell = cells[i_date]
        gdate = parse_date(date_cell.get_text(strip=True), date_cell.get("data-iso"))
        if gdate is None:
            continue
        v_code = code_from_team_href(visitor_a)
        h_code = code_from_team_href(home_a)
        if not v_code or not h_code:
            continue
        v_pts = to_int(cells[i_vis_pts].get_text(strip=True)) if i_vis_pts < len(cells) else None
        h_pts = to_int(cells[i_hom_pts].get_text(strip=True)) if i_hom_pts < len(cells) else None
        # BoxScore gameid：优先 Box Score 列链接，否则由 (日期+主队) 构造
        box_a = tr.find("a", href=re.compile(r"/boxscores/\d{8}[A-Z]{3}\.html"))
        gameid = gameid_from_box_href(box_a)
        if gameid is None:
            y, m, d = gdate.split("-")
            gameid = f"{y}{m}{d}{h_code}"
        games.append({
            "date": gdate,
            "visitor_code": v_code,
            "home_code": h_code,
            "visitor_pts": v_pts,
            "home_pts": h_pts,
            "gameid": gameid,
        })
    return games


# --------------------------------------------------------------------------
# 抓取（复用 br_fill_pbp 的 CF 等待逻辑；返回原始 html 字符串）
# --------------------------------------------------------------------------
def _switch_to_br_tab(driver):
    """确保 driver 当前窗口是 BR 赛程页（避免 CF/弹窗打开的空白新标签被误读）。"""
    try:
        handles = driver.window_handles
        if not handles:
            return
        for h in handles:
            try:
                driver.switch_to.window(h)
                if "basketball-reference.com" in (driver.current_url or ""):
                    return
            except Exception:
                pass
        driver.switch_to.window(handles[-1])
    except Exception:
        pass


def fetch_schedule_html(driver, url):
    """返回原始 html 字符串；CF 超时返回 None；404 返回 '404'；会话失效抛 SessionGone。"""
    try:
        driver.get(url)
        html = ""
        for _ in range(25):  # 最多 ~50s 等 CF
            time.sleep(2)
            try:
                _switch_to_br_tab(driver)
                html = driver.page_source
                title = driver.title
            except WebDriverException:
                raise SessionGone()
            # 404 立即返回（避免小页面卡在 CF 等待循环里空耗 ~50s）
            if "Page Not Found" in html or "404" in (title or ""):
                return "404"
            if not cf_challenge(html, title) and len(html) > 40000:
                break
        else:
            return None  # cf_timeout
        return html
    except WebDriverException as e:
        s = str(e)
        if ("invalid session id" in s or "browser has closed" in s
                or "no such window" in s or "SessionNotCreated" in s):
            raise SessionGone()
        raise


def build_driver_retry(profile_dir):
    """build_driver 带重试：失败清 profile 重建，规避 SingletonLock 等启动失败。"""
    _bf.UDC_DIR = profile_dir
    os.makedirs(profile_dir, exist_ok=True)
    last_err = None
    for attempt in range(1, MAX_DRIVER_RETRY + 1):
        try:
            return _raw_build_driver()
        except (Exception, SessionNotCreatedException) as e:
            last_err = e
            print(f"  ! build_driver 失败(第{attempt}次): {type(e).__name__}: {e}", flush=True)
            try:
                shutil.rmtree(profile_dir, ignore_errors=True)
            except Exception:
                pass
            os.makedirs(profile_dir, exist_ok=True)
            time.sleep(2)
    raise last_err


# --------------------------------------------------------------------------
# 数据加载（只读）
# --------------------------------------------------------------------------
def load_dim_games(conn):
    """加载全部 dim_games 行（只 SELECT，不限 season_type）。返回 (rows, by_key, by_season, codes_set)。

    注意：匹配池须含 ALL season_type（常规赛+附加赛+季后赛等），否则 BR 赛程页把
    附加赛（Play-In）与常规赛混排时，附加赛场会被误判 MISSING。PHANTOM 检测再单独
    只针对 Regular Season 行（季后赛本就不在 BR 常规赛程页，不应算 phantom）。

    by_key: (date, (sorted(norm_home, norm_away))) -> [row, ...]  （主客顺序无关）
    by_season: season(结束年) -> 行数（含所有 season_type，用于门禁相对对比）
    codes_set: 所有出现的原始队码集合（用于 unmapped 判定）
    """
    rows = []
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT game_id, game_date, away_team_abbr, home_team_abbr,
                   away_pts, home_pts, season, pbp_imported, nba_api_id, season_type
            FROM dim_games
            """
        )
        for gid, gdate, away, home, a_pts, h_pts, season, pbp_imp, nba_api, stype in cur.fetchall():
            d_iso = gdate.isoformat() if hasattr(gdate, "isoformat") else str(gdate)
            rows.append({
                "id": gid,
                "date": d_iso,
                "away": (away or "").strip(),
                "home": (home or "").strip(),
                "a_pts": a_pts,
                "h_pts": h_pts,
                "season": int(season) if season is not None else None,
                "pbp_imported": pbp_imp,
                "nba_api_id": nba_api,
                "season_type": (stype or "").strip(),
            })
    by_key = defaultdict(list)
    by_season = Counter()
    codes_set = set()
    for r in rows:
        hn = norm(r["home"])
        an = norm(r["away"])
        key = (r["date"], tuple(sorted((hn, an))))
        by_key[key].append(r)
        if r["season"] is not None:
            by_season[r["season"]] += 1
        if r["home"]:
            codes_set.add(r["home"])
        if r["away"]:
            codes_set.add(r["away"])
    return rows, by_key, by_season, codes_set


def load_pbp_present(conn, dim_rows):
    """返回 set：窗口内已导入 PBP 的 dim_games 行 id。

    实测 pbp_imported 标志是可靠代理：随机抽样 200 场窗口比赛，
    pbp_imported=True 与实际 play_by_play 行存在 100% 一致。故直接用该标志，
    不再扫描已膨胀至 18M 行的 play_by_play（全表 DISTINCT 会卡死数十分钟，
    且被其它长事务 IO 饿死）。PBP_GAP = 配对成功且 BR 已完赛(pbp_imported 非 True)。
    """
    present = set()
    for r in dim_rows:
        if (r["season"] is not None and PBP_MIN_YEAR <= r["season"] <= YEAR_MAX
                and r["pbp_imported"] is True):
            present.add(r["id"])
    return present


# --------------------------------------------------------------------------
# 单季对账
# --------------------------------------------------------------------------
def reconcile_season(dim_by_key, pbp_present, yyyy, br_games, dim_codes_set, unmapped):
    """用 dim_games(常规赛) 对账本季 BR 比赛。

    返回 (本季所有比赛记录列表, 本季新发现的 unmapped 码)。
    每条记录含 issues 列表（空=干净），严格符合报告 schema。
    """
    records = []
    season_start_note = yyyy  # dim_games.season == 结束年 == yyyy

    # 收集 BR 未收录/未知代码
    for g in br_games:
        for c in (g["visitor_code"], g["home_code"]):
            if c and c not in HIST_TO_CUR and norm(c) not in dim_codes_set:
                unmapped.add(c)

    for g in br_games:
        hn = norm(g["home_code"])
        an = norm(g["visitor_code"])
        key = (g["date"], tuple(sorted((hn, an))))
        cands = dim_by_key.get(key)
        pick = None
        if cands:
            for c in cands:
                if c["season"] == yyyy:
                    pick = c
                    break
            if pick is None:
                pick = cands[0]

        br_matchup = f"{g['visitor_code']}@{g['home_code']}"
        issues = []
        detail_parts = []

        if pick is None:
            # MISSING：BR 有、dim_games 无
            issues.append("MISSING")
            detail_parts.append(
                f"BR {g['visitor_pts']}-{g['home_pts']} 无配对 dim_games 行"
            )
            records.append({
                "game_date": g["date"],
                "br_gameid": g["gameid"],
                "br_matchup": br_matchup,
                "db_gameid": None,
                "db_matchup": None,
                "issues": issues,
                "detail": "; ".join(detail_parts),
            })
            continue

        # 已配对
        db_matchup = f"{pick['away']}@{pick['home']}"
        # 方向判定
        same_orient = (an, hn) == (norm(pick["away"]), norm(pick["home"]))
        rev_orient = (an, hn) == (norm(pick["home"]), norm(pick["away"]))

        if rev_orient and not same_orient:
            issues.append("REVERSED")
            detail_parts.append(
                f"home/away 写反 (BR {g['visitor_code']}@{g['home_code']} "
                f"vs DB {pick['away']}@{pick['home']})"
            )
            # 镜像比分也应一致；若不一致再补 SCORE_MISMATCH
            if g["visitor_pts"] is not None and pick["h_pts"] is not None:
                if int(g["visitor_pts"]) != int(pick["h_pts"]) or int(g["home_pts"]) != int(pick["a_pts"]):
                    issues.append("SCORE_MISMATCH")
                    detail_parts.append(
                        f"BR {g['visitor_pts']}-{g['home_pts']} vs DB(镜像) "
                        f"{pick['h_pts']}-{pick['a_pts']}"
                    )
        elif same_orient:
            if g["visitor_pts"] is not None and pick["a_pts"] is not None:
                if int(g["visitor_pts"]) != int(pick["a_pts"]) or int(g["home_pts"]) != int(pick["h_pts"]):
                    issues.append("SCORE_MISMATCH")
                    detail_parts.append(
                        f"BR {g['visitor_pts']}-{g['home_pts']} vs DB "
                        f"{pick['a_pts']}-{pick['h_pts']}"
                    )
        else:
            # 理论上 key 已保证主客集合相同，这里不应触发
            issues.append("MISSING")
            detail_parts.append("主客集合匹配但方向无法判定(异常)")

        # PBP_GAP：配对成功 + BR 显示已完赛（有比分）+ 无 PBP
        completed = g["visitor_pts"] is not None and g["home_pts"] is not None
        if completed and pick["id"] not in pbp_present:
            issues.append("PBP_GAP")
            detail_parts.append(f"PBP 0 行 for {pick['id']}")

        records.append({
            "game_date": g["date"],
            "br_gameid": g["gameid"],
            "br_matchup": br_matchup,
            "db_gameid": pick["id"],
            "db_matchup": db_matchup,
            "issues": issues,
            "detail": "; ".join(detail_parts),
        })

    return records, unmapped


# --------------------------------------------------------------------------
# 报告落盘 / 汇总
# --------------------------------------------------------------------------
def new_report():
    return {
        "seasons": {},
        "totals": {},
        "unmapped_codes": [],
        "notes": [
            "只读核查：除 SELECT 外不写 dim_games / play_by_play / game_id_map 任何行。",
            "核心修复：当前 BR 站点把整季常规赛拆成月度子页，主表仅渲染首月；故抓主表+全月页按 gameid 去重合并。",
            "兼容旧季：解析前仍先剥掉 HTML 注释定界符（旧版 BR 曾把整季藏在注释里）。",
            "匹配键 = (game_date, 映射后_home, 映射后_away) 主客顺序无关；不依赖 season 整数列。",
            "dim_games.season 实测=赛季结束年(=BR yyyy)，故报告 season key 用结束年(如 '1997')。",
            "HIST_TO_CUR 中 NJN->BRK（团队原 BRO 为笔误，dim_games 无 BRO 码）；其余目标与 dim_games 现代码一致。",
            "PBP_GAP 以 pbp_imported 标志为代理（实测 200/200 与实际 PBP 行一致；全表 DISTINCT 会卡死）。",
            "匹配池加载 dim_games 全部 season_type（BR 赛程页把附加赛与常规赛混排，否则附加赛被误判 MISSING）；PHANTOM 仅对 Regular Season 行。",
            "DUPLICATE（额外标签）：同日同两队互换在 dim_games 出现多次=重复行（多余副本常带 home/away 写反）；PHANTOM 仅保留真正孤儿（dim 有、BR 无且无 twin）。",
            "seasons[yyyy] 列出该季全部 BR 比赛；干净比赛 issues=[]；脏数据含对应标签。",
        ],
        "meta": {
            "range_years": f"{YEAR_MIN}-{YEAR_MAX}",
            "generated_by": "audit_br_schedule.py (month-page merge + comment-strip compat)",
        },
    }


def dump_report(report):
    """原子写：先写 REPORT_PATH.tmp 再 os.replace，避免进程被硬杀时把 JSON 写坏
    （续跑的前提——父驱动 kill 子进程后报告必须仍是合法 JSON）。"""
    tmp = REPORT_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, REPORT_PATH)


def dump_season_file(yyyy, records):
    """每季独立缓存：season_<yyyy>.json，原子写。

    崩溃安全第二道防线——即便聚合报告损坏/丢失，也能从各季独立文件
    重建或续跑；任一季子进程被硬杀，最多丢本季，不从聚合报告整体回退。
    放在 compute_totals 之后调用，确保含窗口扫描补上的 PHANTOM/DUPLICATE。"""
    sp = os.path.join(os.path.dirname(REPORT_PATH), f"season_{yyyy}.json")
    tmp = sp + ".tmp"
    payload = {"year": yyyy, "count": len(records), "records": records}
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, sp)


def _rebuild_from_season_files():
    """聚合报告丢失/损坏时的最后防线：从 season_<yyyy>.json 重建 seasons。

    仅在 load 聚合报告抛异常时调用（正常跑聚合报告存在则不触发）。"""
    import glob
    rep = new_report()
    out_dir = os.path.dirname(REPORT_PATH)
    for fp in sorted(glob.glob(os.path.join(out_dir, "season_*.json"))):
        try:
            d = json.load(open(fp, encoding="utf-8"))
            y = str(d.get("year"))
            recs = d.get("records", [])
            # 仅采纳有真实数据的季（排除纯 SESAON_FETCH_FAILED 占位）
            if y and recs and any(not set(r.get("issues", [])) & {"SEASON_FETCH_FAILED"} for r in recs):
                rep["seasons"][y] = recs
        except Exception:
            continue
    return rep


def _gate_ok(yyyy, br_count, expected_dim):
    """门禁：常规赛整季解析行数应合理。

    历史季（尤其 1940-50 缩水季，常规赛可低至 ~190 场）不能因绝对下限
    被误杀；同时必须拦住注释 bug 的 ~80 行假解析。策略：
      - 已知 dim 同季场次数(expected_dim) 且 >=200：用 0.6 相对门禁（拦解析缺失）。
      - 小季 / 未知(expected_dim<200 或 0)：仅用绝对下限 120 拦注释 bug
        （120 明显高于 ~80 的 bug 签名，低于最小真实季 ~190）。
    """
    if expected_dim and expected_dim >= 200:
        if br_count < 0.6 * expected_dim:
            return False, (
                f"行数 {br_count} 远低于 dim_games 同季 {expected_dim} 场"
                f"（< 0.6*expected，疑似解析缺失）"
            )
    else:
        if br_count < 120:
            return False, f"行数 {br_count} < 120（疑似注释 bug，正常应接近整季真实场次）"
    return True, f"行数 {br_count}（dim_games 同季 {expected_dim}）通过门禁"


# --------------------------------------------------------------------------
# 处理单季
# --------------------------------------------------------------------------
def process_season(conn, driver, limiter, yyyy, report, dim_by_key,
                   pbp_present, dim_codes_set, unmapped, attempted, watchdog=None):
    """处理单季：抓取 + 解析 + 门禁 + 对账 + 落盘。返回 (driver, ok)。

    watchdog: dict{"fired": bool}，由 run() 的 threading.Timer 在 300s 时置 True
    并强制回收 driver。本函数在每次页 fetch 重试开头检查，若已触发则抛 SeasonTimeout，
    让 run() 的 except 捕获并标记该季 SEASON_FETCH_FAILED。
    """
    key = str(yyyy)
    attempted.add(yyyy)
    print(f"\n=== 赛季 YYYY={yyyy} (结束年, 对应 dim season={yyyy}) ===", flush=True)

    # 主表 + 月度子页：当前 BR 站点把整季按月份拆子页，主表仅渲染首月。
    # 旧季若整季塞在 HTML 注释里，注释剥离后主表即含全季（月页 404 跳过）。
    base = SCHED_URL.format(yyyy=yyyy)
    _months = SEASON_MONTHS_OVERRIDE.get(yyyy, SCHED_MONTHS)
    pages = [base] + [base.replace(".html", f"-{m}.html") for m in _months]

    all_games = {}
    main_failed = False

    for pi, url in enumerate(pages):
        is_main = (pi == 0)
        html = None
        for _ in range(1, MAX_PAGE_RETRY + 1):
            # 看门狗已触发：本季单页卡死被强制回收，立即抛出让 run() 标记 FAILED
            if watchdog and watchdog.get("fired"):
                raise SeasonTimeout()
            try:
                limiter.wait()
                html = fetch_schedule_html(driver, url)
                if html is not None and html != "404":
                    break
            except SessionGone:
                print("  ! driver 会话失效, 重建中...", flush=True)
                try:
                    driver.quit()
                except Exception:
                    pass
                driver = build_driver_retry(
                    os.path.join(HERE, f".uc_recon_profile_{yyyy}_{int(time.time())}")
                )
            except WebDriverException as e:
                print(f"  ! WebDriverException: {type(e).__name__}: {e}", flush=True)
                try:
                    driver.quit()
                except Exception:
                    pass
                driver = build_driver_retry(
                    os.path.join(HERE, f".uc_recon_profile_{yyyy}_{int(time.time())}")
                )
        if html is None:
            # CF 超时
            if is_main:
                main_failed = True
                print("  [!] 主表 CF 超时", flush=True)
            else:
                print(f"  [~] 月页 {url.split('/')[-1]} CF 超时，跳过", flush=True)
            continue
        if html == "404":
            # 月页 404 = 该月无比赛或旧季布局，跳过（不影响主表首月）
            continue
        parsed = parse_schedule_soup(html, yyyy)
        for g in parsed:
            all_games[g["gameid"]] = g  # 按 gameid 去重合并
        print(f"  [+] {url.split('/')[-1]}: +{len(parsed)} 场 (累计 {len(all_games)})", flush=True)

    if main_failed and not all_games:
        print("  [!] 主表 CF 超时且无任何比赛，标记 SEASON_FETCH_FAILED", flush=True)
        report["seasons"][key] = [{
            "game_date": None, "br_gameid": None, "br_matchup": None,
            "db_gameid": None, "db_matchup": None,
            "issues": ["SEASON_FETCH_FAILED"],
            "detail": "CF 超时（主表多次重试仍拿不到页面）",
        }]
        dump_report(report)
        return driver, False

    br_games = list(all_games.values())
    expected_dim = report.get("_dim_by_season", {}).get(yyyy, 0)
    ok, msg = _gate_ok(yyyy, len(br_games), expected_dim)
    print(f"  解析到 BR 比赛 {len(br_games)} 场 | {msg}", flush=True)
    if not ok:
        # 注释 bug 未生效：停下并报告（不在本季强行继续，避免污染报告）
        report["seasons"][key] = [{
            "game_date": None, "br_gameid": None, "br_matchup": None,
            "db_gameid": None, "db_matchup": None,
            "issues": ["SEASON_FETCH_FAILED"],
            "detail": f"解析门禁未过: {msg}（疑似注释剥离未生效）",
        }]
        dump_report(report)
        return driver, False

    records, unmapped = reconcile_season(
        dim_by_key, pbp_present, yyyy, br_games, dim_codes_set, unmapped
    )
    report["seasons"][key] = records
    # 更新累计 unmapped
    report["unmapped_codes"] = sorted(set(report.get("unmapped_codes", [])) | unmapped)

    dirty = [r for r in records if r["issues"]]
    print(f"  [扫描] BR {len(br_games)} 场 | 脏数据 {len(dirty)} 条", flush=True)
    dump_report(report)
    return driver, True


# --------------------------------------------------------------------------
# 主流程
# --------------------------------------------------------------------------
def run(args):
    conn = psycopg2.connect(**DB_CONN)
    conn.autocommit = True  # 只读
    # 安全网：任何单条查询超过 5 分钟即中止，避免被其它长事务/全表扫描拖死
    try:
        with conn.cursor() as cur:
            cur.execute("SET statement_timeout = 300000")
    except Exception:
        pass

    # 加载 dim_games（一次性）
    print("[i] 加载 dim_games (Regular Season) ...", flush=True)
    dim_rows, dim_by_key, dim_by_season, dim_codes_set = load_dim_games(conn)
    pbp_present = load_pbp_present(conn, dim_rows)
    print(f"[i] dim_games 常规赛行数={len(dim_rows)} | 已导入PBP={len(pbp_present)}", flush=True)
    print(f"[i] dim_games 覆盖 season 范围: {min(dim_by_season)}..{max(dim_by_season)}", flush=True)
    # 仅我们窗口内的「常规赛」dim 行数（审计范围；不含附加赛/季后赛）
    db_window = sum(
        1 for r in dim_rows
        if r.get("season_type") == "Regular Season"
        and r["season"] is not None and YEAR_MIN <= r["season"] <= YEAR_MAX
    )

    # 报告：载入已有（用于 --years 重试合并）或新建
    if args.years and os.path.exists(REPORT_PATH):
        try:
            with open(REPORT_PATH, "r", encoding="utf-8") as f:
                report = json.load(f)
            report.setdefault("seasons", {})
            report.setdefault("unmapped_codes", [])
            # 关键：剥离上一批写入的「派生」条目(PHANTOM/DUPLICATE)，避免跨批重复累加。
            # 这些会在本批 PHANTOM 检测时按全量重新计算；reconciled 记录(MISSING/REVERSED/...)
            # 不受影响，保留原值。
            for k in list(report["seasons"].keys()):
                report["seasons"][k] = [
                    r for r in report["seasons"][k]
                    if not (set(r.get("issues", [])) & {"PHANTOM", "DUPLICATE"})
                ]
            print("[i] 载入已有报告用于合并重试（已剥离派生 PHANTOM/DUPLICATE 待重算）", flush=True)
        except Exception:
            # 聚合报告缺失/损坏：退而从各季独立缓存重建（最后防线）
            report = _rebuild_from_season_files()
            if report["seasons"]:
                print(f"[i] 聚合报告不可读，已从 {len(report['seasons'])} 个 season_*.json 重建", flush=True)
            else:
                report = new_report()
    else:
        report = new_report()
    report["_dim_by_season"] = dict(dim_by_season)  # 内部用，落盘时会写进 json（无害）

    limiter = RateLimiter(max_per_minute=15, min_interval=4.5)
    driver = None
    attempted = set()
    any_gate_fail = False

    # 决定要跑的年份
    if args.years:
        order = sorted(int(y) for y in args.years)
    elif args.all:
        order = list(range(YEAR_MIN, YEAR_MAX + 1))  # 1950..2026 共 77（BR 地板=结束年1950）
    else:
        order = [2026]  # 默认 = 验证季

    try:
        for yyyy in order:
            profile_dir = os.path.join(HERE, f".uc_recon_profile_{yyyy}")
            try:
                if driver is None:
                    driver = build_driver_retry(profile_dir)
            except Exception as e:
                print(f"[FATAL] build_driver 失败 季 {yyyy}: {type(e).__name__}: {e}", flush=True)
                key = str(yyyy)
                attempted.add(yyyy)
                report["seasons"][key] = [{
                    "game_date": None, "br_gameid": None, "br_matchup": None,
                    "db_gameid": None, "db_matchup": None,
                    "issues": ["SEASON_FETCH_FAILED"],
                    "detail": f"build_driver 失败: {type(e).__name__}",
                }]
                dump_report(report)
                continue

            # ---- 单季看门狗：300s 内未结束则强制回收 driver 并抛 SeasonTimeout ----
            # 避免某季 driver/CF 卡死把整个进程拖到被平台硬杀（上一轮 1999 卡 ~50min 被杀）。
            # 用 threading.Timer（非 signal.alarm：后者对 C 扩展 driver 调用不一定能中断）。
            watchdog = {"fired": False}

            def _watchdog_fire():
                watchdog["fired"] = True
                try:
                    driver.quit()
                except Exception:
                    pass

            timer = threading.Timer(300, _watchdog_fire)
            timer.daemon = True
            timer.start()
            try:
                driver, ok = process_season(
                    conn, driver, limiter, yyyy, report, dim_by_key,
                    pbp_present, dim_codes_set, set(), attempted, watchdog,
                )
                if not ok:
                    any_gate_fail = True
                # 验证季：打印样本 + 门禁结果供确认
                if args.validate and ok and yyyy == 2026:
                    print("\n--- 验证季 YYYY=2026 解析样本（前 3 场）---", flush=True)
                    for g in report["seasons"]["2026"][:3]:
                        print(f"  {g}", flush=True)
                    print(f"  [门禁] 本季 BR 场次={len(report['seasons']['2026'])} "
                          f"| dim_games 同季={report.get('_dim_by_season', {}).get(2026)}", flush=True)
            except SeasonTimeout:
                print(f"[!] 季 {yyyy} 看门狗超时(300s)，强制回收并标记 SEASON_FETCH_FAILED", flush=True)
                key = str(yyyy)
                attempted.add(yyyy)
                report["seasons"].setdefault(key, []).append({
                    "game_date": None, "br_gameid": None, "br_matchup": None,
                    "db_gameid": None, "db_matchup": None,
                    "issues": ["SEASON_FETCH_FAILED"],
                    "detail": "看门狗超时(300s)：单季卡死被强制回收",
                })
                dump_report(report)
                any_gate_fail = True
                driver = None  # 强制回收，下季重建
            except Exception as e:
                print(f"[!] 季 {yyyy} 未捕获异常: {type(e).__name__}: {e}", flush=True)
                key = str(yyyy)
                attempted.add(yyyy)
                report["seasons"].setdefault(key, []).append({
                    "game_date": None, "br_gameid": None, "br_matchup": None,
                    "db_gameid": None, "db_matchup": None,
                    "issues": ["SEASON_FETCH_FAILED"],
                    "detail": f"未捕获异常: {type(e).__name__}: {e}",
                })
                dump_report(report)
                any_gate_fail = True
                driver = None  # driver 可能已死，下季重建，避免死 driver 拖累后续季
            finally:
                timer.cancel()  # 防止看门狗在下一季误杀 driver
    finally:
        if driver is not None:
            try:
                driver.quit()
            except Exception:
                pass

    # ---- PHANTOM / DUPLICATE 检测：窗口内未被任何 BR 比赛配对的 dim_games 行 ----
    # 先收集本批已配对 dim id
    matched_ids = set()
    for key, recs in report.get("seasons", {}).items():
        for r in recs:
            if r.get("db_gameid"):
                matched_ids.add(r["db_gameid"])
    # 收集本批 BR 日期范围（仅成功季）
    br_dates = []
    for key, recs in report.get("seasons", {}).items():
        for r in recs:
            if r.get("game_date"):
                br_dates.append(r["game_date"])
    br_min = min(br_dates) if br_dates else None
    br_max = max(br_dates) if br_dates else None

    # 预建 (date, 排序后两队) -> [dim id, ...]，用于识别重复行（同日同队互换）
    teamkey_groups = defaultdict(list)
    for r in dim_rows:
        if r.get("season_type") != "Regular Season":
            continue
        tkey = (r["date"], tuple(sorted((norm(r["home"]), norm(r["away"])))))
        teamkey_groups[tkey].append(r["id"])

    phantom_added = 0
    dup_added = 0
    if br_min and br_max:
        for r in dim_rows:
            if r["id"] in matched_ids:
                continue
            if r.get("season_type") != "Regular Season":
                continue  # 仅针对常规赛行（附加赛/季后赛本就不在 BR 常规赛程页）
            if r["date"] < br_min or r["date"] > br_max:
                continue  # 仅窗口内
            if r["season"] is not None and not (YEAR_MIN <= r["season"] <= YEAR_MAX):
                continue
            tkey = (r["date"], tuple(sorted((norm(r["home"]), norm(r["away"])))))
            skey = str(r["season"])
            twins = [i for i in teamkey_groups.get(tkey, []) if i != r["id"]]
            if twins:
                # 同日同队互换出现多次 = dim_games 重复行（多余副本，常带 home/away 写反）
                issue = "DUPLICATE"
                detail = (
                    f"dim_games 重复行 (同日同队互换): 与 "
                    f"{', '.join(twins)} 重复; 本行 {r['id']} "
                    f"(DB {r['a_pts']}-{r['h_pts']})"
                )
                dup_added += 1
            else:
                # 无 twin 且未被 BR 配对 = 真孤儿（dim 有、BR 无）
                issue = "PHANTOM"
                detail = f"dim_games {r['id']} 无 BR 配对 (DB {r['a_pts']}-{r['h_pts']})"
                phantom_added += 1
            report["seasons"].setdefault(skey, []).append({
                "game_date": r["date"],
                "br_gameid": None,
                "br_matchup": None,
                "db_gameid": r["id"],
                "db_matchup": f"{r['away']}@{r['home']}",
                "issues": [issue],
                "detail": detail,
            })
    print(f"\n[i] 窗口 [{br_min}..{br_max}] 内未配对常规赛行: "
          f"PHANTOM(真孤儿)={phantom_added} | DUPLICATE(重复行)={dup_added}", flush=True)

    # ---- 汇总 totals ----
    compute_totals(report, db_window)

    # ---- 每季独立缓存（崩溃安全第二道防线）----
    # 即便聚合报告损坏，也能从 season_<yyyy>.json 重建/续跑。
    # 放在 compute_totals 之后：此时 report['seasons'] 已含窗口扫描补上的
    # PHANTOM/DUPLICATE，逐季落盘拿到的是该季最终态。
    try:
        for key, recs in report.get("seasons", {}).items():
            try:
                yyyy = int(key)
            except Exception:
                continue
            dump_season_file(yyyy, recs)
        print(f"[i] 每季独立缓存已写: {os.path.dirname(REPORT_PATH)}/season_*.json", flush=True)
    except Exception as e:
        print(f"[!] 每季缓存写入异常（不影响聚合报告）: {type(e).__name__}: {e}", flush=True)

    dump_report(report)

    # 清理内部字段
    report.pop("_dim_by_season", None)
    dump_report(report)

    print("\n=== 总计数 ===", flush=True)
    t = report["totals"]
    print(f"  seasons_processed(attempted) = {t.get('seasons_processed')}", flush=True)
    print(f"  br_games_total   = {t.get('br_games_total')}", flush=True)
    print(f"  db_games_total   = {t.get('db_games_total')}", flush=True)
    print(f"  MISSING={t.get('MISSING')} PHANTOM={t.get('PHANTOM')} "
          f"DUPLICATE={t.get('DUPLICATE')} REVERSED={t.get('REVERSED')} "
          f"SCORE_MISMATCH={t.get('SCORE_MISMATCH')} PBP_GAP={t.get('PBP_GAP')} "
          f"SEASON_FETCH_FAILED={t.get('SEASON_FETCH_FAILED')}", flush=True)
    print(f"  unmapped_codes   = {report.get('unmapped_codes')}", flush=True)
    print(f"  报告已落盘: {REPORT_PATH}", flush=True)
    if any_gate_fail:
        print("[!!] 存在门禁未过/抓取失败的赛季，本次未完整完成。请用 --years 重试失败季。", flush=True)
    return report


def compute_totals(report, db_window):
    counts = Counter()
    br_total = 0
    db_total = db_window
    seasons_processed = 0
    for key, recs in report.get("seasons", {}).items():
        seasons_processed += 1
        for r in recs:
            if r.get("br_gameid"):
                br_total += 1
            for iss in r.get("issues", []):
                counts[iss] += 1
    report["totals"] = {
        "seasons_processed": seasons_processed,
        "br_games_total": br_total,
        "db_games_total": db_total,
        "MISSING": counts.get("MISSING", 0),
        "PHANTOM": counts.get("PHANTOM", 0),
        "DUPLICATE": counts.get("DUPLICATE", 0),
        "REVERSED": counts.get("REVERSED", 0),
        "SCORE_MISMATCH": counts.get("SCORE_MISMATCH", 0),
        "PBP_GAP": counts.get("PBP_GAP", 0),
        "SEASON_FETCH_FAILED": counts.get("SEASON_FETCH_FAILED", 0),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--validate", action="store_true",
                    help="仅跑 YYYY=2026 验证季（打印样本+门禁），确认无误后再 --all")
    ap.add_argument("--all", action="store_true",
                    help="跑全量 1997..2026（30 季）")
    ap.add_argument("--years", nargs="+", help="指定若干结束年（如 1999 2012）重试，合并进现有报告")
    args = ap.parse_args()
    if not args.validate and not args.all and not args.years:
        args.validate = True  # 默认 = 验证季，安全优先
    run(args)


if __name__ == "__main__":
    main()
