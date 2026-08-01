#!/usr/bin/env python3
"""
BR 联盟赛程页 <-> dim_games 脏数据核查 (全量 1996-2026)。

方法:
- 对每赛季爬取 BR 联盟赛程页 (https://www.basketball-reference.com/leagues/NBA_YYYY_games.html,
  YYYY = 赛季结束年, 1997..2026 共 30 个, 覆盖咱们的 1996..2025 季)。
- 解析出全部比赛: game_date / 主客队 (从 /teams/<CODE>/ 链接取历史缩写) / 比分 / br_gameid
  (从 /boxscores/<YYYYMMDD><主队代码>.html 取)。
- 与 dim_games (Regular Season) 对账, 按 (game_date, 归一后主队, 归一后客队) 配对, 标记:
  MISSING / PHANTOM / REVERSED / SCORE_MISMATCH / PBP_GAP / SEASON_FETCH_FAILED。
- 增量写 /tmp/dirty_games_report.json: 每处理完一个赛季 json.dump 整个累计结果 (每季落盘一次)。

铁律: 只读核查。除了读 dim_games / play_by_play / game_id_map, 只写 /tmp/dirty_games_report.json。
绝不修改任何数据库行。

团队缩写归一 (关键):
- BR 老赛季用历史缩写 (WSB/NJN/SEA/VAN/CHH/NOK/NOH/CHA 等), 咱们 dim_games 旧比赛也存历史缩写,
  新比赛存现代缩写 (BRK/CHO/PHO...)。两边代码都先过同一张 HIST_TO_CUR 映射到 30 队现代缩写,
  再按 (date, home, away) 配对。现代缩写映射后仍是自身 (幂等)。
- 注意: 实测 dim_games 现代 Brooklyn=BRK (不是 BKN/BRO), Charlotte=CHO, Phoenix=PHO。
  HIST_TO_CUR 必须映射到这些真实存在的代码, 否则配对全错。

健壮性:
- 每赛季独立 try/except, 单季失败只记 SEASON_FETCH_FAILED 并继续, 绝不跳过末尾报告写出。
- 每赛季全新 chromedriver profile 目录 (绕开 SingletonLock), build_driver 重试
  (捕获 SessionNotCreatedException), fetch 捕获 SessionGone。
- 验证季 YYYY=2026 一跑完立刻落盘, 再继续其余 29 季 (本脚本顺序 [2026, 1997..2025])。

用法:
  python recon_games_br.py --verify-only   # 仅 YYYY=2026 验证季
  python recon_games_br.py --all           # 全量 (断点续跑: 已完成的季自动跳过)
"""
import os
import sys
import re
import json
import time
import shutil
import subprocess
import argparse
from datetime import datetime
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import psycopg2
from psycopg2.extensions import AsIs
from dotenv import load_dotenv
load_dotenv(os.path.join(HERE, ".env"))
# 代理会破坏 undetected_chromedriver, 清掉
for k in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY", "all_proxy", "ALL_PROXY"):
    os.environ.pop(k, None)

from bs4 import BeautifulSoup, Comment
import undetected_chromedriver as uc
from selenium.common.exceptions import SessionNotCreatedException, WebDriverException

REPORT = "/tmp/dirty_games_report.json"
LEMMA_BASE = "https://www.basketball-reference.com/leagues/NBA_{YYYY}_games.html"

# 30 队现代缩写 (与 dim_games 实测一致: Brooklyn=BRK, Charlotte=CHO, Phoenix=PHO)
MODERN_CODES = {
    "ATL", "BOS", "BRK", "CHI", "CHO", "CLE", "DAL", "DEN", "DET", "GSW",
    "HOU", "IND", "LAC", "LAL", "MEM", "MIA", "MIL", "MIN", "NOP", "NYK",
    "OKC", "ORL", "PHI", "PHO", "POR", "SAC", "SAS", "TOR", "UTA", "WAS",
}

# 历史 -> 现代  (目标必须是 dim_games 真实存在的现代代码)
HIST_TO_CUR = {
    "WSB": "WAS",  # Washington Bullets -> Wizards
    "NJN": "BRK",  # New Jersey Nets -> Brooklyn (dim_games 用 BRK, 非 BKN/BRO)
    "SEA": "OKC",  # Seattle -> Oklahoma City (搬迁)
    "VAN": "MEM",  # Vancouver -> Memphis (搬迁)
    "CHH": "CHO",  # 原 Charlotte Hornets -> 现 Charlotte
    "NOK": "NOP", "NOH": "NOP",  # New Orleans 各阶段 -> Pelicans
    "CHA": "CHO",  # Bobcats -> Hornets
    # 以下为幂等保底 (现代代码映射后仍是自身)
    "BRK": "BRK", "CHO": "CHO", "NOP": "NOP", "MEM": "MEM", "OKC": "OKC",
    "PHO": "PHO", "WAS": "WAS",
}


def norm(code):
    """历史/现代代码 -> 30 队现代缩写 (幂等)。未收录原样返回 (由调用方判 unmapped)。"""
    if not code:
        return code
    return HIST_TO_CUR.get(code, code)


# ---------------------------------------------------------------------------
# 数据库 (只读)
# ---------------------------------------------------------------------------
def get_conn():
    # statement_timeout 防止在共享 DB 高负载时单条查询挂死数小时。
    # 提到 300s: 共享 Postgres 有其它会话在跑 5.5h 的 count(*), 单条 RS 查询偶发 >120s,
    # 但仍应在合理时间返回。配合 with_db 的重连重试, 超时即重试而非放弃。
    return psycopg2.connect(
        host=os.environ.get("DB_HOST", "localhost"),
        port=int(os.environ.get("DB_PORT", 5433)),
        dbname=os.environ.get("DB_NAME", "nba"),
        user=os.environ.get("DB_USER", "postgres"),
        password=os.environ.get("DB_PASSWORD"),
        options="-c statement_timeout=300000",
    )


def with_db(fn, label, max_tries=4, sleep_base=8):
    """打开 (必要时重连) 数据库连接执行 fn(conn), 在超时/断连时自动重连重试。

    共享 DB 偶发 statement_timeout / 连接被杀, 每次重试都重建一条全新连接,
    避免复用已损坏/已中断的连接。返回 fn(conn) 的结果。"""
    last = None
    for attempt in range(1, max_tries + 1):
        conn = get_conn()
        try:
            return fn(conn)
        except psycopg2.OperationalError as e:
            last = e
            try:
                conn.rollback()
            except Exception:
                pass
            try:
                conn.close()
            except Exception:
                pass
            print(f"OperationalError {label} attempt {attempt}/{max_tries}: {e}", flush=True)
            if attempt < max_tries:
                time.sleep(sleep_base * attempt)
        except Exception as e:
            try:
                conn.close()
            except Exception:
                pass
            raise
    raise last


def load_pbp_ids_for_season(conn, db_rows):
    """本季所有配对候选 gameid (db game_id + nba_api_id) 中, 在 play_by_play 里
    实际存在行的集合。用索引点查 (gameid = ANY(...)), 避免全表 DISTINCT 扫描
    (共享 DB 高负载下全表扫描会卡死数小时)。"""
    ids = set()
    for r in db_rows:
        if r["game_id"]:
            ids.add(r["game_id"])
        if r["nba_api_id"]:
            ids.add(r["nba_api_id"])
    if not ids:
        return set()
    with conn.cursor() as cur:
        cur.execute(
            "SELECT DISTINCT gameid FROM play_by_play WHERE gameid = ANY(%s)",
            (list(ids),),
        )
        return {str(g) for (g,) in cur.fetchall() if g is not None}


def load_db_season(conn, db_season):
    """某季 (end year, 即 BR 的 YYYY) 全部 Regular Season 行。

    注意: dim_games.season 是【结束年】(season=2026 即 2025-26 季, 日期 2025-10..2026-04)。
    BR 的 YYYY 恰好等于这个结束年, 所以按 season=YYYY 取数 (而非 team-lead 口述的 YYYY-1)。
    报告里的 season 字段仍按 team-lead 要求记 YYYY-1 (起始年)。"""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT game_id, game_date, away_team_abbr, home_team_abbr,
                   away_pts, home_pts, nba_api_id
            FROM dim_games
            WHERE season = %s AND season_type = 'Regular Season'
            """,
            (db_season,),
        )
        rows = []
        for gid, gdate, av, ah, ap, hp, nba_id in cur.fetchall():
            rows.append({
                "game_id": gid,
                "game_date": gdate.strftime("%Y-%m-%d") if gdate else None,
                "away": av,
                "home": ah,
                "away_pts": ap,
                "home_pts": hp,
                "nba_api_id": (str(nba_id) if nba_id is not None else None),
            })
        return rows


# ---------------------------------------------------------------------------
# 浏览器
# ---------------------------------------------------------------------------
class SessionGone(Exception):
    pass


def _chrome_major():
    """探测已安装的 Chrome 大版本 (uc 默认会拉最新 driver 而与本机 Chrome 不符,
    必须显式传 version_main 匹配本机版本, 否则 SessionNotCreatedException)。"""
    try:
        out = subprocess.check_output(
            ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
             "--version"], stderr=subprocess.DEVNULL).decode(errors="ignore")
        m = re.search(r"(\d+)\.", out)
        if m:
            return int(m.group(1))
    except Exception:
        pass
    return 150


def build_driver(profile_dir, max_tries=3):
    last = None
    vmajor = _chrome_major()
    for _ in range(max_tries):
        try:
            opts = uc.ChromeOptions()
            opts.add_argument("--no-sandbox")
            opts.add_argument("--disable-dev-shm-usage")
            opts.add_argument("--window-size=1280,900")
            opts.add_argument(f"--user-data-dir={profile_dir}")
            opts.add_argument("--disable-gpu")
            # 显式传本机 Chrome 大版本, 让 uc 下载匹配的 driver (避免 151 driver vs 150 Chrome)
            # headless=False: 复用 br_fill_pbp 的方式, 无头模式会被 CF 托管挑战永久卡住
            # (实测 headless 下 "请稍候…" 挑战页 160s+ 不解除), 而 headful 能过 CF。
            d = uc.Chrome(options=opts, version_main=vmajor, headless=False)
            d.set_page_load_timeout(60)
            d.implicitly_wait(3)
            return d
        except SessionNotCreatedException as e:
            last = e
            shutil.rmtree(profile_dir, ignore_errors=True)
            os.makedirs(profile_dir, exist_ok=True)
            time.sleep(2)
    raise last


def cf_challenge(html, title):
    t = (title or "")
    h = (html or "")
    # 英文 + 中文 CF 挑战页标识
    markers = [
        "Just a moment", "cf-browser-verification", "Checking your browser",
        "cf-chl", "Verify you are human", "DDOS", "Attention Required",
        "请稍候", "验证您是真实用户", "Checking if", "challenges.cloudflare.com",
    ]
    return any(m in t or m in h for m in markers)


class RateLimiter:
    """BR 请求硬上限: 最小间隔 + 滚动 60s 窗口, 绝不超过 max_per_minute。"""
    def __init__(self, max_per_minute=15, min_interval=5.0):
        self.max_per_minute = max(1, int(max_per_minute))
        self.min_interval = max(1.0, float(min_interval))
        self._times = []
        self._last = 0.0

    def wait(self):
        now = time.time()
        since = now - self._last
        sleep_for = self.min_interval - since if since < self.min_interval else 0.0
        cutoff = now - 60.0
        self._times = [t for t in self._times if t > cutoff]
        if len(self._times) >= self.max_per_minute:
            sleep_for = max(sleep_for, self._times[0] + 60.0 - now)
        if sleep_for > 0:
            time.sleep(sleep_for)
        now = time.time()
        self._times.append(now)
        self._last = now


def fetch_schedule(driver, url, limiter, max_cf_wait=180):
    """返回 html 或 None (CF 超时)。session 失效抛 SessionGone。"""
    limiter.wait()
    try:
        driver.get(url)
    except WebDriverException as e:
        # 任何导航期异常 (含 NoSuchWindow/target window already closed) 都视为会话失效 -> 重建
        raise SessionGone()
    html = ""
    steps = max(1, max_cf_wait // 2)
    last_log = -10
    for i in range(steps):
        time.sleep(2)
        try:
            html = driver.page_source
            title = driver.title
        except WebDriverException:
            raise SessionGone()
        if not cf_challenge(html, title) and len(html) > 30000:
            break
        if i - last_log >= 5:  # ~10s 心跳
            print(f"  [CF] 等待挑战解除... t={i*2}s title={title!r} len={len(html)}", flush=True)
            last_log = i
    else:
        # CF 超时: 落盘调试信息
        try:
            with open("/tmp/cf_debug.html", "w", encoding="utf-8") as fh:
                fh.write(html or "")
            print(f"  [CF-TIMEOUT-DEBUG] title={title!r} len={len(html or '')} "
                  f"snippet={(html or '')[:300]!r}", flush=True)
        except Exception as e:
            print(f"  [CF-TIMEOUT-DEBUG] 无法落盘: {e}", flush=True)
        return None
    return html


# ---------------------------------------------------------------------------
# 解析 BR 赛程页
# ---------------------------------------------------------------------------
def find_games_table(soup):
    t = soup.find("table", id="games")
    if t:
        return t
    # BR 把数据表包在 HTML 注释里, 需从注释中解析
    for c in soup.find_all(string=lambda s: isinstance(s, Comment)):
        cs = BeautifulSoup(c, "lxml")
        t = cs.find("table", id="games")
        if t:
            return t
    # 兜底: 含 'Date' 表头的任意表
    for t in soup.find_all("table"):
        if t.find("th", string=lambda s: s and "Date" in s):
            return t
    return None


def _code_from_cell(cell):
    if cell is None:
        return None
    a = cell.find("a")
    if a and a.get("href"):
        m = re.search(r"/teams/([A-Za-z]{2,3})/", a["href"])
        if m:
            return m.group(1).upper()
    return None


def _gid_from_cell(cell):
    if cell is None:
        return None
    a = cell.find("a")
    if a and a.get("href"):
        m = re.search(r"/boxscores/([A-Za-z0-9]+\.html)", a["href"])
        if m:
            return m.group(1).replace(".html", "")
    return None


def _parse_date(txt):
    if not txt:
        return None
    txt = txt.strip()
    for fmt in ("%a, %b %d, %Y", "%Y-%m-%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(txt, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def _int(x):
    try:
        return int(str(x).strip())
    except (ValueError, TypeError):
        return None


def parse_games(html, unmapped):
    """解析 BR 赛程页 -> 比赛列表。每场: game_date, visitor_code, home_code,
    visitor_pts, home_pts, br_gameid。收集未收录 (归一后非 30 队) 的原始 BR code 到 unmapped。"""
    soup = BeautifulSoup(html, "lxml")
    table = find_games_table(soup)
    if table is None:
        return []
    # 表头列索引
    head = table.find("thead") or table.find("tr")
    head_cells = head.find_all(["th", "td"])
    cols = [c.get_text(strip=True) for c in head_cells]

    def idx(name):
        for i, c in enumerate(cols):
            if c and c.lower().startswith(name.lower()):
                return i
        return -1

    i_date = idx("Date")
    i_vis = idx("Visitor")
    i_home = idx("Home")
    pts_idx = [i for i, c in enumerate(cols) if c and c.upper() == "PTS"]
    i_vpts = pts_idx[0] if pts_idx else -1
    i_hpts = pts_idx[1] if len(pts_idx) > 1 else -1
    i_box = idx("Box")

    # BR 赛程表按月份拆成多个 <tbody>, 必须遍历全部; 直接拿所有 <tr> (含 thead 行会被下方跳过)
    rows = table.find_all("tr")
    games = []
    for tr in rows:
        tds = tr.find_all(["td", "th"])
        if len(tds) < 5:
            continue  # 跳过月份分隔行 (单 th) 与表头
        date_cell = tds[i_date] if 0 <= i_date < len(tds) else None
        vis_cell = tds[i_vis] if 0 <= i_vis < len(tds) else None
        home_cell = tds[i_home] if 0 <= i_home < len(tds) else None
        vpts_cell = tds[i_vpts] if 0 <= i_vpts < len(tds) else None
        hpts_cell = tds[i_hpts] if 0 <= i_hpts < len(tds) else None
        box_cell = tds[i_box] if 0 <= i_box < len(tds) else None

        gdate = _parse_date(date_cell.get_text(strip=True) if date_cell else None)
        vcode = _code_from_cell(vis_cell)
        hcode = _code_from_cell(home_cell)
        if not gdate or not vcode or not hcode:
            continue
        vpts = _int(vpts_cell.get_text(strip=True) if vpts_cell else None)
        hpts = _int(hpts_cell.get_text(strip=True) if hpts_cell else None)
        gid = _gid_from_cell(box_cell)
        if gid is None:
            # 兜底: 用日期+主队代码构造
            gid = gdate.replace("-", "") + hcode
        # 记录未收录 code
        for raw in (vcode, hcode):
            if raw and norm(raw) not in MODERN_CODES:
                unmapped.add(raw)
        games.append({
            "game_date": gdate,
            "visitor_code": vcode,
            "home_code": hcode,
            "visitor_pts": vpts,
            "home_pts": hpts,
            "br_gameid": gid,
        })
    return games


# ---------------------------------------------------------------------------
# 对账
# ---------------------------------------------------------------------------
def reconcile(br_games, db_rows, pbp_ids):
    """返回 (records, season_counts)。records 每项为 dict; season_counts 为本季各 issue 计数。"""
    recs = []
    cnt = defaultdict(int)

    # db 行按 (date, away_norm, home_norm) -> list (可消费)
    db_map = defaultdict(list)
    for r in db_rows:
        if not r["game_date"] or not r["away"] or not r["home"]:
            continue
        key = (r["game_date"], norm(r["away"]), norm(r["home"]))
        db_map[key].append(r)

    for g in br_games:
        gd = g["game_date"]
        bv, bh = norm(g["visitor_code"]), norm(g["home_code"])
        exact = (gd, bv, bh)
        rev = (gd, bh, bv)
        issues = []
        detail = ""
        matched = None
        reversed_flag = False
        if db_map.get(exact):
            matched = db_map[exact].pop(0)
        elif db_map.get(rev):
            matched = db_map[rev].pop(0)
            reversed_flag = True

        br_matchup = f"{g['visitor_code']}@{g['home_code']}"
        if matched is None:
            issues.append("MISSING")
            db_gameid = None
            db_matchup = None
        else:
            db_gameid = matched["game_id"]
            db_matchup = f"{matched['away']}@{matched['home']}"
            # 比分核对 (考虑 REVERSED)
            if reversed_flag:
                issues.append("REVERSED")
                br_a, br_h = g["visitor_pts"], g["home_pts"]
                db_a, db_h = matched["home_pts"], matched["away_pts"]  # 主客互换
            else:
                br_a, br_h = g["visitor_pts"], g["home_pts"]
                db_a, db_h = matched["away_pts"], matched["home_pts"]
            if br_a is not None and br_h is not None and db_a is not None and db_h is not None:
                if (br_a, br_h) != (db_a, db_h):
                    issues.append("SCORE_MISMATCH")
                    detail = f"BR {br_a}-{br_h} vs DB {db_a}-{db_h}"
            # PBP_GAP: play_by_play 里该 game_id (任意 source) 0 行
            has_pbp = (db_gameid in pbp_ids) or (
                matched["nba_api_id"] is not None and matched["nba_api_id"] in pbp_ids)
            if not has_pbp:
                issues.append("PBP_GAP")

        rec = {
            "season": None,  # 由调用方填充 (start year)
            "game_date": gd,
            "br_gameid": g["br_gameid"],
            "br_matchup": br_matchup,
            "db_gameid": db_gameid,
            "db_matchup": db_matchup,
            "issues": issues,
            "detail": detail,
        }
        recs.append(rec)
        for iss in issues:
            cnt[iss] += 1

    # 剩余未消费的 db 行 -> PHANTOM
    for key, rows in db_map.items():
        for r in rows:
            recs.append({
                "season": None,
                "game_date": r["game_date"],
                "br_gameid": None,
                "br_matchup": None,
                "db_gameid": r["game_id"],
                "db_matchup": f"{r['away']}@{r['home']}",
                "issues": ["PHANTOM"],
                "detail": "",
            })
            cnt["PHANTOM"] += 1

    return recs, dict(cnt)


# ---------------------------------------------------------------------------
# 报告读写
# ---------------------------------------------------------------------------
def load_report():
    if os.path.exists(REPORT):
        try:
            with open(REPORT, "r", encoding="utf-8") as f:
                data = json.load(f)
            data.setdefault("seasons", {})
            data.setdefault("totals", {})
            data.setdefault("unmapped_codes", [])
            return data
        except Exception:
            pass
    return {"seasons": {}, "totals": {}, "unmapped_codes": []}


def dump_report(report):
    tmp = REPORT + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    os.replace(tmp, REPORT)  # 原子替换, 防写一半被杀


def compute_totals(report):
    totals = {
        "seasons_processed": len(report["seasons"]),
        "br_games_total": 0,
        "db_games_total": 0,
        "MISSING": 0, "PHANTOM": 0, "REVERSED": 0,
        "SCORE_MISMATCH": 0, "PBP_GAP": 0, "SEASON_FETCH_FAILED": 0,
    }
    for recs in report["seasons"].values():
        for r in recs:
            if r.get("br_gameid"):
                totals["br_games_total"] += 1
            if r.get("db_gameid"):
                totals["db_games_total"] += 1
            for iss in r.get("issues", []):
                if iss in totals:
                    totals[iss] += 1
    return totals


# ---------------------------------------------------------------------------
# 单季处理
# ---------------------------------------------------------------------------
def process_season(start_year, limiter, report, unmapped,
                   driver_pool, profile_base):
    """处理一个赛季 (start year -> YYYY=start_year+1)。结果写入 report['seasons'][key]。
    成功或失败都写入, 保证 resume 不重复且报告完整。返回 (recs, counts, games)。"""
    key = str(start_year)
    YYYY = start_year + 1
    url = LEMMA_BASE.format(YYYY=YYYY)
    print(f"\n=== 赛季 {start_year}-{start_year+1} (YYYY={YYYY}) url={url} ===", flush=True)

    # 若已处理则跳过 (resume)
    if key in report["seasons"]:
        print(f"  [skip] 季 {key} 已在报告中, 跳过", flush=True)
        return report["seasons"][key], {}

    profile = os.path.join(profile_base, f".uc_recon_profile_{YYYY}")
    os.makedirs(profile, exist_ok=True)
    driver = driver_pool.get(YYYY)
    games = None
    fetch_failed = None

    for attempt in range(1, 4):
        try:
            if driver is None:
                driver = build_driver(profile)
                driver_pool[YYYY] = driver
            html = fetch_schedule(driver, url, limiter)
            if html is None:
                # CF 超时: 重建 driver 重试
                print(f"  ! CF 超时 (attempt {attempt}), 重建 driver...", flush=True)
                try:
                    driver.quit()
                except Exception:
                    pass
                driver = None
                driver_pool.pop(YYYY, None)
                shutil.rmtree(profile, ignore_errors=True)
                os.makedirs(profile, exist_ok=True)
                continue
            games = parse_games(html, unmapped)
            break
        except SessionGone:
            print(f"  ! driver 崩溃 SessionGone (attempt {attempt}), 重建...", flush=True)
            try:
                driver.quit()
            except Exception:
                pass
            driver = None
            driver_pool.pop(YYYY, None)
            shutil.rmtree(profile, ignore_errors=True)
            os.makedirs(profile, exist_ok=True)
            continue
        except SessionNotCreatedException as e:
            print(f"  ! SessionNotCreated (attempt {attempt}): {e}, 重建...", flush=True)
            try:
                driver.quit()
            except Exception:
                pass
            driver = None
            driver_pool.pop(YYYY, None)
            shutil.rmtree(profile, ignore_errors=True)
            os.makedirs(profile, exist_ok=True)
            continue
        except Exception as e:
            fetch_failed = f"{type(e).__name__}: {e}"
            print(f"  ! 异常: {fetch_failed}", flush=True)
            break

    if games is None or len(games) == 0:
        # 抓取/解析失败 (含 CF 挡了 -> 0 场)
        reason = fetch_failed or ("0 games parsed (possible CF block)" if games is not None else "fetch failed")
        rec = {
            "season": start_year,
            "game_date": None,
            "br_gameid": None,
            "br_matchup": None,
            "db_gameid": None,
            "db_matchup": None,
            "issues": ["SEASON_FETCH_FAILED"],
            "detail": reason,
        }
        report["seasons"][key] = [rec]
        dump_report(report)
        print(f"  [FAIL] 季 {key} 抓取/解析失败: {reason}", flush=True)
        return [rec], {"SEASON_FETCH_FAILED": 1}, None

    # 成功解析 -> 对账
    # dim_games.season 是结束年 = BR 的 YYYY。DB 查询经 with_db 重连重试, 抗共享 DB 高负载超时。
    db_season = YYYY
    db_rows = with_db(lambda c: load_db_season(c, db_season), f"load_db {YYYY}")
    pbp_ids = with_db(lambda c: load_pbp_ids_for_season(c, db_rows), f"load_pbp {YYYY}")
    recs, counts = reconcile(games, db_rows, pbp_ids)
    for r in recs:
        r["season"] = start_year
    report["seasons"][key] = recs
    dump_report(report)

    print(f"  BR 比赛数={len(games)}  DB(RS)行数={len(db_rows)}", flush=True)
    print(f"  本季分类: {counts}", flush=True)
    print(f"  已累计季数={len(report['seasons'])}  落盘 -> {REPORT}", flush=True)
    return recs, counts, games


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--verify-only", action="store_true",
                    help="仅处理验证季 YYYY=2026 (2025-26)")
    ap.add_argument("--all", action="store_true",
                    help="全量 1997..2026 (默认; 已完成季自动跳过)")
    args = ap.parse_args()

    if args.verify_only:
        years_yyyy = [2026]
    else:
        years_yyyy = [2026] + list(range(1997, 2026))  # 2026 先跑, 再 1997..2025

    report = load_report()
    unmapped = set(report.get("unmapped_codes", []))
    limiter = RateLimiter(max_per_minute=15, min_interval=5.0)
    profile_base = HERE
    driver_pool = {}

    ok_seasons = 0
    try:
        for YYYY in years_yyyy:
            start_year = YYYY - 1
            try:
                recs, counts, games = process_season(
                    start_year, limiter, report, unmapped,
                    driver_pool, profile_base)
                if recs and recs[0].get("issues") == ["SEASON_FETCH_FAILED"]:
                    pass
                else:
                    ok_seasons += 1
                    # 验证季: 打印前 3 场样本 (gameid/matchup/pts) 供 team-lead 核对解析器
                    if args.verify_only and games:
                        print("\n=== VERIFY SAMPLE (first 3 BR games) ===", flush=True)
                        for g in games[:3]:
                            print(f"  {g['br_gameid']}  "
                                  f"{g['visitor_code']}@{g['home_code']}  "
                                  f"{g['visitor_pts']}-{g['home_pts']}", flush=True)
                        print("=== VERIFY reconciliation (2025-26) ===", flush=True)
                        print(f"  BR games = {len(games)}", flush=True)
                        print(f"  counts   = {json.dumps(counts, ensure_ascii=False)}", flush=True)
            except Exception as e:
                # 单季兜底: 绝不因一场/一季异常跳过末尾报告
                key = str(start_year)
                report["seasons"].setdefault(key, [{
                    "season": start_year, "game_date": None, "br_gameid": None,
                    "br_matchup": None, "db_gameid": None, "db_matchup": None,
                    "issues": ["SEASON_FETCH_FAILED"], "detail": f"outer: {type(e).__name__}: {e}",
                }])
                dump_report(report)
                print(f"[!] 季 {key} 外层异常已记录: {e}", flush=True)
            # 季间礼貌间隔
            time.sleep(3)
    finally:
        for d in driver_pool.values():
            try:
                d.quit()
            except Exception:
                pass
        # 合并 unmapped_codes 并落盘最终报告
        report["unmapped_codes"] = sorted(unmapped)
        report["totals"] = compute_totals(report)
        dump_report(report)

    print("\n================ 全量完成 ================", flush=True)
    print(f"处理季数(非失败)={ok_seasons}  报告季数={len(report['seasons'])}", flush=True)
    print("totals:", json.dumps(report["totals"], ensure_ascii=False), flush=True)
    print("unmapped_codes:", report["unmapped_codes"], flush=True)
    print(f"报告文件: {REPORT}", flush=True)


if __name__ == "__main__":
    main()
