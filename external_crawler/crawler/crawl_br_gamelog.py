import os
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


def scrape_gamelog(player_name: str, player_id: str, season: int) -> list:
    """Scrape one player's gamelog from BR (browser-backed)"""
    first_letter = player_id[0].lower()
    url = f"https://www.basketball-reference.com/players/{first_letter}/{player_id}/gamelog/{season}"

    html = _fetch_html(url)
    if not html:
        print(f"    fetch failed")
        return []

    soup = BeautifulSoup(html, 'html.parser')
    table = soup.find('table', id='player_game_log_reg')
    if not table:
        print(f"    No table found")
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


def run_pipeline(season: int, limit: int = None, dry_run: bool = False, resume: bool = False):
    """Main pipeline"""
    conn = psycopg2.connect(**DB_CONFIG)
    
    # Get players
    players = get_players(conn, season, limit, resume)
    if resume:
        already_done = sum(1 for _ in get_players(conn, season)) - len(players)
        print(f"共 {len(players)} 名球员需要爬取 ({already_done} 已跳过)")
    
    # Build game_id mapping
    game_map = get_game_id_map(conn, season)
    print(f"game_id 映射: {len(game_map)} 条 (赛季 {season})")
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
                        game_id = game_map.get((date_str, g['opp']))
                    
                    if not game_id:
                        continue
                    game_id = str(game_id)  # player_gamelog.gameid is varchar
                    
                    if not dry_run:
                        # UPSERT: DELETE then INSERT
                        cur = conn.cursor()
                        cur.execute("""
                            DELETE FROM player_gamelog WHERE gameid = %s AND player = %s
                        """, (game_id, player_name))
                        
                        cur.execute("""
                            INSERT INTO player_gamelog 
                            (gameid, player, team, season, fg, fga, fg_pct, fg3, fga3, fg3_pct,
                             ft, fta, ft_pct, orb, drb, trb, ast, stl, blk, tov, pf, pts, plus_minus,
                             created_at)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                        """, (
                            game_id, player_name, g['team'], season,
                            g.get('fg'), g.get('fga'), g.get('fg_pct'),
                            g.get('fg3'), g.get('fga3'), g.get('fg3_pct'),
                            g.get('ft'), g.get('fta'), g.get('ft_pct'),
                            g.get('orb'), g.get('drb'), g.get('trb'),
                            g.get('ast'), g.get('stl'), g.get('blk'),
                            g.get('tov'), g.get('pf'), g.get('pts'),
                            g.get('plus_minus'),
                        ))
                        cur.close()
                    
                    inserted += 1
                
                if dry_run:
                    conn.rollback()
                else:
                    conn.commit()
                
                print(f"{inserted} 场 ✓")
                total_games += inserted
                success += 1
        
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
    
    conn.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='BR 球员 gamelog 爬取')
    parser.add_argument('--season', type=int, required=True, help='赛季结束年 (如 2026 = 2025-26赛季)')
    parser.add_argument('--limit', type=int, default=None, help='最多爬几人 (测试用)')
    parser.add_argument('--dry-run', action='store_true', help='只测试不写库')
    parser.add_argument('--resume', action='store_true', help='跳过已有数据的球员（断点续传）')
    args = parser.parse_args()
    
    run_pipeline(args.season, args.limit, args.dry_run, args.resume)
