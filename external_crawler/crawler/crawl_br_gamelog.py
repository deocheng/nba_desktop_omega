import os
import json
"""
BR 球员 gamelog 批量爬取 + 入库
数据源: https://www.basketball-reference.com/players/{letter}/{player_id}/gamelog/{season}
写入: player_gamelog 表

用法:
  python crawl_br_gamelog.py --season 2026           # 爬 2025-26 赛季
  python crawl_br_gamelog.py --season 2026 --dry-run  # 测试模式
  python crawl_br_gamelog.py --season 2026 --limit 10 # 只爬10人
"""
import requests
from bs4 import BeautifulSoup
import psycopg2
import psycopg2.extras
import time
import random
import argparse
import sys
from datetime import datetime
from pathlib import Path
import tempfile
import shutil
import re
from typing import Optional

# Ensure the project root (three levels up from this file) is on sys.path so
# `import common.browser` resolves when run as a standalone script.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

# cache-first 主球员页缓存: gamelog 走浏览器通道(Playwright + 9222 Chrome),
# 顺手把主球员页 HTML 落盘, 供后续 nickname / bio_ext 爬虫(cache-first, curl 通道)
# 离线抽取, 不再每轮撞 BR 403。详见 common/player_page_cache.py。
import common.player_page_cache as player_page_cache

DB_CONFIG = dict(host='localhost', port=5433, dbname='nba', user='postgres', password=os.environ.get('DB_PASSWORD'))

# ── 缓存冷归档策略配置 (2026-08-11 用户要求：溢出归档不要删除，以防万一) ──
# 冷归档根目录：项目根/raw_archive/gamelog (raw_archive 是 24G 持久归档区，永不清理)。
# ARCHIVE_ON_OVERFLOW: 是否开启冷归档(默认开)；CACHE_OVERFLOW_GB: 本地缓存
#   超此 GB 数触发把最老季双轨迁移到冷档腾空间(不删除)。二者均可被 CLI / 环境变量覆盖。
RAW_ARCHIVE_ROOT = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "raw_archive", "gamelog")
ARCHIVE_ON_OVERFLOW = os.environ.get("ARCHIVE_ON_OVERFLOW", "1") == "1"
CACHE_OVERFLOW_GB = float(os.environ.get("CACHE_OVERFLOW_GB", "20"))

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}

# 渲染进程崩溃（Target crashed）后自动重建页面重试的上限。
# 超过则放弃该球员（按 fetch failed 跳过），避免单个崩溃拖垮整季。
_FETCH_MAX_RETRIES = 3

# BR stat name → DB column name mapping
STAT_MAP = {
    'fg': 'fg', 'fga': 'fga', 'fg_pct': 'fg_pct',
    'fg3': 'fg3', 'fg3a': 'fga3', 'fg3_pct': 'fg3_pct',
    'ft': 'ft', 'fta': 'fta', 'ft_pct': 'ft_pct',
    'orb': 'orb', 'drb': 'drb', 'trb': 'trb',
    'ast': 'ast', 'stl': 'stl', 'blk': 'blk',
    'tov': 'tov', 'pf': 'pf', 'pts': 'pts',
    'plus_minus': 'plus_minus',
}

NUMERIC_STATS = {'fg_pct', 'fg3_pct', 'ft_pct'}


def safe_int(val):
    """Convert BR value to int, returns None for empty/invalid"""
    if val is None or val == '' or val == '*':
        return None
    try:
        return int(val)
    except (ValueError, TypeError):
        return None


def safe_float(val):
    """Convert BR value to float, returns None for empty/invalid"""
    if val is None or val == '':
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def parse_pct(val):
    """Parse FG% format like '.625' → 0.625"""
    if val is None or val == '':
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def get_players(conn, season: int, limit: int = None, resume: bool = False):
    """Get player list from player_per_game for a season.
    If resume=True, skip players that already have gamelog data for this season."""
    cur = conn.cursor()
    
    if resume:
        query = """
            SELECT DISTINCT p.player, p.player_id FROM player_per_game p
            WHERE p.season = %s 
              AND p.player_id IS NOT NULL AND p.player_id <> ''
              AND NOT EXISTS (
                SELECT 1 FROM player_gamelog g 
                WHERE g.player = p.player AND g.season = %s
              )
            ORDER BY p.player
        """
        if limit:
            query += f" LIMIT {limit}"
        cur.execute(query, (season, season))
    else:
        query = """
            SELECT DISTINCT player, player_id FROM player_per_game 
            WHERE season = %s AND player_id IS NOT NULL AND player_id <> ''
            ORDER BY player
        """
        if limit:
            query += f" LIMIT {limit}"
        cur.execute(query, (season,))
    return cur.fetchall()


# --- 队名归一（历史/现代缩写统一到同一 franchise 键，见数据四性铁律）---
# 照搬 reingest_gamelog_from_cache.py 的 ABBR_GROUPS，确保爬取侧映射与回填侧一致：
# dim_games 存现代缩写(BRK/OKC/CHO...)，BR 缓存用历史缩写(NJN/SEA/CHH...)，
# 建映射与查表两侧都先 canon_team 才不漏掉搬迁/改名队。
_ABBR_GROUPS = [
    {'SAS', 'SAN'}, {'GSW', 'GOS'}, {'PHI', 'PHL'}, {'UTA', 'UTH'},
    {'CHA', 'CHO', 'CHH'}, {'NOK', 'NOP', 'NOH'}, {'VAN', 'MEM'},
    {'WSB', 'WAS'}, {'NJN', 'BRK'}, {'SEA', 'OKC'}, {'SDC', 'LAC'}, {'KCK', 'SAC'},
]
_CANON = {}
for _grp in _ABBR_GROUPS:
    _tok = frozenset(_grp)
    for _a in _grp:
        _CANON[_a] = _tok

def canon_team(a):
    """Map a team abbreviation (historical or modern) to a canonical franchise key."""
    return _CANON.get(a, a)


def get_game_id_map(conn, season: int):
    """Build (date, team) -> nba_api_id mapping from dim_games.

    NOTE: player_gamelog.gameid stores the NUMERIC nba_api_id (not the
    alphanumeric games.game_id), so we map via dim_games.nba_api_id.
    BR gamelog pages are regular-season only ('player_game_log_reg').
    """
    cur = conn.cursor()
    cur.execute("""
        SELECT game_date::text, home_team_abbr, away_team_abbr, nba_api_id
        FROM dim_games
        WHERE season = %s AND season_type = 'Regular Season'
          AND nba_api_id IS NOT NULL
    """, (season,))

    mapping = {}
    for row in cur.fetchall():
        date_str, home, away, nba_id = row
        mapping[(date_str, canon_team(home))] = nba_id
        mapping[(date_str, canon_team(away))] = nba_id

    return mapping


def get_game_id_full_map(conn, season: int):
    """Build (date, team) -> alphanumeric game_id mapping from dim_games.

    Unlike :func:`get_game_id_map` (which returns the *numeric* ``nba_api_id``
    stored in ``player_gamelog.gameid``), this returns the *alphanumeric* full
    game id (``dim_games.game_id``, e.g. ``"198511080LAL"``) used to backfill
    ``player_gamelog.game_id_full``.

    Same key shape ``(date, team)`` as ``get_game_id_map`` so callers can look
    up by home or away abbreviation identically. Backward compatible: it is a
    brand-new helper and does not change ``get_game_id_map``'s behavior.
    """
    cur = conn.cursor()
    cur.execute("""
        SELECT game_date::text, home_team_abbr, away_team_abbr, game_id
        FROM dim_games
        WHERE season = %s AND season_type = 'Regular Season'
          AND game_id IS NOT NULL
    """, (season,))

    mapping = {}
    for row in cur.fetchall():
        date_str, home, away, gid = row
        mapping[(date_str, canon_team(home))] = gid
        mapping[(date_str, canon_team(away))] = gid

    return mapping


class BRServerError(Exception):
    """BR 源站返回错误页(如 HTTP 500)或页面未正常渲染。

    这是 BR 服务端故障，与客户端无关：上游应「绕开」——记录该球员 br_id 到
    500 绕开清单，后续直接跳过不再重撞（避免空转烧 IP），且不写入数据。
    verify_gaps 仍会显示该缺口，绝不标「完成」。由 run_pipeline 的 except 捕获处理。
    """
    pass


def _default_bypass_file() -> str:
    """500 绕开清单默认路径：<项目根>/logs/gamelog_500_bypass.txt。"""
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(root, 'logs', 'gamelog_500_bypass.txt')


def _fetch_html(url: str) -> str:
    """Fetch a fully-rendered BR page via the shared driver, with automatic
    recovery from a crashed renderer.

    When the page's renderer crashes mid-scrape (``Target crashed`` /
    ``Target closed`` / connection dropped) the current DOM websocket dies and
    any ``Runtime.evaluate`` raises ``RuntimeError``. Previously that propagated
    to the per-player loop and dropped the player (``ERR: ...``). Now we rebuild
    the driver (fresh page target) and re-navigate — i.e. auto-refresh the page —
    up to ``_FETCH_MAX_RETRIES`` times before giving up on that player.

    Cloudflare-challenge timeouts (``CFChallengeError``) are a site-wide fault,
    not a crash, so they are re-raised untouched (the loop skips the player as
    before, without burning rebuild cycles).
    """
    from common.browser import get_driver, reconnect_driver, CFChallengeError

    # 仅命中「渲染进程确实死亡」的信号才重建页面重试。
    # 刻意不含 "Connection"/"websocket"/"Errno"：内存饥饿导致的
    # HTTP 500 / Connection refused 建不出 target，重建页面治不了，
    # 重试只会空转（用户已明确反对）；故不再静默 skip，而是交由下方
    # 「无表检测」抛 BRServerError → 上层按『失败』计数，杜绝假完成。
    _CRASH_TOKENS = (
        "Target crashed", "Target closed", "Target detached", "Session closed",
    )

    def _is_crash(msg: str) -> bool:
        return any(tok in msg for tok in _CRASH_TOKENS)

    def _rebuild():
        # 重建全局 driver（新 target），失败静默（下次 get_driver 仍会再试）。
        try:
            reconnect_driver()
        except Exception:  # noqa: BLE001
            pass

    last_exc = None
    for attempt in range(1, _FETCH_MAX_RETRIES + 1):
        drv = get_driver()
        try:
            drv.get(url)
            html = drv.page_source
        except CFChallengeError:
            raise  # 站点级 CF 故障：不重试
        except RuntimeError as e:
            if _is_crash(str(e)) and attempt < _FETCH_MAX_RETRIES:
                last_exc = e
                print(f"    ⚠ 渲染进程崩溃({e})，自动重建页面刷新重试 ({attempt}/{_FETCH_MAX_RETRIES})…", flush=True)
                _rebuild()
                time.sleep(2)
                continue
            raise
        except Exception as e:
            if _is_crash(str(e)) and attempt < _FETCH_MAX_RETRIES:
                last_exc = e
                print(f"    ⚠ 抓取异常({e})，自动重建页面刷新重试 ({attempt}/{_FETCH_MAX_RETRIES})…", flush=True)
                _rebuild()
                time.sleep(2)
                continue
            raise
        # 主页已渲染，检测真实表
        if "player_game_log_reg" in html:
            return html
        # Poll up to ~60s for the real table (CF interstitial still clearing).
        for _ in range(12):
            time.sleep(5)
            try:
                html = drv.page_source
            except RuntimeError as e:
                if _is_crash(str(e)) and attempt < _FETCH_MAX_RETRIES:
                    last_exc = e
                    print(f"    ⚠ 轮询中渲染进程崩溃({e})，自动重建页面刷新重试 ({attempt}/{_FETCH_MAX_RETRIES})…", flush=True)
                    _rebuild()
                    break  # 跳出 poll，外层 for 重试整页
                raise
            if "player_game_log_reg" in html:
                return html
        # 无表 → 区分「真实空数据页」与「BR 错误页(500/超时/空白)」。
        # 真实 BR 页面(即便 0 场)必含站点骨架；错误页/空白页不含 → 视为抓取失败，
        # 计为失败而非静默 skip，杜绝「假完成」(输出 0 失败却缺口未补)。
        _BR_CHROME = ("Basketball-Reference.com", 'id="footer"', 'class="navbar"',
                      'id="content"', "stathead")
        _ERR_MARKERS = ("Server Error (500)", "There was an error with this request",
                        "Internal Server Error", "We're sorry, but something went wrong")
        if any(m in html for m in _ERR_MARKERS):
            raise BRServerError(f"BR 返回错误页(疑似500): {url}")
        if not any(c in html for c in _BR_CHROME):
            raise BRServerError(f"BR 页面未正常渲染(无站点骨架, 疑似500/超时): {url}")
        return html  # 真实空数据页：调用方按 skip 处理
    print(f"    ⚠ target 反复崩溃，放弃该球员 (last: {last_exc})", flush=True)
    raise BRServerError(f"渲染进程反复崩溃, 放弃该球员: {url} (last: {last_exc})")


def parse_gamelog_html(html: str) -> list:
    """Parse a BR player gamelog HTML page into a list of game dicts.

    Pure function — takes raw HTML, returns structured games. Extracted from
    :func:`scrape_gamelog` so the parse layer can be unit-tested without a
    browser/network. Looks for the ``player_game_log_reg`` table and reads each
    row's ``data-stat`` attributes.

    Args:
        html: Rendered HTML of a BR ``/gamelog/<season>`` page (must contain the
            ``player_game_log_reg`` table).

    Returns:
        List of game dicts with keys: ``date``, ``team``, ``opp``,
        ``is_starter``, and one entry per stat in :data:`STAT_MAP`.
    """
    if not html:
        return []

    soup = BeautifulSoup(html, 'html.parser')
    table = soup.find('table', id='player_game_log_reg')
    if not table:
        return []

    rows = table.find_all('tr')
    games = []

    for row in rows:
        # Skip header rows (thead class)
        cls = row.get('class', [])
        if 'thead' in cls:
            continue

        tds = row.find_all(['th', 'td'])
        vals = {td.get('data-stat', ''): td.get_text(strip=True) for td in tds}

        # Skip summary rows (no ranker value or ranker is header)
        ranker = vals.get('ranker', '')
        if not ranker or ranker == 'Rk':
            continue

        # Skip inactive games
        starter = vals.get('is_starter', '')
        if starter == 'Inactive' or starter == 'Did Not Play' or starter == 'Did Not Dress':
            continue

        date_str = vals.get('date', '')
        team = vals.get('team_name_abbr', '')

        if not date_str:
            continue

        game = {
            'date': date_str,
            'team': team,
            'opp': vals.get('opp_name_abbr', ''),
            'is_starter': (starter == '*'),
        }

        # Map stats
        for br_stat, db_col in STAT_MAP.items():
            raw = vals.get(br_stat, '')
            if db_col in NUMERIC_STATS:
                game[db_col] = parse_pct(raw)
            else:
                game[db_col] = safe_int(raw)

        # MP (minutes played) is a "M:SS" string stored verbatim in the
        # varchar `minutes` column — must NOT go through safe_int (it would
        # return None for non-numeric "M:SS"). BR's data-stat for this cell is "mp".
        mp_raw = vals.get('mp', '')
        game['minutes'] = mp_raw if mp_raw else None

        games.append(game)

    return games


# ═══════════════════════════════════════════════════════════════════════════
# 双轨缓存 · HTML 轨道
# ───────────────────────────────────────────────────────────────────────────
# 背景：旧缓存只存解析结果(gamelog_<season>.json)，一旦解析器漏抽字段
# (如季后赛 minutes)，原始值已丢、重放缓存也补不回。故新增 HTML 轨道存
# 浏览器渲染后的原始页面，使「改解析器后免重爬重解」能恢复丢字段。
#   JSON 轨道: gamelog_<season>.json + .part.jsonl  (解析结果，索引/兜底，MERGE 语义)
#   HTML 轨道: <cache_dir>/html/<season>/<首字母>/<player_id>.html  (原始页面，权威源)
# 两轨并存：rework / cache-first 优先从 HTML 重解；HTML 缺失时回退 JSON。
# ═══════════════════════════════════════════════════════════════════════════

def gamelog_html_path(season: int, player_id: str, cache_dir: str) -> str:
    """返回某球员某季 gamelog 原始 HTML 的缓存路径。"""
    if not player_id:
        return os.path.join(cache_dir, "html", str(season), "_bad", "empty.html")
    first = player_id[0].lower()
    return os.path.join(cache_dir, "html", str(season), first, f"{player_id}.html")


def save_gamelog_html(season: int, player_id: str, html: str, cache_dir: str) -> bool:
    """原子写 gamelog 原始 HTML 到双轨缓存的 HTML 轨道。

    失败 / 空 / CF 挑战页 / 残页 / 非 gamelog 页 → 不写(返回 False)，绝不污染缓存。
    成功返回 True。供 ``scrape_gamelog`` 在抓取成功后落盘(与 JSON 轨道并行)。
    """
    if not cache_dir or not player_id or not html:
        return False
    low = html.lower()
    # 轻量有效性判据：确信是正常 gamelog 页才存。
    if len(html) < 20000 or "just a moment" in low:
        return False
    if "player_game_log_reg" not in html:
        return False
    dest = gamelog_html_path(season, player_id, cache_dir)
    try:
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        # 临时文件与最终文件同目录 → os.replace 原子改名(同文件系统)
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(dest), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(html)
            os.replace(tmp, dest)
        finally:
            if os.path.exists(tmp):
                try:
                    os.remove(tmp)
                except OSError:
                    pass
    except OSError:
        return False
    return True


def load_gamelog_html(season: int, player_id: str, cache_dir: str) -> Optional[str]:
    """读取缓存的 gamelog 原始 HTML；未命中 / 空文件 → None。"""
    if not cache_dir or not player_id:
        return None
    p = gamelog_html_path(season, player_id, cache_dir)
    try:
        if os.path.exists(p) and os.path.getsize(p) > 0:
            return open(p, encoding="utf-8", errors="replace").read()
    except OSError:
        return None
    return None


def has_gamelog_html(season: int, player_id: str, cache_dir: str) -> bool:
    """该球员该季 gamelog HTML 是否已缓存(文件存在且 >0 字节)。"""
    if not cache_dir or not player_id:
        return False
    p = gamelog_html_path(season, player_id, cache_dir)
    try:
        return os.path.exists(p) and os.path.getsize(p) > 0
    except OSError:
        return False


# ═══════════════════════════════════════════════════════════════════════════
# 缓存冷归档策略 (2026-08-11 用户要求：溢出时归档不要删除，以防万一)
# ───────────────────────────────────────────────────────────────────────────
# 背景：Chrome 100MB 磁盘缓存(--disk-cache-size)是「传输层」单一不透明池，存
#   HTTP 响应(HTML/JSON/图片混在一起)，满了按 LRU 内部直接删除且无法挂钩「删前
#   归档」；它**不存用户数据**，溢出只丢传输中间体，与源数据无关。用户真正的
#   JSON + 网页数据在爬虫「双轨缓存」(gamelog_cache)：
#     · JSON 轨道  gamelog_<season>.json + .part.jsonl
#     · HTML 轨道  html/<season>/<首字母>/<player_id>.html (原始页面, 权威源)
#   双轨默认永不自动删。本策略在其上再加「溢出冷归档」显式保障：
#     · archive_season_cold     —— 每季跑完把双轨**复制**到 raw_archive/gamelog/<season>/，
#       本地仍留(秒级 rework)，冷档为「以防万一」额外副本。
#     · enforce_overflow_policy —— 本地缓存超 CACHE_OVERFLOW_GB 时，把最老季双轨
#       **移动**到冷归档腾空间(不删除，数据仍可追溯)。
# 归档格式(用户授权我决定)：JSON 轨道 + HTML 原始页 双轨皆归档。
# ═══════════════════════════════════════════════════════════════════════════

def _cache_size_bytes(path: str) -> int:
    """递归统计目录占用字节数(容错单文件 stat 失败)。"""
    total = 0
    try:
        for root, _d, files in os.walk(path):
            for fn in files:
                try:
                    total += os.path.getsize(os.path.join(root, fn))
                except OSError:
                    pass
    except OSError:
        pass
    return total


def _count_files(path: str) -> int:
    """递归统计目录下文件总数(容错)。"""
    n = 0
    try:
        for _root, _d, files in os.walk(path):
            n += len(files)
    except OSError:
        pass
    return n


def archive_season_cold(season: int, cache_dir: str, raw_root: str = None) -> bool:
    """本季双轨缓存(JSON + HTML 原始页)冷归档到 raw_archive/gamelog/<season>/。

    采用**复制**(非移动)：本地 gamelog_cache 仍保留可秒级 rework；冷档是
    「以防万一」的额外副本。已归档则幂等跳过。返回是否产生新归档。
    受 ARCHIVE_ON_OVERFLOW 总开关控制。
    """
    if not ARCHIVE_ON_OVERFLOW:
        return False
    raw_root = raw_root or RAW_ARCHIVE_ROOT
    if not cache_dir or not os.path.isdir(cache_dir):
        return False
    src_html = os.path.join(cache_dir, "html", str(season))
    src_json = os.path.join(cache_dir, f"gamelog_{season}.json")
    src_part = os.path.join(cache_dir, f"gamelog_{season}.part.jsonl")
    dst = os.path.join(raw_root, str(season))
    dst_html = os.path.join(dst, "html")
    src_html_n = _count_files(src_html)
    dst_html_n = _count_files(dst_html)
    dst_has_json = os.path.exists(os.path.join(dst, f"gamelog_{season}.json"))
    # 智能跳过：已归档且 html 已追平源(或源本就无 html) → 视为完整, 跳过。
    # 源后续补齐 html 时(dst_html_n < src_html_n)会刷新补全, 不漏归档。
    if dst_has_json and (src_html_n == 0 or dst_html_n >= src_html_n):
        return False
    have = src_html_n > 0 or os.path.exists(src_json) or os.path.exists(src_part)
    if not have:
        return False
    try:
        os.makedirs(dst, exist_ok=True)
        if os.path.isdir(src_html):
            shutil.copytree(src_html, os.path.join(dst, "html"), dirs_exist_ok=True)
        for src in (src_json, src_part):
            if os.path.exists(src):
                shutil.copy2(src, os.path.join(dst, os.path.basename(src)))
        print(f"    [冷归档] 本季双轨已复制到 {dst} (JSON+HTML, 以防万一)")
        return True
    except OSError as exc:
        print(f"    [冷归档] 失败(不影响主流程): {exc}", file=sys.stderr)
        return False


def enforce_overflow_policy(cache_dir: str, raw_root: str = None) -> None:
    """本地缓存超 CACHE_OVERFLOW_GB 时，把最老季双轨 MOVE 到冷归档腾空间。

    仅归档(移动)不删除：数据从本地 gamelog_cache 迁到 raw_archive/gamelog/<season>/，
    仍可追溯。ARCHIVE_ON_OVERFLOW 关闭则不动作。
    """
    if not ARCHIVE_ON_OVERFLOW:
        return
    raw_root = raw_root or RAW_ARCHIVE_ROOT
    if not cache_dir or not os.path.isdir(cache_dir):
        return
    threshold = CACHE_OVERFLOW_GB * 1_000_000_000
    try:
        if _cache_size_bytes(cache_dir) <= threshold:
            return
    except OSError:
        return
    html_root = os.path.join(cache_dir, "html")
    seasons: list[int] = []
    if os.path.isdir(html_root):
        for name in os.listdir(html_root):
            if name.isdigit():
                seasons.append(int(name))
    for fn in os.listdir(cache_dir):
        m = re.match(r"gamelog_(\d{4})\.json$", fn)
        if m and int(m.group(1)) not in seasons:
            seasons.append(int(m.group(1)))
    seasons.sort()
    moved = 0
    for season in seasons:
        if _cache_size_bytes(cache_dir) <= threshold:
            break
        dst_season = os.path.join(raw_root, str(season))
        if os.path.isdir(dst_season) and any(os.scandir(dst_season)):
            continue  # 该季已归档过
        try:
            os.makedirs(dst_season, exist_ok=True)
            src_html = os.path.join(html_root, str(season))
            if os.path.isdir(src_html):
                shutil.move(src_html, os.path.join(dst_season, "html"))
            for fn in (f"gamelog_{season}.json", f"gamelog_{season}.part.jsonl"):
                src = os.path.join(cache_dir, fn)
                if os.path.exists(src):
                    shutil.move(src, os.path.join(dst_season, fn))
            print(f"    [溢出归档] 季 {season} 双轨已移至冷归档 {dst_season} (释放本地, 不删除)")
            moved += 1
        except OSError as exc:
            print(f"    [溢出归档] 季 {season} 失败: {exc}", file=sys.stderr)
            break
    if moved:
        print(f"    [溢出归档] 共迁移 {moved} 季到冷归档(本地缓存回落至阈值内)")


def scrape_gamelog(player_name: str, player_id: str, season: int,
                   cache_dir: str = None, force_fetch: bool = False) -> list:
    """Scrape one player's gamelog from BR (browser-backed), dual-track cached.

    Dual-track: the raw rendered HTML is saved to the HTML track
    (<cache_dir>/html/<season>/<player_id>.html) on every successful fetch, and
    reused cache-first on subsequent runs (unless ``force_fetch``) so a later
    parser fix can re-extract dropped fields (e.g. playoff minutes) without
    re-hitting BR. The parsed JSON track (handled by run_pipeline / rework) is
    the index/fallback.
    """
    first_letter = player_id[0].lower()
    url = f"https://www.basketball-reference.com/players/{first_letter}/{player_id}/gamelog/{season}"

    # ── cache-first 主球员页: gamelog 走浏览器通道, 顺手把主球员页 HTML
    # 落盘(含绰号 FAQ / #bling 荣誉 / 亲属), 供 nickname / bio_ext 爬虫离线抽。
    # 仅在未缓存时额外导航一次; 命中 CF 挑战页则跳过(不污染缓存)。
    if not player_page_cache.is_cached(player_id):
        first = player_id[0].lower()
        main_url = f"https://www.basketball-reference.com/players/{first}/{player_id}.html"
        try:
            from common.browser import get_driver
            drv = get_driver()
            drv.get(main_url)
            html_main = drv.page_source
            if html_main and "Just a moment" not in html_main:
                if player_page_cache.save_html(player_id, html_main):
                    print(f"    主球员页已缓存", end=' ')
        except Exception as exc:
            print(f"    主球员页缓存失败(不影响gamelog): {exc}", end=' ')

    # ── 双轨 · HTML 轨道 cache-first 读取(免重爬) ──
    # 已缓存本季本球员原始 HTML 且非 CF/残页 → 本地重解返回，不碰 BR。
    if cache_dir and not force_fetch and has_gamelog_html(season, player_id, cache_dir):
        html = load_gamelog_html(season, player_id, cache_dir)
        if html and "player_game_log_reg" in html:
            return parse_gamelog_html(html)
        # 缓存损坏/非预期 → 落入下方线上抓取兜底

    html = _fetch_html(url)
    if not html:
        print(f"    fetch failed")
        return []

    # 双轨落盘：抓取成功即存原始 HTML(供后续改解析器免重爬恢复丢字段)
    if cache_dir:
        save_gamelog_html(season, player_id, html, cache_dir)

    return parse_gamelog_html(html)


def _gamelog_part_path(season: int, cache_dir: str) -> str:
    """本季"增量分片"文件路径（JSONL，每行一个球员条目）。

    存在的意义：``merge_gamelog_cache`` 只在整季跑完时调用一次，一旦中途被
    CF 墙熔断 / 看门狗重启 / SIGKILL 打断，内存里的 ``season_cache`` 会全部
    丢失、缓存文件永远写不出来（历史上 2026 季反复爬了多轮而 ``gamelog_cache``
    始终是空目录，根因即此）。分片文件让每爬完一个球员就立刻落盘一行，
    实现"崩溃零丢失"。
    """
    return os.path.join(cache_dir, f"gamelog_{season}.part.jsonl")


def append_gamelog_part(season: int, cache_dir: str, entry: dict) -> None:
    """把单个球员条目实时追加到本季分片文件（O(1) 追加，开销极小）。

    绝不抛异常：缓存是"锦上添花"，任何 IO 问题都不允许中断爬取主流程。
    """
    try:
        os.makedirs(cache_dir, exist_ok=True)
        with open(_gamelog_part_path(season, cache_dir), "a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
            fh.flush()
            os.fsync(fh.fileno())  # 强制落盘，防 SIGKILL 时数据仍留在页缓存
    except Exception:
        pass


def _read_gamelog_part(part_path: str) -> list:
    """读回分片文件里的球员条目；逐行容错（半截行/坏行直接跳过）。"""
    out = []
    if not os.path.exists(part_path):
        return out
    try:
        with open(part_path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except (json.JSONDecodeError, ValueError):
                    continue  # 被 kill 截断的最后一行 → 丢弃该行即可
                if isinstance(obj, dict):
                    out.append(obj)
    except OSError:
        pass
    return out


def merge_gamelog_cache(season: int, new_players: list, cache_dir: str) -> str:
    """读取旧缓存(若存在且有效) + 合并 new_players(按 player_id 去重覆盖) + 整体回写。

    该函数的语义是 MERGE 而非 OVERWRITE：在写某季缓存前，先尝试读取已存在的
    ``gamelog_<season>.json``；将旧缓存的 players 与本轮回新抓的 players 按
    ``player_id`` 合并（相同 player_id 以新抓覆盖旧，不同则追加），再整体回写。
    这样在 ``--resume`` 模式下缓存文件不会被削成"仅本轮回新抓的球员"。

    容错策略（绝不让脚本因缓存问题崩溃）：
      - 旧缓存文件不存在 → 当作空缓存，直接写入 new_players；
      - 旧缓存 JSON 损坏/半截（如被中途 kill 截断）→ 捕获 JSONDecodeError，
        当作空缓存处理；
      - 旧缓存结构异常（非 dict、缺 ``players`` 键、``players`` 非 list 等）→
        同样容错当作空缓存。

    Args:
        season: 赛季结束年（如 1995 表示 1994-95 赛季），用于构造文件名。
        new_players: 本轮回新抓的球员列表，元素形如
            ``{"player": <name>, "player_id": <pid>, "games": [...]}``。
        cache_dir: 缓存目录，不存在时自动创建。

    Returns:
        写入后的缓存文件绝对/相对路径。
    """
    os.makedirs(cache_dir, exist_ok=True)
    out_path = os.path.join(cache_dir, f"gamelog_{season}.json")
    part_path = _gamelog_part_path(season, cache_dir)

    # 0) 吸收上一轮遗留的增量分片（上次跑到一半被打断时实时落盘的球员）。
    #    这保证"崩溃过的那一轮"抓到的数据不会白费，下次运行自动回收。
    part_players = _read_gamelog_part(part_path)

    # 1) 读取旧缓存（多重容错：不存在 / 损坏 / 结构异常 → 当作空）。
    old_players: list = []
    if os.path.exists(out_path):
        try:
            with open(out_path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            if isinstance(data, dict):
                old_players = data.get("players") or []
            if not isinstance(old_players, list):
                old_players = []
        except (json.JSONDecodeError, ValueError, OSError):
            # 损坏/半截/无法读取 → 视为空缓存，绝不让脚本崩溃。
            old_players = []

    # 2) 按 player_id 合并：新抓覆盖同 player_id 的旧条目（保留旧位置）；
    #    无 player_id 的条目用唯一键保留，避免被静默丢弃。
    no_id_counter = 0

    def _key(entry: object):
        nonlocal no_id_counter
        pid = entry.get("player_id") if isinstance(entry, dict) else None
        if pid is not None:
            return ("id", pid)
        no_id_counter += 1
        return ("noid", no_id_counter)

    #    优先级：旧缓存 < 遗留分片 < 本轮新抓（越新越优先覆盖同 player_id）。
    merged: dict = {}
    for entry in old_players:
        merged[_key(entry)] = entry
    for entry in part_players:
        merged[_key(entry)] = entry  # 上次被打断那轮实时落盘的数据
    for entry in new_players:
        merged[_key(entry)] = entry  # 新抓覆盖同 player_id 的旧条目

    merged_players = list(merged.values())

    # 3) 整体回写（MERGE 结果）。先写临时文件再原子 rename，
    #    避免正好在回写途中被 kill 导致主缓存文件被截断成半截 JSON。
    tmp_path = out_path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as fh:
        json.dump(
            {"season": season, "players": merged_players},
            fh,
            ensure_ascii=False,
            indent=1,
        )
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp_path, out_path)

    # 4) 分片已安全并入主缓存 → 清理，避免下轮重复吸收、无限膨胀。
    try:
        if os.path.exists(part_path):
            os.remove(part_path)
    except OSError:
        pass

    return out_path


def load_player_id_bridge(conn) -> dict:
    """br_player_id -> nba_player_id（int）。

    供 :func:`build_insert` 把 NBA 数字球员 id 写进 ``player_gamelog.player_id``
    / ``nba_player_id``。BR 爬虫此前**从不写这两列**（只写 ``br_player_id`` +
    ``gameid``），导致 2024/2026 等纯 BR 爬取季的 NBA 数字球员 id 全 NULL。

    去重：``player_id_bridge`` 同一 ``br_player_id`` 可能有多行，用
    ``DISTINCT ON`` 取一个稳定的 nba_player_id。
    """
    mapping: dict = {}
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT DISTINCT ON (br_player_id) br_player_id, nba_player_id "
            "FROM player_id_bridge WHERE nba_player_id IS NOT NULL "
            "ORDER BY br_player_id, nba_player_id"
        )
        for br, nba in cur.fetchall():
            if br and nba is not None:
                mapping[br] = int(nba)
        cur.close()
    except Exception:
        pass
    return mapping


def build_insert(player_name: str, player_id: str, g: dict, game_id_full: str = None,
                nba_player_id: int = None) -> tuple:
    """Build the (columns, values) tuple for a single player_gamelog INSERT.

    Pure function (no DB access) so the column/value alignment can be unit-tested
    without connecting to Postgres. Both :func:`run_pipeline` and
    :func:`rework_season` call it, eliminating the previously duplicated INSERT
    construction and guaranteeing the two write paths stay in sync.

    Args:
        player_name: Display name of the player; also written to ``player_name``.
        player_id: BR string id (e.g. ``"abbrd03"``); written to ``br_player_id``.
        g: Parsed game dict. Must carry ``game_id`` (numeric ``nba_api_id`` as a
            string), ``team``, ``season``, and the stat fields from
            :data:`STAT_MAP`. The caller is responsible for setting ``game_id``
            (e.g. from ``get_game_id_map``) before calling.
        game_id_full: Alphanumeric full game id (``dim_games.game_id``), or
            ``None`` when the mapping is missing.
        nba_player_id: NBA numeric player id (int), looked up from
            ``player_id_bridge`` by ``br_player_id``; written to the
            ``nba_player_id`` column only. The ``player_id`` column is written
            with the BR slug (``player_id`` arg) to match ``br_player_id``
            (user 2026-08-07: BR slug is the authoritative player id).
            ``None`` when unknown (historical BR-only rows had this missing).

    Returns:
        ``(columns, values)`` — two tuples of identical length (29). ``created_at``
        is intentionally excluded; callers append it as ``NOW()`` in the SQL.
    """
    columns = (
        'gameid', 'player', 'team', 'season',
        'br_player_id', 'player_name', 'game_id_full',
        'player_id', 'nba_player_id',
        'fg', 'fga', 'fg_pct', 'fg3', 'fga3', 'fg3_pct',
        'ft', 'fta', 'ft_pct', 'orb', 'drb', 'trb', 'ast', 'stl', 'blk',
        'tov', 'pf', 'pts', 'plus_minus', 'minutes',
    )
    values = (
        g.get('game_id'),
        player_name,
        g.get('team'),
        g.get('season'),
        player_id,
        player_name,
        game_id_full,
        player_id,
        nba_player_id,
        g.get('fg'), g.get('fga'), g.get('fg_pct'),
        g.get('fg3'), g.get('fga3'), g.get('fg3_pct'),
        g.get('ft'), g.get('fta'), g.get('ft_pct'),
        g.get('orb'), g.get('drb'), g.get('trb'),
        g.get('ast'), g.get('stl'), g.get('blk'),
        g.get('tov'), g.get('pf'), g.get('pts'),
        g.get('plus_minus'), g.get('minutes'),
    )
    return columns, values


def delete_existing(cur, game_id: str, br_player_id: str, player_name: str) -> None:
    """Idempotent delete for one (game, player) before re-inserting.

    【2026-08-05 根因修复】原实现两处写入路径都用 ``WHERE gameid=%s AND player=%s``,
    去重键是**名字字符串**而非 id。历史上同一人在不同批次被写成三种形态
    (``Varejao`` / ``A. Varejao`` / ``Anderson Varejao``), 名字键互相删不掉,
    导致同场同人并存 3 份 (全表约 2 倍膨胀)。

    正确的身份键是 ``br_player_id`` (BR slug), 与 ``dim_players.player_id`` 同域。
    这里额外保留一条名字兜底: 仅当既有行 ``br_player_id IS NULL`` (即无身份的历史
    残渣) 且全名相同时才一并清除 —— 这样重爬能顺带清掉老脏行, 又不会误删另一个
    有明确 slug 的同名球员。

    Args:
        cur: 打开的 psycopg2 cursor。
        game_id: ``player_gamelog.gameid`` (数字 id 的字符串形式)。
        br_player_id: BR slug; 为空时退化为纯名字键 (仅兜底, 正常路径不会为空)。
        player_name: 球员全名。
    """
    if br_player_id:
        cur.execute(
            "DELETE FROM player_gamelog "
            "WHERE gameid = %s "
            "  AND (br_player_id = %s OR (br_player_id IS NULL AND player = %s))",
            (game_id, br_player_id, player_name),
        )
    else:
        # 没有 slug 时无法按身份幂等, 只能退回名字键 (保持旧行为)。
        cur.execute(
            "DELETE FROM player_gamelog WHERE gameid = %s AND player = %s",
            (game_id, player_name),
        )


def run_pipeline(season: int, limit: int = None, dry_run: bool = False,
                resume: bool = False, cache_dir: str = None, only_br_ids=None,
                bypass_file=None, force_fetch: bool = False):
    """Main pipeline.

    cache_dir: 若设置，本季爬完将整季解析结果落盘为
    <cache_dir>/gamelog_<season>.json，供返工免重爬重放（--rework）。
    only_br_ids: 若设置（br_player_id 列表），只爬这些球员（智能补齐缺口）。
    """
    conn = psycopg2.connect(**DB_CONFIG)

    # 本季本地缓存收集（返工安全）
    season_cache = []

    # ── 限速配置（env 可覆盖；默认已偏保守以防 BR 限流 / CF 墙）──
    CRAWL_DELAY_MIN = float(os.environ.get('CRAWL_DELAY_MIN', '6'))
    CRAWL_DELAY_MAX = float(os.environ.get('CRAWL_DELAY_MAX', '10'))
    CRAWL_LONG_EVERY = int(os.environ.get('CRAWL_LONG_EVERY', '20'))
    CRAWL_LONG_SLEEP = float(os.environ.get('CRAWL_LONG_SLEEP', '30'))

    # Get players
    # only_br_ids 模式：强制基于全量列表过滤（resume 会漏掉「有部分数据」的缺口球员）
    players = get_players(conn, season, limit, resume and not only_br_ids)
    if only_br_ids:
        wanted = set(only_br_ids)
        players = [p for p in players if p[1] in wanted]
        print(f"共 {len(players)} 名缺口球员需要补齐 (only_br_ids)")
    elif resume:
        already_done = sum(1 for _ in get_players(conn, season)) - len(players)
        print(f"共 {len(players)} 名球员需要爬取 ({already_done} 已跳过)")
    
    # Build game_id mappings: numeric nba_api_id (for player_gamelog.gameid)
    # and alphanumeric full game id (for player_gamelog.game_id_full).
    game_map = get_game_id_map(conn, season)
    game_id_full_map = get_game_id_full_map(conn, season)
    bridge_map = load_player_id_bridge(conn)
    print(f"game_id 映射: {len(game_map)} 条, game_id_full 映射: {len(game_id_full_map)} 条 (赛季 {season})")
#   Inactive status values to skip
    skip_statuses = {'Inactive', 'Did Not Play', 'Did Not Dress', 'Not With Team', 'Inactive'}
    
    total_games = 0
    success = 0
    failed = 0
    skipped_players = 0
    bypassed_count = 0   # BR 源站 500 绕开数（不计入 failed，避免空转重试烧 IP）
    # ── 500 绕开清单：BR 返回 500 的球员 br_id 记入此文件，后续直接跳过不再重撞 ──
    bypass_path = bypass_file or _default_bypass_file()
    bypass_set = set()
    if os.path.exists(bypass_path):
        with open(bypass_path) as _bf:
            bypass_set = {l.strip() for l in _bf if l.strip()}
    # ── 丢弃计数（防「静默丢弃 + 假成功 ✓」复发）──
    # 任何一场因 dim_games 无 nba_api_id 映射而无法入库的比赛都必须被计数，
    # 并在行尾 / 结尾汇总里显式打印，否则整季静默少一大截仍然显示全 ✓。
    total_dropped = 0
    dropped_keys = {}   # (date, team) -> 次数，用于结尾列出前若干个缺映射日期
    
    for i, (player_name, player_id) in enumerate(players):
        if not player_id:
            print(f"[{i+1}/{len(players)}] {player_name} (None) → 跳过 (无 player_id)")
            skipped_players += 1
            continue
        if player_id in bypass_set:
            print(f"[{i+1}/{len(players)}] {player_name} ({player_id}) → 绕开 (已记录 BR 500, 跳过重撞)")
            bypassed_count += 1
            continue
        print(f"[{i+1}/{len(players)}] {player_name} ({player_id})...", end=' ', flush=True)
        
        try:
            games = scrape_gamelog(player_name, player_id, season, cache_dir=cache_dir, force_fetch=force_fetch)
            
            if not games:
                print(f"0 场 (skip)")
                skipped_players += 1
            else:
                inserted = 0
                dropped = 0
                for g in games:
                    date_str = g['date']
                    team = g['team']
                    game_id = game_map.get((date_str, canon_team(team)))

                    if not game_id:
                        # Try with opponent team (away games)
                        game_id = game_map.get((date_str, canon_team(g.get('opp', ''))))

                    if not game_id:
                        # 【禁止静默丢弃】dim_games 该场无 nba_api_id → 无法入库。
                        # 必须计数并暴露，绝不能悄悄 continue 后仍打印 ✓。
                        dropped += 1
                        total_dropped += 1
                        dropped_keys[(date_str, team)] = dropped_keys.get((date_str, team), 0) + 1
                        continue
                    game_id = str(game_id)  # player_gamelog.gameid is varchar

                    # Alphanumeric full game id (dim_games.game_id).
                    game_id_full = game_id_full_map.get((date_str, canon_team(team)))
                    if not game_id_full:
                        game_id_full = game_id_full_map.get((date_str, canon_team(g.get('opp', ''))))
                    game_id_full = str(game_id_full) if game_id_full else None

                    # Stamp the resolved ids onto the game dict so build_insert
                    # has everything it needs in one place.
                    g['game_id'] = game_id
                    g['season'] = season
                    columns, values = build_insert(player_name, player_id, g, game_id_full,
                                                    nba_player_id=bridge_map.get(player_id))

                    if not dry_run:
                        # UPSERT: DELETE then INSERT (身份键 = br_player_id, 见 delete_existing)
                        cur = conn.cursor()
                        delete_existing(cur, game_id, player_id, player_name)

                        col_sql = ", ".join(columns)
                        placeholder_sql = ", ".join(["%s"] * len(columns))
                        cur.execute(
                            f"INSERT INTO player_gamelog ({col_sql}, created_at) "
                            f"VALUES ({placeholder_sql}, NOW())",
                            values,
                        )
                        cur.close()
                    
                    inserted += 1
                
                if dry_run:
                    conn.rollback()
                else:
                    conn.commit()
                
                if dropped:
                    print(f"{inserted} 场入库 / {dropped} 场丢弃(无nba_api_id) ⚠")
                else:
                    print(f"{inserted} 场 ✓")
                total_games += inserted
                success += 1
                # 收集到本季缓存（仅非空场，供 --rework 返工重放）
                _cache_entry = {
                    "player": player_name,
                    "player_id": player_id,
                    "games": games,
                }
                season_cache.append(_cache_entry)
                # ★ 实时落盘：每爬完一个球员立刻追加一行到分片文件。
                #   不能只依赖循环结束后的 merge_gamelog_cache —— 一旦中途被
                #   CF 熔断 / 看门狗重启 / SIGKILL 打断，内存里的 season_cache
                #   会全部丢失，缓存永远写不出来（这正是 gamelog_cache 长期
                #   为空目录的根因）。
                if cache_dir and not dry_run:
                    append_gamelog_part(season, cache_dir, _cache_entry)
        
        except Exception as e:
            if isinstance(e, BRServerError):
                # BR 源站 500：绕开，记录到清单，不计入 failed（避免空转重试烧 IP）
                try:
                    with open(bypass_path, 'a') as _bf:
                        if player_id not in bypass_set:
                            _bf.write(player_id + "\n")
                except OSError:
                    pass
                bypass_set.add(player_id)
                bypassed_count += 1
                print(f"ERR: BRServerError(500, 绕开不再重撞): {e}")
            else:
                print(f"ERR: {e}")
                failed += 1
            conn.rollback()
        
        # Rate limiting: configurable delay between players (default 6-10s).
        if i < len(players) - 1:
            delay = CRAWL_DELAY_MIN + random.uniform(0, max(0.0, CRAWL_DELAY_MAX - CRAWL_DELAY_MIN))
            time.sleep(delay)
            # Periodic long pause to further throttle request rate.
            if (i + 1) % CRAWL_LONG_EVERY == 0:
                print(f"  [rate-limit] 长休 {CRAWL_LONG_SLEEP}s (已爬 {i + 1} 人)")
                time.sleep(CRAWL_LONG_SLEEP)
    
    print(f"\n{'='*50}")
    print(f"完成! {success} 成功, {failed} 失败, {skipped_players} 跳过, {bypassed_count} 绕开(500)")
    print(f"共写入 {total_games} 场比赛")
    # ── 丢弃汇总（必须显式打印，即使为 0）──
    print(f"丢弃 {total_dropped} 场 (dim_games 无 nba_api_id 映射)")
    if total_dropped:
        print(f"!! 警告: 本季 {total_dropped} 场因缺 nba_api_id 未入库 —— "
              f"这些数据【没有】进库，请先修 dim_games.nba_api_id 再重跑本季。")
        worst = sorted(dropped_keys.items(), key=lambda kv: -kv[1])[:15]
        print(f"   缺映射 (date, team) 前 {len(worst)} 项 "
              f"(共 {len(dropped_keys)} 个不同键):")
        for (d, t), n in worst:
            print(f"     {d}  {t}  x{n}")

    # ── 本季本地缓存（返工安全：可免重爬重放）──
    # 注意：这里使用 MERGE 语义（merge_gamelog_cache）而非 OVERWRITE，
    # 以免 --resume 模式下把整季缓存削成"仅本轮回新抓的球员"。
    if cache_dir and not dry_run:
        out_path = merge_gamelog_cache(season, season_cache, cache_dir)
        print(f"已缓存本季到 {out_path} (本轮回 {len(season_cache)} 球员, MERGE 写入)")
        # 冷归档：① 本季双轨复制一份到 raw_archive(以防万一)；② 本地超阈值则把最老季迁冷档
        archive_season_cold(season, cache_dir)
        enforce_overflow_policy(cache_dir)

    conn.close()


def rework_season(season: int, cache_dir: str) -> None:
    """从本地双轨缓存重放本季 gamelog 到 DB（免重爬，用于返工/修正）。

    双轨优先策略：对每个球员，若 HTML 轨道存在且为有效 gamelog 页，则
    **重解原始 HTML**（用当前解析器，可恢复此前漏抽的字段如季后赛 minutes）；
    否则回退 JSON 轨道的 ``games``。两轨都没有则跳过。

    同时把「JSON 未收录、但 HTML 轨道有」的球员也纳入重放，防止 JSON 缓存
    万一丢失后无法恢复。依赖 dim_games 的 game_id 映射不变。
    """
    import json, os
    # 先把上次被打断时留下的增量分片并入主缓存（保持原行为）。
    if os.path.exists(_gamelog_part_path(season, cache_dir)):
        merge_gamelog_cache(season, [], cache_dir)
        print(f"[rework] 已并入遗留增量分片 gamelog_{season}.part.jsonl")

    # JSON 轨道玩家索引(name 兜底)
    json_path = os.path.join(cache_dir, f"gamelog_{season}.json")
    players_from_json: dict = {}
    if os.path.exists(json_path):
        try:
            with open(json_path, encoding="utf-8") as fh:
                data = json.load(fh)
            for p in data.get("players", []):
                pid = p.get("player_id")
                if pid:
                    players_from_json[pid] = p
        except (json.JSONDecodeError, ValueError, OSError):
            pass

    # 构建重放工作表 (player_id, player_name)：JSON + HTML 双轨并集
    seen: set = set()
    worklist = []
    for pid, p in players_from_json.items():
        if pid not in seen:
            seen.add(pid)
            worklist.append((pid, p.get("player")))
    # HTML 轨道独有球员(防 JSON 丢失后仍能恢复)
    html_season_dir = os.path.join(cache_dir, "html", str(season))
    if os.path.isdir(html_season_dir):
        for first_dir in os.listdir(html_season_dir):
            d = os.path.join(html_season_dir, first_dir)
            if not os.path.isdir(d):
                continue
            for fn in os.listdir(d):
                if fn.endswith(".html"):
                    pid = fn[:-5]
                    if pid and pid not in seen:
                        seen.add(pid)
                        worklist.append((pid, None))

    if not worklist:
        print(f"[rework] 双轨缓存均为空: season {season}")
        return

    conn = psycopg2.connect(**DB_CONFIG)
    game_map = get_game_id_map(conn, season)
    game_id_full_map = get_game_id_full_map(conn, season)
    bridge_map = load_player_id_bridge(conn)
    total = 0
    dropped = 0
    dropped_keys = {}
    for br_player_id, player_name in worklist:
        # 双轨优先：HTML 重解 > JSON games
        html = load_gamelog_html(season, br_player_id, cache_dir) if cache_dir else None
        if html and "player_game_log_reg" in html:
            games = parse_gamelog_html(html)
            if not player_name:
                jp = players_from_json.get(br_player_id)
                player_name = jp.get("player") if jp else None
        else:
            jp = players_from_json.get(br_player_id)
            games = jp.get("games", []) if jp else []
        if not player_name:
            player_name = br_player_id  # 兜底名(HTML-only 且 JSON 无记录)

        for g in games:
            date_str = g.get("date")
            team = g.get("team")
            game_id = game_map.get((date_str, team))
            if not game_id:
                game_id = game_map.get((date_str, g.get("opp", "")))
            if not game_id:
                # 【禁止静默丢弃】同 run_pipeline：计数并在结尾暴露。
                dropped += 1
                dropped_keys[(date_str, team)] = dropped_keys.get((date_str, team), 0) + 1
                continue
            game_id = str(game_id)

            # Alphanumeric full game id (dim_games.game_id).
            game_id_full = game_id_full_map.get((date_str, team))
            if not game_id_full:
                game_id_full = game_id_full_map.get((date_str, g.get("opp", "")))
            game_id_full = str(game_id_full) if game_id_full else None

            g["game_id"] = game_id
            g["season"] = season
            columns, values = build_insert(player_name, br_player_id, g, game_id_full,
                                            nba_player_id=bridge_map.get(br_player_id))

            cur = conn.cursor()
            delete_existing(cur, game_id, br_player_id, player_name)
            col_sql = ", ".join(columns)
            placeholder_sql = ", ".join(["%s"] * len(columns))
            cur.execute(
                f"INSERT INTO player_gamelog ({col_sql}, created_at) "
                f"VALUES ({placeholder_sql}, NOW())",
                values,
            )
            total += 1
    conn.commit()
    conn.close()
    print(f"[rework] 重放完成: {total} 场入库 / {dropped} 场丢弃(无nba_api_id) (season {season})")
    if dropped:
        print(f"[rework] !! 警告: {dropped} 场因 dim_games 缺 nba_api_id 未入库，"
              f"涉及 {len(dropped_keys)} 个 (date, team) 键 —— 先修 dim_games 再重放。")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='BR 球员 gamelog 爬取')
    parser.add_argument('--season', type=int, required=False, help='赛季结束年 (如 2026 = 2025-26赛季)')
    parser.add_argument('--limit', type=int, default=None, help='最多爬几人 (测试用)')
    parser.add_argument('--dry-run', action='store_true', help='只测试不写库')
    parser.add_argument('--resume', action='store_true', help='跳过已有数据的球员（断点续传）')
    parser.add_argument('--only-br-ids', type=str, default=None,
                        help='只爬该文件列出的 br_player_id（每行一个），用于智能补齐缺口')
    parser.add_argument('--cache-dir', type=str, default=None,
                        help='本季缓存目录，爬完落盘 JSON 供返工（--rework）')
    parser.add_argument('--rework', type=int, default=None,
                        help='从缓存重放某季（免爬），需配合 --cache-dir')
    parser.add_argument('--all-seasons', action='store_true',
                        help='全量：按赛季分层优先级遍历所有赛季（2010+ 先，pre-1980 最后）')
    parser.add_argument('--start-season', type=int, default=1997,
                        help='--all-seasons 起始赛季（含）')
    parser.add_argument('--end-season', type=int, default=2026,
                        help='--all-seasons 结束赛季（含）')
    parser.add_argument('--bypass-500-file', type=str, default=None,
                        help='500 绕开清单文件：BR 返回 500 的球员 br_id 记入此文件并后续跳过')
    parser.add_argument('--force-fetch', action='store_true',
                        help='跳过 HTML 轨道 cache-first 读取，强制重新抓取(实时赛季更新用)')
    # ── 缓存冷归档策略 (2026-08-11) ──
    parser.add_argument('--raw-archive-dir', type=str, default=None,
                        help='冷归档根目录(默认 <项目根>/raw_archive/gamelog)')
    parser.add_argument('--no-archive', action='store_true',
                        help='关闭冷归档(默认开启：溢出时归档不删除)')
    parser.add_argument('--cache-overflow-gb', type=float, default=None,
                        help='本地缓存超此 GB 数触发迁移最老季到冷归档(默认 20)')
    args = parser.parse_args()

    # 缓存冷归档策略覆写 (2026-08-11)：CLI > 环境变量/默认
    if args.raw_archive_dir:
        globals()['RAW_ARCHIVE_ROOT'] = args.raw_archive_dir
    if args.no_archive:
        globals()['ARCHIVE_ON_OVERFLOW'] = False
    if args.cache_overflow_gb is not None:
        globals()['CACHE_OVERFLOW_GB'] = args.cache_overflow_gb

    bypass_file = args.bypass_500_file or _default_bypass_file()

    # 读取 only_br_ids 文件（智能补齐缺口）
    only_ids = None
    if args.only_br_ids:
        try:
            with open(args.only_br_ids) as f:
                only_ids = [l.strip() for l in f if l.strip()]
        except OSError as e:
            print(f"[only_br_ids] 无法读取文件 {args.only_br_ids}: {e}", file=sys.stderr)
            sys.exit(2)

    if args.rework is not None:
        rework_season(args.rework, args.cache_dir or "gamelog_cache")
    elif args.all_seasons:
        # 【赛季优先级 2026-08-01】按 season_sort_key 逐季遍历：tier0(2010+) 先、pre-1980 最后。
        from common.season_priority import season_sort_key, tier_name
        seasons = sorted(range(args.start_season, args.end_season + 1), key=season_sort_key)
        print(f"--all-seasons：按赛季分层优先级遍历 {len(seasons)} 个赛季")
        for s in seasons:
            print(f"===== season {s} [{tier_name(s)}] =====")
            run_pipeline(s, args.limit, args.dry_run, True, args.cache_dir, only_ids,
                         bypass_file=bypass_file, force_fetch=args.force_fetch)
    elif args.season:
        run_pipeline(args.season, args.limit, args.dry_run, args.resume, args.cache_dir, only_ids,
                     bypass_file=bypass_file, force_fetch=args.force_fetch)
    else:
        print("需指定 --season <结束年> / --all-seasons / --rework <结束年>")
