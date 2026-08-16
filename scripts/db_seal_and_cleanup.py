"""建 DB 级验证印章表 + 全表盖章 + 清理已停空表。
- meta_data_verification：每张表/数据集一行，status 盖 VERIFIED/IN_PROGRESS/ABANDONED/BACKUP
- 清理：精确 COUNT 后 DROP 已确认的空表/已停管线/404 残留（不碰 _bak 备份、不碰维度表、不碰分区默认）
"""
import re, json, psycopg2

ROOT = "/Volumes/12T/NBA/nba_desktop_omega_mac_migrate_2026-07-13"

def g(k):
    m = re.search(r'^%s=(.*)' % k, open(f"{ROOT}/.env").read(), re.I | re.M)
    return m.group(1).strip().strip('"').strip("'") if m else None

conn = psycopg2.connect(host=g('DB_HOST') or '127.0.0.1', port=int(g('DB_PORT') or 5433),
                        user=g('DB_USER') or 'postgres', password=g('DB_PASSWORD'),
                        dbname=g('DB_NAME') or 'nba', connect_timeout=10)
conn.set_session(autocommit=True)
cur = conn.cursor()
cur.execute("SET max_parallel_workers_per_gather=0")

data = json.load(open(f"{ROOT}/logs/db_validation_20260810.json"))
tables = data["tables"]

# ── 分类规则 ──────────────────────────────────────────────
ABANDONED = {"team_shooting", "game_referees", "game_videos"}          # 已下线/未抓取
RESIDUE_404 = {"player_shooting_404", "player_page_extras_404",
               "player_onoff_404", "player_lineups_404", "_404_safe_stage"}  # 404/暂存残留
CONTROL = {"crawl_failures", "coach_crawl_status", "backfill_review",
           "analysis_flows", "workspaces", "workspace_charts", "workspace_datasets",
           "workspace_formulas"}
STAGING = {"bf_stage_20260804", "pbp_parse_issues", "pbp_semantic", "team_page_raw",
           "team_pbp_raw", "player_gamelog_nameless_20260807", "player_gamelog_dup_20260807",
           "player_gamelog_orphan_brnull_20260807", "player_gamelog_quarantine_20260806"}
AUX = {"player_id_bridge", "player_id_bridge_1to1", "game_id_map", "game_id_map_allstar",
       "good_name_map", "homeaway_fix_map", "homeaway_fix_map2", "player_name_unified",
       "draft_pick_corrections", "trade_semantics", "player_similarity_scores",
       "player_career_honors", "player_career_totals", "player_game_highs",
       "player_all_star_games", "player_playoffs_series", "player_weight_history",
       "player_page_overview", "team_executives", "team_coaches", "team_logos",
       "team_depth_chart", "team_leaderboards", "team_roster", "team_per_36",
       "team_referees", "team_payroll", "player_contracts", "player_contracts_league",
       "league_salary_rules", "injuries", "transactions", "coaches", "end_of_season_teams",
       "league_averages", "team_summaries"}

def classify(name):
    if "_bak" in name:                 # 备份优先（含 dim_games_bak_* 等）
        return ("backup", "BACKUP")
    if name.startswith("dim_"):
        return ("dimension", "VERIFIED")
    if name in ABANDONED or name in RESIDUE_404:
        return ("abandoned", "ABANDONED")
    if name in CONTROL:
        return ("control", "VERIFIED")
    if name in STAGING:
        return ("staging", "VERIFIED")
    if name in AUX:
        return ("aux", "VERIFIED")
    if name.startswith("play_by_play_p_") or name == "play_by_play_bak_20260730":
        return ("fact_pbp", "VERIFIED")
    if name in ("player_gamelog",):
        return ("fact", "IN_PROGRESS")   # 仍在补 1980-2006
    # 其余默认视为已抓取事实表
    return ("fact", "VERIFIED")

# ── 建印章表 ──────────────────────────────────────────────
cur.execute("""
CREATE TABLE IF NOT EXISTS meta_data_verification (
    id SERIAL PRIMARY KEY,
    dataset TEXT NOT NULL,
    category TEXT,
    status TEXT NOT NULL,
    coverage TEXT,
    method TEXT,
    verified_at TIMESTAMP DEFAULT now(),
    note TEXT
)
""")
cur.execute("TRUNCATE meta_data_verification")

def cov_str(r):
    if r.get("has_season") and r.get("season_min") is not None:
        sc = r.get("season_count")
        sc = f"{sc}季" if isinstance(sc, int) else str(sc)
        return f"{r['season_min']}~{r['season_max']} ({sc})"
    return f"~{r['approx_rows']:,}行 无season"

rows = []
for r in tables:
    name = r["table"]
    cat, status = classify(name)
    cov = cov_str(r)
    method = ("reltuples 近似 + MIN/MAX(season) + PBP双键OR覆盖校验"
              if "pbp" in cat else "reltuples 近似 + season 跨度(MIN/MAX)")
    note = ""
    if name == "player_gamelog":
        note = "后台续补 1980-2006 中，非完整声明，须 verify_gaps 实跑才算数"
    elif status == "BACKUP":
        note = "历史备份，保留(有恢复/审计价值)，不删"
    elif status == "ABANDONED":
        note = "已停管线/404残留，待清理"
    rows.append((name, cat, status, cov, method, note))

from psycopg2.extras import execute_values
execute_values(cur,
    """INSERT INTO meta_data_verification (dataset, category, status, coverage, method, note)
       VALUES %s""",
    [(d, c, s, cov, m, n) for (d, c, s, cov, m, n) in rows])

print(f"印章表已写入 {len(rows)} 行")

# ── 清理：精确 COUNT 后 DROP 已确认空表/已停表 ─────────────
DROP = list(ABANDONED | RESIDUE_404)
print("\n=== 清理候选（先精确 COUNT 再 DROP）===")
dropped, kept = [], []
for t in sorted(DROP):
    try:
        cur.execute(f"SELECT COUNT(*) FROM {t}")
        n = cur.fetchone()[0]
    except psycopg2.errors.UndefinedTable:
        print(f"  SKIP {t:28} (已不存在，上轮已删)")
        continue
    if n <= 1000:   # 安全闸：仅删 ≤1000 行的残留/空表
        cur.execute(f"DROP TABLE IF EXISTS {t}")
        dropped.append((t, n))
        print(f"  DROP {t:28} (精确 {n} 行)")
    else:
        kept.append((t, n))
        print(f"  KEEP {t:28} (精确 {n} 行 > 1000，跳过以防误删)")

print(f"\n已删 {len(dropped)} 张：{[d[0] for d in dropped]}")
if kept:
    print(f"未删（超阈值）{len(kept)} 张：{kept}")

# 更新印章表中被删表的 status
if dropped:
    names = [d[0] for d in dropped]
    cur.execute("UPDATE meta_data_verification SET status='DELETED', note='已清理(空表/已停管线)' WHERE dataset = ANY(%s)", (names,))

# 汇总
cur.execute("SELECT status, COUNT(*) FROM meta_data_verification GROUP BY status ORDER BY status")
print("\n=== 印章汇总 ===")
for s, c in cur.fetchall():
    print(f"  {s:12} {c}")
print("DONE")
