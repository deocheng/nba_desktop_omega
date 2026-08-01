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

# Ensure the project root (three levels up from this file) is on sys.path so
# `import common.browser` resolves when run as a standalone script.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

# cache-first 主球员页缓存: gamelog 走浏览器通道(Playwright + 9222 Chrome),
# 顺手把主球员页 HTML 落盘, 供后续 nickname / bio_ext 爬虫(cache-first, curl 通道)
# 离线抽取, 不再每轮撞 BR 403。详见 common/player_page_cache.py。
import common.player_page_cache as player_page_cache

DB_CONFIG = dict(host='localhost', port=5433, dbname='nba', user='postgres', password=os.environ.get('DB_PASSWORD'))

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}

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
        mapping[(date_str, home)] = nba_id
        mapping[(date_str, away)] = nba_id

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
        mapping[(date_str, home)] = gid
        mapping[(date_str, away)] = gid

    return mapping


def _fetch_html(url: str) -> str:
    """Fetch a fully-rendered BR page via the shared Playwright driver.

    Reuses ``common.browser.get_driver()`` (the Playwright + stealth backend,
    with optional CF-cookie injection). After navigation we poll ``page_source``
    for the real stat table so a previously-injected ``cf_clearance`` cookie is
    given time to clear any residual Cloudflare interstitial. Returns the rendered
    HTML, or '' on hard failure.
    """
    from common.browser import get_driver
    drv = get_driver()
    drv.get(url)
    html = drv.page_source
    if "player_game_log_reg" in html:
        return html
    # Poll up to ~60s for the real table (CF interstitial still clearing).
    for _ in range(12):
        time.sleep(5)
        html = drv.page_source
        if "player_game_log_reg" in html:
            return html
    return html  # caller sees no table and skips safely


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

        games.append(game)

    return games


def scrape_gamelog(player_name: str, player_id: str, season: int) -> list:
    """Scrape one player's gamelog from BR (browser-backed)"""
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

    html = _fetch_html(url)
    if not html:
        print(f"    fetch failed")
        return []

    return parse_gamelog_html(html)


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

    merged: dict = {}
    for entry in old_players:
        merged[_key(entry)] = entry
    for entry in new_players:
        merged[_key(entry)] = entry  # 新抓覆盖同 player_id 的旧条目

    merged_players = list(merged.values())

    # 3) 整体回写（MERGE 结果）。
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(
            {"season": season, "players": merged_players},
            fh,
            ensure_ascii=False,
            indent=1,
        )

    return out_path


def build_insert(player_name: str, player_id: str, g: dict, game_id_full: str = None) -> tuple:
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

    Returns:
        ``(columns, values)`` — two tuples of identical length (26). ``created_at``
        is intentionally excluded; callers append it as ``NOW()`` in the SQL.
    """
    columns = (
        'gameid', 'player', 'team', 'season',
        'br_player_id', 'player_name', 'game_id_full',
        'fg', 'fga', 'fg_pct', 'fg3', 'fga3', 'fg3_pct',
        'ft', 'fta', 'ft_pct', 'orb', 'drb', 'trb', 'ast', 'stl', 'blk',
        'tov', 'pf', 'pts', 'plus_minus',
    )
    values = (
        g.get('game_id'),
        player_name,
        g.get('team'),
        g.get('season'),
        player_id,
        player_name,
        game_id_full,
        g.get('fg'), g.get('fga'), g.get('fg_pct'),
        g.get('fg3'), g.get('fga3'), g.get('fg3_pct'),
        g.get('ft'), g.get('fta'), g.get('ft_pct'),
        g.get('orb'), g.get('drb'), g.get('trb'),
        g.get('ast'), g.get('stl'), g.get('blk'),
        g.get('tov'), g.get('pf'), g.get('pts'),
        g.get('plus_minus'),
    )
    return columns, values


def run_pipeline(season: int, limit: int = None, dry_run: bool = False,
                resume: bool = False, cache_dir: str = None):
    """Main pipeline.

    cache_dir: 若设置，本季爬完将整季解析结果落盘为
    <cache_dir>/gamelog_<season>.json，供返工免重爬重放（--rework）。
    """
    conn = psycopg2.connect(**DB_CONFIG)

    # 本季本地缓存收集（返工安全）
    season_cache = []

    # Get players
    players = get_players(conn, season, limit, resume)
    if resume:
        already_done = sum(1 for _ in get_players(conn, season)) - len(players)
        print(f"共 {len(players)} 名球员需要爬取 ({already_done} 已跳过)")
    
    # Build game_id mappings: numeric nba_api_id (for player_gamelog.gameid)
    # and alphanumeric full game id (for player_gamelog.game_id_full).
    game_map = get_game_id_map(conn, season)
    game_id_full_map = get_game_id_full_map(conn, season)
    print(f"game_id 映射: {len(game_map)} 条, game_id_full 映射: {len(game_id_full_map)} 条 (赛季 {season})")
#   Inactive status values to skip
    skip_statuses = {'Inactive', 'Did Not Play', 'Did Not Dress', 'Not With Team', 'Inactive'}
    
    total_games = 0
    success = 0
    failed = 0
    skipped_players = 0
    
    for i, (player_name, player_id) in enumerate(players):
        if not player_id:
            print(f"[{i+1}/{len(players)}] {player_name} (None) → 跳过 (无 player_id)")
            skipped_players += 1
            continue
        print(f"[{i+1}/{len(players)}] {player_name} ({player_id})...", end=' ', flush=True)
        
        try:
            games = scrape_gamelog(player_name, player_id, season)
            
            if not games:
                print(f"0 场 (skip)")
                skipped_players += 1
            else:
                inserted = 0
                for g in games:
                    date_str = g['date']
                    team = g['team']
                    game_id = game_map.get((date_str, team))

                    if not game_id:
                        # Try with opponent team (away games)
                        game_id = game_map.get((date_str, g.get('opp', '')))

                    if not game_id:
                        continue
                    game_id = str(game_id)  # player_gamelog.gameid is varchar

                    # Alphanumeric full game id (dim_games.game_id).
                    game_id_full = game_id_full_map.get((date_str, team))
                    if not game_id_full:
                        game_id_full = game_id_full_map.get((date_str, g.get('opp', '')))
                    game_id_full = str(game_id_full) if game_id_full else None

                    # Stamp the resolved ids onto the game dict so build_insert
                    # has everything it needs in one place.
                    g['game_id'] = game_id
                    g['season'] = season
                    columns, values = build_insert(player_name, player_id, g, game_id_full)

                    if not dry_run:
                        # UPSERT: DELETE then INSERT
                        cur = conn.cursor()
                        cur.execute(
                            "DELETE FROM player_gamelog WHERE gameid = %s AND player = %s",
                            (game_id, player_name),
                        )

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
                
                print(f"{inserted} 场 ✓")
                total_games += inserted
                success += 1
                # 收集到本季缓存（仅非空场，供 --rework 返工重放）
                season_cache.append({
                    "player": player_name,
                    "player_id": player_id,
                    "games": games,
                })
        
        except Exception as e:
            print(f"ERR: {e}")
            failed += 1
            conn.rollback()
        
        # Rate limiting: 3-6 seconds between players
        if i < len(players) - 1:
            delay = 3 + random.uniform(0, 3)
            time.sleep(delay)
    
    print(f"\n{'='*50}")
    print(f"完成! {success} 成功, {failed} 失败, {skipped_players} 跳过")
    print(f"共写入 {total_games} 场比赛")

    # ── 本季本地缓存（返工安全：可免重爬重放）──
    # 注意：这里使用 MERGE 语义（merge_gamelog_cache）而非 OVERWRITE，
    # 以免 --resume 模式下把整季缓存削成"仅本轮回新抓的球员"。
    if cache_dir and not dry_run:
        out_path = merge_gamelog_cache(season, season_cache, cache_dir)
        print(f"已缓存本季到 {out_path} (本轮回 {len(season_cache)} 球员, MERGE 写入)")

    conn.close()


def rework_season(season: int, cache_dir: str) -> None:
    """从本地缓存重放本季 gamelog 到 DB（免重爬，用于返工/修正）。

    读取 <cache_dir>/gamelog_<season>.json，按原逻辑重新 UPSERT 到
    player_gamelog（DELETE+INSERT）。依赖 dim_games 的 game_id 映射，
    因此 dim_games 不可在本季重放前被改动 game_id。
    """
    import json, os
    path = os.path.join(cache_dir, f"gamelog_{season}.json")
    if not os.path.exists(path):
        print(f"[rework] 缓存不存在: {path}")
        return
    data = json.load(open(path, encoding="utf-8"))
    conn = psycopg2.connect(**DB_CONFIG)
    game_map = get_game_id_map(conn, season)
    game_id_full_map = get_game_id_full_map(conn, season)
    total = 0
    for p in data.get("players", []):
        br_player_id = p.get("player_id")
        player_name = p.get("player")
        for g in p.get("games", []):
            date_str = g.get("date")
            team = g.get("team")
            game_id = game_map.get((date_str, team))
            if not game_id:
                game_id = game_map.get((date_str, g.get("opp", "")))
            if not game_id:
                continue
            game_id = str(game_id)

            # Alphanumeric full game id (dim_games.game_id).
            game_id_full = game_id_full_map.get((date_str, team))
            if not game_id_full:
                game_id_full = game_id_full_map.get((date_str, g.get("opp", "")))
            game_id_full = str(game_id_full) if game_id_full else None

            g["game_id"] = game_id
            g["season"] = season
            columns, values = build_insert(player_name, br_player_id, g, game_id_full)

            cur = conn.cursor()
            cur.execute(
                "DELETE FROM player_gamelog WHERE gameid=%s AND player=%s",
                (game_id, player_name),
            )
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
    print(f"[rework] 重放完成: {total} 场 (season {season})")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='BR 球员 gamelog 爬取')
    parser.add_argument('--season', type=int, required=False, help='赛季结束年 (如 2026 = 2025-26赛季)')
    parser.add_argument('--limit', type=int, default=None, help='最多爬几人 (测试用)')
    parser.add_argument('--dry-run', action='store_true', help='只测试不写库')
    parser.add_argument('--resume', action='store_true', help='跳过已有数据的球员（断点续传）')
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
    args = parser.parse_args()

    if args.rework is not None:
        rework_season(args.rework, args.cache_dir or "gamelog_cache")
    elif args.all_seasons:
        # 【赛季优先级 2026-08-01】按 season_sort_key 逐季遍历：tier0(2010+) 先、pre-1980 最后。
        from common.season_priority import season_sort_key, tier_name
        seasons = sorted(range(args.start_season, args.end_season + 1), key=season_sort_key)
        print(f"--all-seasons：按赛季分层优先级遍历 {len(seasons)} 个赛季")
        for s in seasons:
            print(f"===== season {s} [{tier_name(s)}] =====")
            run_pipeline(s, args.limit, args.dry_run, True, args.cache_dir)
    elif args.season:
        run_pipeline(args.season, args.limit, args.dry_run, args.resume, args.cache_dir)
    else:
        print("需指定 --season <结束年> / --all-seasons / --rework <结束年>")
