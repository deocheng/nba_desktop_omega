"""
Parse Basketball-Reference NYK contracts HTML and insert into PostgreSQL.
"""
import os
import re
import json
from datetime import datetime
from bs4 import BeautifulSoup
import psycopg2
from psycopg2.extras import execute_values

# ---------------- 配置 ----------------
HTML_FILE = r"C:\autopick\AutoPick\nba_data\scraped_nyk_contracts.html"
TEAM_ABBR = "NYK"
TEAM_NAME = "New York Knicks"
SCRAPED_URL = "https://www.basketball-reference.com/contracts/NYK.html"
SCRAPED_AT = datetime.now().isoformat(timespec="seconds")

DB_CONFIG = {
    "host": "localhost",
    "port": 5433,
    "dbname": "nba",
    "user": "postgres",
    "password": "postgres",
}

SALARY_CAP_2025_26 = 154_647_000


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


def main():
    with open(HTML_FILE, "r", encoding="utf-8") as f:
        html = f.read()

    soup = BeautifulSoup(html, "lxml")

    # ---------- 1. 解析 Payroll 表格 ----------
    contracts_tbl = soup.find("table", id="contracts")
    if not contracts_tbl:
        raise RuntimeError("找不到 #contracts 表格")

    players = []
    for tr in contracts_tbl.find("tbody").find_all("tr"):
        # 跳过表头分隔行 & 包含 partial_table (Tosan Evbuomwan) 也保留
        th = tr.find("th", {"data-stat": "player"})
        if not th:
            continue
        a = th.find("a")
        player_name = a.get_text(strip=True) if a else th.get_text(strip=True)
        player_id = (a["href"].split("/")[-1].replace(".html", "")
                     if a and a.get("href") else None)

        # 名字斜体=已离队 (partial_table 行)
        is_italic = th.find("em") is not None

        def cell(stat):
            td = tr.find(["td", "th"], {"data-stat": stat})
            return td.get_text(strip=True) if td else ""

        def csk(stat):
            td = tr.find(["td", "th"], {"data-stat": stat})
            return td.get("csk", "") if td else ""

        age_txt = cell("age_today")
        age = int(age_txt) if age_txt.isdigit() else None

        # 标记 option 颜色
        y1_cell = tr.find("td", {"data-stat": "y1"})
        y2_cell = tr.find("td", {"data-stat": "y2"})
        y3_cell = tr.find("td", {"data-stat": "y3"})
        y4_cell = tr.find("td", {"data-stat": "y4"})
        y5_cell = tr.find("td", {"data-stat": "y5"})
        y6_cell = tr.find("td", {"data-stat": "y6"})

        def option_flag(td):
            if not td:
                return None
            cls = td.get("class", [])
            if "salary-pl" in cls:
                return "player_option"
            if "salary-tm" in cls:
                return "team_option"
            return None

        def csk_int(td):
            v = (td.get("csk", "") if td else "").strip()
            return int(v) if v and v.lstrip("-").isdigit() else None

        players.append({
            "player_id": player_id,
            "player_name": player_name,
            "age": age,
            "y1_2025_26": parse_money(cell("y1")),
            "y2_2026_27": parse_money(cell("y2")),
            "y3_2027_28": parse_money(cell("y3")),
            "y4_2028_29": parse_money(cell("y4")),
            "y5_2029_30": parse_money(cell("y5")),
            "y6_2030_31": parse_money(cell("y6")),
            "guaranteed": parse_money(cell("remain_gtd")),
            "opt_y1": option_flag(y1_cell),
            "opt_y2": option_flag(y2_cell),
            "opt_y3": option_flag(y3_cell),
            "opt_y4": option_flag(y4_cell),
            "opt_y5": option_flag(y5_cell),
            "opt_y6": option_flag(y6_cell),
            "is_partial": is_italic,  # 已离队
        })

    # ---------- 2. 解析 Payroll Notes ----------
    notes_tbl = soup.find("table", id="payroll-notes")
    notes_map = {}
    if notes_tbl:
        for tr in notes_tbl.find("tbody").find_all("tr"):
            th = tr.find("th", {"data-stat": "player"})
            if not th:
                continue
            a = th.find("a")
            player_id = (a["href"].split("/")[-1].replace(".html", "")
                         if a and a.get("href") else None)
            notes_td = tr.find("td", {"data-stat": "notes"})
            bullets = []
            if notes_td:
                for li in notes_td.find_all("li"):
                    bullets.append(li.get_text(" ", strip=True))
            notes_map[player_id] = bullets

    # 关联 notes
    for p in players:
        p["notes"] = notes_map.get(p["player_id"], [])

    # ---------- 3. 写入 PostgreSQL ----------
    conn = psycopg2.connect(**DB_CONFIG)
    conn.autocommit = False
    cur = conn.cursor()

    # 球队摘要表 (复用现有结构)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS team_payroll (
            team_abbr         VARCHAR(8)   NOT NULL,
            team_name         VARCHAR(64),
            season            VARCHAR(8)   NOT NULL,
            salary_cap        BIGINT,
            largest_guarantee BIGINT,
            largest_guarantee_player TEXT,
            source_url        TEXT,
            scraped_at        TIMESTAMP    NOT NULL DEFAULT NOW(),
            total_2025_26     BIGINT,
            total_2026_27     BIGINT,
            total_2027_28     BIGINT,
            total_2028_29     BIGINT,
            total_2029_30     BIGINT,
            total_2030_31     BIGINT,
            total_guaranteed  BIGINT,
            player_count      INT,
            PRIMARY KEY (team_abbr, season)
        );
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS player_contracts (
            team_abbr    VARCHAR(8)  NOT NULL,
            season       VARCHAR(8)  NOT NULL,
            player_id    VARCHAR(32),
            player_name  TEXT        NOT NULL,
            age          INT,
            salary_2025_26 BIGINT,
            salary_2026_27 BIGINT,
            salary_2027_28 BIGINT,
            salary_2028_29 BIGINT,
            salary_2029_30 BIGINT,
            salary_2030_31 BIGINT,
            opt_2025_26  VARCHAR(20),
            opt_2026_27  VARCHAR(20),
            opt_2027_28  VARCHAR(20),
            opt_2028_29  VARCHAR(20),
            opt_2029_30  VARCHAR(20),
            opt_2030_31  VARCHAR(20),
            guaranteed   BIGINT,
            is_partial   BOOLEAN     DEFAULT FALSE,
            notes        JSONB,
            source_url   TEXT,
            scraped_at   TIMESTAMP   NOT NULL DEFAULT NOW(),
            PRIMARY KEY (team_abbr, season, player_id)
        );
    """)

    # Team totals (从页面上抓到的 Team Totals 行)
    tfoot = contracts_tbl.find("tfoot")
    totals = {}
    if tfoot:
        for tr in tfoot.find_all("tr"):
            for stat in ("y1", "y2", "y3", "y4", "y5", "y6", "remain_gtd"):
                td = tr.find("td", {"data-stat": stat})
                if td:
                    totals[stat] = parse_money(td.get_text(strip=True))

    cur.execute("""
        INSERT INTO team_payroll
            (team_abbr, team_name, season, salary_cap, largest_guarantee,
             largest_guarantee_player, source_url, scraped_at,
             total_2025_26, total_2026_27, total_2027_28,
             total_2028_29, total_2029_30, total_2030_31,
             total_guaranteed, player_count)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
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
            player_count = EXCLUDED.player_count;
    """, (
        TEAM_ABBR, TEAM_NAME, "2025-26", SALARY_CAP_2025_26,
        133_382_144, "Mikal Bridges", SCRAPED_URL, SCRAPED_AT,
        totals.get("y1"), totals.get("y2"), totals.get("y3"),
        totals.get("y4"), totals.get("y5"), totals.get("y6"),
        totals.get("remain_gtd"), len(players),
    ))

    # 球员合同
    rows = [(
        TEAM_ABBR, "2025-26", p["player_id"], p["player_name"], p["age"],
        p["y1_2025_26"], p["y2_2026_27"], p["y3_2027_28"],
        p["y4_2028_29"], p["y5_2029_30"], p["y6_2030_31"],
        p["opt_y1"], p["opt_y2"], p["opt_y3"],
        p["opt_y4"], p["opt_y5"], p["opt_y6"],
        p["guaranteed"], p["is_partial"],
        json.dumps(p["notes"], ensure_ascii=False),
        SCRAPED_URL, SCRAPED_AT,
    ) for p in players]

    execute_values(cur, """
        INSERT INTO player_contracts
            (team_abbr, season, player_id, player_name, age,
             salary_2025_26, salary_2026_27, salary_2027_28,
             salary_2028_29, salary_2029_30, salary_2030_31,
             opt_2025_26, opt_2026_27, opt_2027_28,
             opt_2028_29, opt_2029_30, opt_2030_31,
             guaranteed, is_partial, notes, source_url, scraped_at)
        VALUES %s
        ON CONFLICT (team_abbr, season, player_id) DO UPDATE SET
            player_name = EXCLUDED.player_name,
            age = EXCLUDED.age,
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
            is_partial = EXCLUDED.is_partial,
            notes = EXCLUDED.notes,
            source_url = EXCLUDED.source_url,
            scraped_at = EXCLUDED.scraped_at;
    """, rows)

    conn.commit()
    cur.execute("SELECT COUNT(*) FROM player_contracts WHERE team_abbr=%s AND season=%s;",
                (TEAM_ABBR, "2025-26"))
    print(f"[OK] player_contracts 写入完成，team={TEAM_ABBR} 记录数: {cur.fetchone()[0]}")
    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
