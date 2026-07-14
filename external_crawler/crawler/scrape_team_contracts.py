#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
NBA Team Contracts Scraper — Basketball-Reference
====================================================
爬取所有 30 支球队的合同页面，支持：
  - 当前赛季（2025-26）
  - 历史赛季（通过修改 URL 或页面上的年份选择器）

用法:
  python crawler/scrape_team_contracts.py              # 爬取所有球队当前合同
  python crawler/scrape_team_contracts.py --teams LAL BOS GSW  # 只爬指定球队
  python crawler/scrape_team_contracts.py --all-seasons   # 尝试爬取历史合同
  python crawler/scrape_team_contracts.py --min-delay 20 --max-delay 30
"""
import os
import sys
import time
import json
import logging
import argparse
from datetime import datetime
from pathlib import Path

import psycopg2
from psycopg2.extras import execute_values

# 添加项目根目录到 path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from br_safe_scraper import SafeBRScraper, BR_BASE, HAS_BS4

if HAS_BS4:
    from bs4 import BeautifulSoup

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(
            os.path.join(os.path.dirname(__file__), "..", "logs", "contracts_scrape.log"),
            encoding="utf-8",
        ),
    ],
)
logger = logging.getLogger("ContractScraper")

DB_CONFIG = {
    "host": "localhost",
    "port": 5433,
    "dbname": "nba",
    "user": "postgres",
    "password": "postgres",
}

# NBA 所有球队缩写（2025-26 赛季）
NBA_TEAMS = [
    "ATL", "BOS", "BRK", "CHI", "CHO", "CLE", "DAL", "DEN",
    "DET", "GSW", "HOU", "IND", "LAC", "LAL", "MEM", "MIA",
    "MIL", "MIN", "NOP", "NYK", "OKC", "ORL", "PHI", "PHO",
    "POR", "SAC", "SAS", "TOR", "UTA", "WAS",
]

# 球队全名映射
TEAM_NAMES = {
    "ATL": "Atlanta Hawks", "BOS": "Boston Celtics", "BRK": "Brooklyn Nets",
    "CHI": "Chicago Bulls", "CHO": "Charlotte Hornets", "CLE": "Cleveland Cavaliers",
    "DAL": "Dallas Mavericks", "DEN": "Denver Nuggets", "DET": "Detroit Pistons",
    "GSW": "Golden State Warriors", "HOU": "Houston Rockets", "IND": "Indiana Pacers",
    "LAC": "Los Angeles Clippers", "LAL": "Los Angeles Lakers", "MEM": "Memphis Grizzlies",
    "MIA": "Miami Heat", "MIL": "Milwaukee Bucks", "MIN": "Minnesota Timberwolves",
    "NOP": "New Orleans Pelicans", "NYK": "New York Knicks", "OKC": "Oklahoma City Thunder",
    "ORL": "Orlando Magic", "PHI": "Philadelphia 76ers", "PHO": "Phoenix Suns",
    "POR": "Portland Trail Blazers", "SAC": "Sacramento Kings",
    "SAS": "San Antonio Spurs", "TOR": "Toronto Raptors",
    "UTA": "Utah Jazz", "WAS": "Washington Wizards",
}


def parse_money(text):
    """'$1,234,567' -> 1234567 ; '' -> None"""
    if not text:
        return None
    t = text.strip().replace("$", "").replace(",", "").strip()
    if not t:
        return None
    try:
        return int(t)
    except ValueError:
        return None


def parse_contract_html(html: str, team_abbr: str, season: str) -> dict:
    """解析 BR 合同页面 HTML，返回球员合同列表和球队总计"""
    if not HAS_BS4:
        raise RuntimeError("需要 bs4 库，请运行: pip install beautifulsoup4 lxml")

    soup = BeautifulSoup(html, "lxml")

    result = {
        "team_abbr": team_abbr,
        "team_name": TEAM_NAMES.get(team_abbr, team_abbr),
        "season": season,
        "players": [],
        "team_totals": {},
        "source_url": f"{BR_BASE}/contracts/{team_abbr}.html",
        "scraped_at": datetime.now().isoformat(timespec="seconds"),
    }

    # 查找合同表格
    contracts_tbl = soup.find("table", id="contracts")
    if not contracts_tbl:
        # 尝试其他可能的 id
        for tid in ["contracts", "payroll", "team_contracts"]:
            contracts_tbl = soup.find("table", id=tid)
            if contracts_tbl:
                break

    if not contracts_tbl:
        logger.warning(f"  [{team_abbr}] 找不到合同表格")
        return result

    # 解析球员合同
    tbody = contracts_tbl.find("tbody")
    if not tbody:
        logger.warning(f"  [{team_abbr}] 表格没有 tbody")
        return result

    for tr in tbody.find_all("tr"):
        # 跳过表头分隔行
        th = tr.find("th", {"data-stat": "player"})
        if not th:
            continue

        a = th.find("a")
        player_name = a.get_text(strip=True) if a else th.get_text(strip=True)
        player_id = (a["href"].split("/")[-1].replace(".html", "")
                     if a and a.get("href") else None)

        # 名字斜体 = 已离队
        is_italic = th.find("em") is not None

        def cell(stat):
            td = tr.find(["td", "th"], {"data-stat": stat})
            return td.get_text(strip=True) if td else ""

        def option_flag(td):
            if not td:
                return None
            cls = td.get("class", [])
            if "salary-pl" in cls:
                return "player_option"
            if "salary-tm" in cls:
                return "team_option"
            return None

        age_txt = cell("age_today")
        age = int(age_txt) if age_txt.isdigit() else None

        # 获取各年份工资（y1, y2, y3...）
        salaries = {}
        options = {}
        for y in ["y1", "y2", "y3", "y4", "y5", "y6"]:
            y_cell = tr.find(["td", "th"], {"data-stat": y})
            salaries[y] = parse_money(cell(y))
            options[y] = option_flag(y_cell)

        guaranteed = parse_money(cell("remain_gtd"))

        # 备注（如果有）
        notes_td = tr.find(["td", "th"], {"data-stat": "notes"})
        notes = []
        if notes_td:
            for li in notes_td.find_all("li"):
                notes.append(li.get_text(" ", strip=True))

        result["players"].append({
            "player_id": player_id,
            "player_name": player_name,
            "age": age,
            "salaries": salaries,
            "options": options,
            "guaranteed": guaranteed,
            "is_partial": is_italic,
            "notes": notes,
        })

    # 解析球队总计（tfoot）
    tfoot = contracts_tbl.find("tfoot")
    if tfoot:
        for tr in tfoot.find_all("tr"):
            for stat in ["y1", "y2", "y3", "y4", "y5", "y6", "remain_gtd"]:
                td = tr.find(["td", "th"], {"data-stat": stat})
                if td:
                    result["team_totals"][stat] = parse_money(td.get_text(strip=True))

    logger.info(f"  [{team_abbr}] 解析完成: {len(result['players'])} 名球员")
    return result


def ensure_tables(conn):
    """检查合同相关表是否存在（已存在则跳过）"""
    cur = conn.cursor()
    # 表已由 import_contracts.py 创建，这里只做验证
    try:
        cur.execute("SELECT 1 FROM player_contracts_league LIMIT 1")
        logger.info("player_contracts_league 表已存在")
    except:
        logger.warning("player_contracts_league 表不存在，将创建...")
        cur.execute("""
            CREATE TABLE IF NOT EXISTS player_contracts_league (
                player_id VARCHAR(32),
                player_name TEXT NOT NULL,
                team_abbr VARCHAR(8) NOT NULL,
                season VARCHAR(8) NOT NULL,
                salary_2025_26 BIGINT,
                salary_2026_27 BIGINT,
                salary_2027_28 BIGINT,
                salary_2028_29 BIGINT,
                salary_2029_30 BIGINT,
                salary_2030_31 BIGINT,
                opt_2025_26 VARCHAR(20),
                opt_2026_27 VARCHAR(20),
                opt_2027_28 VARCHAR(20),
                opt_2028_29 VARCHAR(20),
                opt_2029_30 VARCHAR(20),
                opt_2030_31 VARCHAR(20),
                guaranteed BIGINT,
                source_url TEXT,
                scraped_at TIMESTAMP NOT NULL DEFAULT NOW(),
                PRIMARY KEY (player_id, team_abbr, season)
            )
        """)
    
    try:
        cur.execute("SELECT 1 FROM team_payroll LIMIT 1")
        logger.info("team_payroll 表已存在")
    except:
        logger.warning("team_payroll 表不存在，将创建...")
        cur.execute("""
            CREATE TABLE IF NOT EXISTS team_payroll (
                team_abbr VARCHAR(8) NOT NULL,
                team_name VARCHAR(64),
                season VARCHAR(8) NOT NULL,
                salary_cap BIGINT,
                largest_guarantee BIGINT,
                largest_guarantee_player TEXT,
                source_url TEXT,
                scraped_at TIMESTAMP NOT NULL DEFAULT NOW(),
                total_2025_26 BIGINT,
                total_2026_27 BIGINT,
                total_2027_28 BIGINT,
                total_2028_29 BIGINT,
                total_2029_30 BIGINT,
                total_2030_31 BIGINT,
                total_guaranteed BIGINT,
                player_count INT,
                PRIMARY KEY (team_abbr, season)
            )
        """)
    
    conn.commit()
    cur.close()


def save_contracts(conn, data: dict):
    """将解析后的合同数据写入数据库"""
    cur = conn.cursor()
    
    # 1. 写入球队工资总额 (team_payroll)
    t = data["team_totals"]
    cur.execute("""
        INSERT INTO team_payroll
            (team_abbr, team_name, season, salary_cap,
             largest_guarantee, largest_guarantee_player,
             source_url, scraped_at,
             total_2025_26, total_2026_27, total_2027_28,
             total_2028_29, total_2029_30, total_2030_31,
             total_guaranteed, player_count)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (team_abbr, season) DO UPDATE SET
            team_name = EXCLUDED.team_name,
            salary_cap = EXCLUDED.salary_cap,
            largest_guarantee = EXCLUDED.largest_guarantee,
            largest_guarantee_player = EXCLUDED.largest_guarantee_player,
            source_url = EXCLUDED.source_url,
            scraped_at = EXCLUDED.scraped_at,
            total_2025_26 = EXCLUDED.total_2025_26,
            total_2026_27 = EXCLUDED.total_2026_27,
            total_2027_28 = EXCLUDED.total_2027_28,
            total_2028_29 = EXCLUDED.total_2028_29,
            total_2029_30 = EXCLUDED.total_2029_30,
            total_2030_31 = EXCLUDED.total_2030_31,
            total_guaranteed = EXCLUDED.total_guaranteed,
            player_count = EXCLUDED.player_count
    """, (
        data["team_abbr"], data["team_name"], data["season"],
        None,  # salary_cap - 需要从其他来源获取
        t.get("y1"),  # largest_guarantee (近似值)
        None,  # largest_guarantee_player
        data["source_url"], data["scraped_at"],
        t.get("y1"), t.get("y2"), t.get("y3"),
        t.get("y4"), t.get("y5"), t.get("y6"),
        t.get("remain_gtd"),
        len(data["players"]),
    ))
    
    # 2. 写入球员合同 (player_contracts_league)
    for p in data["players"]:
        # 构建 SQL 和参数
        sql = """
            INSERT INTO player_contracts_league
                (player_id, player_name, team_abbr, season,
                 salary_2025_26, salary_2026_27, salary_2027_28,
                 salary_2028_29, salary_2029_30, salary_2030_31,
                 opt_2025_26, opt_2026_27, opt_2027_28,
                 opt_2028_29, opt_2029_30, opt_2030_31,
                 guaranteed, source_url, scraped_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (player_id, team_abbr, season) DO UPDATE SET
                player_name = EXCLUDED.player_name,
                salary_2025_26 = EXCLUDED.salary_2025_26,
                salary_2026_27 = EXCLUDED.salary_2026_27,
                salary_2027_28 = EXCLUDED.salary_2027_28,
                salary_2028_29 = EXCLUDED.salary_2028_29,
                salary_2029_30 = EXCLUDED.salary_2029_30,
                salary_2030_31 = EXCLUDED.salary_2030_31,
                opt_2025_26 = EXCLUDED.opt_2025_26,
                opt_2026_27 = EXCLUDED.opt_2026_27,
                opt_2027_28 = EXCLUDED.opt_2027_28,
                opt_2028_29 = EXCLUDED.opt_2028_29,
                opt_2029_30 = EXCLUDED.opt_2029_30,
                opt_2030_31 = EXCLUDED.opt_2030_31,
                guaranteed = EXCLUDED.guaranteed,
                source_url = EXCLUDED.source_url,
                scraped_at = EXCLUDED.scraped_at
        """
        
        salaries = p["salaries"]
        options = p["options"]
        
        cur.execute(sql, (
            p["player_id"], p["player_name"], data["team_abbr"], data["season"],
            salaries.get("y1"), salaries.get("y2"), salaries.get("y3"),
            salaries.get("y4"), salaries.get("y5"), salaries.get("y6"),
            options.get("y1"), options.get("y2"), options.get("y3"),
            options.get("y4"), options.get("y5"), options.get("y6"),
            p["guaranteed"], data["source_url"], data["scraped_at"],
        ))
    
    conn.commit()
    cur.close()
    logger.info(f"  [{data['team_abbr']}] 数据已写入数据库 ({len(data['players'])} 名球员)")


def scrape_team(scraper: SafeBRScraper, conn, team_abbr: str, season: str = "2025-26") -> bool:
    """爬取单个球队的合同数据"""
    url = f"{BR_BASE}/contracts/{team_abbr}.html"
    logger.info(f"[{team_abbr}] 开始爬取: {url}")

    html = scraper.fetch(url)
    if not html:
        logger.error(f"[{team_abbr}] 爬取失败（可能被拦截）")
        return False

    try:
        data = parse_contract_html(html, team_abbr, season)
        if not data["players"]:
            logger.warning(f"[{team_abbr}] 没有解析到球员数据")
            return False
        save_contracts(conn, data)
        return True
    except Exception as e:
        logger.error(f"[{team_abbr}] 解析/保存失败: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(description="爬取 NBA 球队合同数据（从 BR）")
    parser.add_argument("--teams", nargs="*", default=None,
                        help="只爬取指定球队（缩写），默认全部 30 队")
    parser.add_argument("--season", type=str, default="2025-26",
                        help="赛季（默认 2025-26）")
    parser.add_argument("--all-seasons", action="store_true",
                        help="尝试爬取历史赛季（实验性）")
    parser.add_argument("--min-delay", type=float, default=15.0,
                        help="最小延迟秒数（默认 15）")
    parser.add_argument("--max-delay", type=float, default=25.0,
                        help="最大延迟秒数（默认 25）")
    parser.add_argument("--no-warmup", action="store_true",
                        help="跳过 session 预热")
    args = parser.parse_args()

    # 确定要爬取的球队
    if args.teams:
        teams = [t.upper() for t in args.teams if t.upper() in NBA_TEAMS]
        if not teams:
            logger.error(f"无效的球队缩写: {args.teams}")
            return
    else:
        teams = NBA_TEAMS

    logger.info(f"准备爬取 {len(teams)} 支球队的合同数据")
    logger.info(f"延迟设置: {args.min_delay}-{args.max_delay} 秒")

    # 连接数据库
    conn = psycopg2.connect(**DB_CONFIG)
    ensure_tables(conn)

    # 创建安全爬取器
    scraper = SafeBRScraper(
        min_delay=args.min_delay,
        max_delay=args.max_delay,
        max_retries=3,
        use_playwright=False,
    )

    # 预热
    if not args.no_warmup:
        ok = scraper.warmup()
        if not ok:
            logger.error("预热失败，BR 可能正在拦截。请稍后重试。")
            scraper.close()
            conn.close()
            return

    # 爬取每支球队
    success = 0
    failed = 0
    start_time = time.time()

    for i, team in enumerate(teams):
        logger.info(f"\n{'=' * 60}")
        logger.info(f"进度: {i+1}/{len(teams)} - {team}")
        logger.info(f"{'=' * 60}")

        ok = scrape_team(scraper, conn, team, args.season)
        if ok:
            success += 1
        else:
            failed += 1

        # 进度报告
        if (i + 1) % 5 == 0 or i == len(teams) - 1:
            elapsed = time.time() - start_time
            logger.info(f"\n进度报告: {success} 成功, {failed} 失败, "
                        f"已用时间: {elapsed:.0f}s")

    # 完成
    elapsed = time.time() - start_time
    logger.info(f"\n{'=' * 60}")
    logger.info(f"爬取完成！")
    logger.info(f"  成功: {success} 队")
    logger.info(f"  失败: {failed} 队")
    logger.info(f"  总时间: {elapsed:.0f}s ({elapsed/60:.1f} min)")
    logger.info(f"  爬取统计: {scraper.get_stats()}")
    logger.info(f"{'=' * 60}")

    scraper.close()
    conn.close()


if __name__ == "__main__":
    main()
