"""orchestrator_tasks.py — BR-only 轮换调度任务注册表。

每个任务字段：
  name       任务名（唯一）
  cmd        启动命令（从仓库根运行；调度器负责注入 env：CDP / 代理消毒 / CF_*）
  deps       依赖的任务名列表（依赖未完成前不启动本任务）
  priority   优先级（数值大者优先，用于同档选择）
  probe_sql  剩余缺口查询（返回"还剩多少待爬"）；None=无精确探针，靠进程退出决策
  log        该任务专属日志路径（调度器用于 alive/进度判据）

说明：
  - 轮换池**严格限定在 BR 网站**（不含 ESPN 跨源），按 URL 模式差异分散风险。
  - player_shot_chart 的 universe 来自 player_shooting，故设 deps=["player_shooting"]。
  - probe_sql 仅用于"缺口==0→标记完成"；>0 或无探针→轮换。表名/列名实施时按需核对。
"""
from typing import Optional

# ── 探针 SQL ────────────────────────────────────────────────────────────
# 【数据四性铁律 · 统一】探针口径必须与对应爬虫 enumerate_pairs() 的口径**逐字一致**，
# 否则调度器与爬虫互相打架（爬虫认为无缺口→空转退出；探针认为有缺口→永不标 done）。
#
# 2026-07-31 修复（原实现违反四性，导致 shot_chart 全天零调度）：
#   - 原 _SHOOTING_GAP_SQL 抄的是 shot_chart 的 pair 缺口口径（跨域错配 → 违反「正确」），
#     致 player_shooting 恒 gap>0 永不 done，其 dep 方 player_shot_chart 被死锁 runs=0。
#   - 原 _SHOTCHART_GAP_SQL 漏排 crawl_failures（真无数据的对永远计入 → 缺口永不归零），
#     且限定 season>=2001 漏掉 594 个 2001 前缺口（违反「完整」）。

# 与 crawl_br_player_shooting.py::enumerate_pairs 一致：
# fact_player_season_stats 实际出战赛季缺口，排除已登记失败。
_SHOOTING_GAP_SQL = """
    SELECT count(*) FROM (
      SELECT DISTINCT fps.player_id, fps.season::int
      FROM fact_player_season_stats fps
      WHERE fps.season >= 1997 AND fps.season <= 2026
        AND fps.player_id IS NOT NULL
        AND NOT EXISTS (SELECT 1 FROM player_shooting ps
                        WHERE ps.player_id=fps.player_id AND ps.season=fps.season
                          AND ps.season_type='Regular')
        AND NOT EXISTS (SELECT 1 FROM crawl_failures cf
                        WHERE cf.task_type='br_player_shooting'
                          AND cf.game_id='br_player_shooting|'||fps.player_id||'|'||fps.season::text)
    ) g
"""

# 与 crawl_br_player_shot_chart.py::enumerate_pairs 一致：
# universe=已落库 player_shooting，排除已落库 shot_chart 与已登记失败；**不限赛季**。
_SHOTCHART_GAP_SQL = """
    SELECT count(*) FROM (
      SELECT DISTINCT ps.player_id, ps.season
      FROM player_shooting ps
      LEFT JOIN player_shot_chart sc
             ON sc.player_id = ps.player_id AND sc.season = ps.season
      LEFT JOIN crawl_failures cf
             ON cf.task_type='br_player_shot_chart'
            AND cf.game_id = 'br_player_shot_chart|' || ps.player_id || '|' || ps.season::text
      WHERE sc.player_id IS NULL AND cf.game_id IS NULL
    ) g
"""

# 与 crawl_br_nicknames.py::get_players(resume=True) 一致：
# nickname IS NULL 且未登记「确认无绰号」。
# 注意：确认无绰号者写回的也是 NULL，仅靠 IS NULL 无法与「从没查过」区分，
# 故必须排除 crawl_failures，否则缺口恒为 3404、永不归零（2026-07-31 实测）。
_NICKNAME_GAP_SQL = """
    SELECT count(*) FROM dim_players p
    WHERE p.nickname IS NULL
      AND NOT EXISTS (
          SELECT 1 FROM crawl_failures cf
          WHERE cf.task_type = 'br_player_nickname'
            AND cf.game_id = 'br_player_nickname|' || p.player_id
      )
"""

# 与 crawl_br_player_bio_ext.py::get_players(resume=True) 一致：
# bio_ext_scraped_at IS NULL。该列由 upsert_player_bio_ext() 无条件写 now()，
# 语义是「是否已尝试」（而非「是否有数据」），故能正确收敛到 0。
_BIO_EXT_GAP_SQL = """
    SELECT count(*) FROM dim_players WHERE bio_ext_scraped_at IS NULL
"""

# 与 crawl_br_player_page_extras.enumerate_players 口径逐字对齐：
# 枚举宇宙 = player_gamelog.br_player_id ∪ dim_players.player_id（已确认两者都在 dim_players 内）。
# 「未完成」= 时间戳非空(已成功落库) / 404 隔离 / crawl_failures 登记 三者都不满足。
_PAGE_EXTRAS_GAP_SQL = """
    SELECT count(*) FROM (
      SELECT slug FROM (
        SELECT br_player_id AS slug FROM player_gamelog WHERE br_player_id IS NOT NULL
        UNION SELECT player_id AS slug FROM dim_players WHERE player_id IS NOT NULL
      ) u
      WHERE NOT EXISTS (
        SELECT 1 FROM dim_players p
        WHERE p.player_id = u.slug AND p.player_page_extras_scraped_at IS NOT NULL)
        AND NOT EXISTS (SELECT 1 FROM player_page_extras_404 q WHERE q.slug = u.slug)
        AND NOT EXISTS (
          SELECT 1 FROM crawl_failures cf
          WHERE cf.task_type = 'br_player_page_extras'
            AND cf.game_id = 'player_page_extras|' || u.slug || '|all')
    ) g
"""

# ── EPM（dunksandthrees.com）─────────────────────────────────────────────
# 与 BR 站点完全独立：走 curl_cffi/urllib 抓 dunksandthrees，不占 Chrome CDP、不碰 CF。
# 三源分别落库：
#   /epm          → player_epm(source='dunksandthrees.com/epm'，当前赛季预测值)
#   /epm/actual   → player_epm_actual(source='dunksandthrees.com/epm/actual'，当前赛季实际值)
#   球员页 eskills → player_epm(source='dunksandthrees.com/player/eskills'，2002~now 全历史)
# 探针宇宙 = player_shooting 覆盖的活跃球员；跑满后缺口归零→标记完成，闲置至用户重置状态触发刷新
# （与既有 probe_sql=None 任务行为一致；ON CONFLICT 按 source 隔离，三源不互相覆盖）。

# 与 crawl_dunksandthrees_epm.py 落库口径一致：source='dunksandthrees.com/epm' 的当前赛季行。
_EPM_GAP_SQL = """
    SELECT count(*) FROM (
      SELECT p.player_id FROM dim_players p
      WHERE p.player_id IS NOT NULL
        AND EXISTS (SELECT 1 FROM player_shooting ps WHERE ps.player_id = p.player_id)
        AND NOT EXISTS (
          SELECT 1 FROM player_epm e
          WHERE e.br_player_id = p.player_id
            AND e.source = 'dunksandthrees.com/epm'
            AND e.season = (SELECT max(season) FROM player_epm WHERE source='dunksandthrees.com/epm')
        )
    ) g
"""

# 与 crawl_dunksandthrees_epm_actual.py 落库口径一致：source='dunksandthrees.com/epm/actual'。
_EPM_ACTUAL_GAP_SQL = """
    SELECT count(*) FROM (
      SELECT p.player_id FROM dim_players p
      WHERE p.player_id IS NOT NULL
        AND EXISTS (SELECT 1 FROM player_shooting ps WHERE ps.player_id = p.player_id)
        AND NOT EXISTS (
          SELECT 1 FROM player_epm_actual e
          WHERE e.br_player_id = p.player_id
            AND e.source = 'dunksandthrees.com/epm/actual'
            AND e.season = (SELECT max(season) FROM player_epm_actual WHERE source='dunksandthrees.com/epm/actual')
        )
    ) g
"""

# 与 crawl_dunksandthrees_epm_history.py 落库口径一致：source='dunksandthrees.com/player/eskills'（全历史）。
_EPM_HISTORY_GAP_SQL = """
    SELECT count(*) FROM (
      SELECT p.player_id FROM dim_players p
      WHERE p.player_id IS NOT NULL
        AND EXISTS (SELECT 1 FROM player_shooting ps WHERE ps.player_id = p.player_id)
        AND NOT EXISTS (
          SELECT 1 FROM player_epm e
          WHERE e.br_player_id = p.player_id
            AND e.source = 'dunksandthrees.com/player/eskills'
        )
    ) g
"""

TASKS = [
    {
        "name": "player_shooting",
        "cmd": [".venv/bin/python", "external_crawler/crawler/crawl_br_player_shooting.py", "--resume"],
        "deps": [],
        "priority": 90,
        "probe_sql": _SHOOTING_GAP_SQL,
        "log": "/Volumes/12T/NBA/shooting_crawl.log",
    },
    {
        "name": "player_shot_chart",
        # 【四性 · 完整】2026-07-31 移除 deps=["player_shooting"]：
        # shot_chart 的 universe 是**已落库**的 player_shooting 行，不要求 shooting 全量完成；
        # 硬依赖只会在 shooting 探针异常时造成死锁（历史上已致 runs=0 全天零调度）。
        "cmd": [".venv/bin/python", "external_crawler/crawler/crawl_br_player_shot_chart.py", "--resume"],
        "deps": [],
        "priority": 100,
        "probe_sql": _SHOTCHART_GAP_SQL,
        "log": "/Volumes/12T/NBA/shot_chart_crawl.log",
    },
    {
        "name": "player_page_extras",
        "cmd": [".venv/bin/python", "external_crawler/crawler/crawl_br_player_page_extras.py", "--resume"],
        "deps": [],
        "priority": 70,
        "probe_sql": _PAGE_EXTRAS_GAP_SQL,
        "log": "/Volumes/12T/NBA/player_page_extras_crawl.log",
    },
    {
        "name": "team_page_extras",
        "cmd": [".venv/bin/python", "external_crawler/crawler/crawl_br_team_page_extras.py", "--season", "2026", "--resume"],
        "deps": [],
        "priority": 60,
        "probe_sql": None,
        "log": "/Volumes/12T/NBA/team_page_extras_crawl.log",
    },
    {
        "name": "team_lineups",
        "cmd": [".venv/bin/python", "external_crawler/crawler/crawl_br_team_lineups.py",
                "--season", "2026", "--resume", "--cache-dir", "br_lineups_cache"],
        "deps": [],
        "priority": 50,
        "probe_sql": None,
        "log": "/Volumes/12T/NBA/team_lineups_crawl.log",
    },
    {
        "name": "team_referees",
        "cmd": [".venv/bin/python", "external_crawler/crawler/crawl_br_team_referees.py",
                "--season", "2026", "--resume", "--cache-dir", "br_referees_cache"],
        "deps": [],
        "priority": 50,
        "probe_sql": None,
        "log": "/Volumes/12T/NBA/team_referees_crawl.log",
    },
    {
        "name": "team_pbp",
        "cmd": [".venv/bin/python", "external_crawler/crawler/crawl_br_team_pbp.py",
                "--all-seasons", "--resume", "--caffeinate", "--cache-dir", "br_team_pbp_cache"],
        "deps": [],
        "priority": 40,
        "probe_sql": None,
        "log": "/Volumes/12T/NBA/team_pbp_crawl.log",
    },
    {
        "name": "headshots",
        "cmd": [".venv/bin/python", "external_crawler/crawler/crawl_br_headshots.py", "--resume"],
        "deps": [],
        "priority": 30,
        "probe_sql": None,
        "log": "/Volumes/12T/NBA/headshots_crawl.log",
    },
    {
        "name": "nicknames",
        "cmd": [".venv/bin/python", "external_crawler/crawler/crawl_br_nicknames.py", "--resume", "--rate", "5.0"],
        "deps": [],
        "priority": 30,
        "probe_sql": _NICKNAME_GAP_SQL,
        "log": "/Volumes/12T/NBA/nicknames_crawl.log",
    },
    {
        "name": "bio_ext",
        "cmd": [".venv/bin/python", "external_crawler/crawler/crawl_br_player_bio_ext.py", "--resume", "--rate", "5.0"],
        "deps": [],
        "priority": 30,
        "probe_sql": _BIO_EXT_GAP_SQL,
        "log": "/Volumes/12T/NBA/bio_ext_crawl.log",
    },
    {
        "name": "epm",
        "cmd": [".venv/bin/python", "crawl_dunksandthrees_epm.py"],
        "deps": [],
        "priority": 20,
        "probe_sql": _EPM_GAP_SQL,
        "log": "/Volumes/12T/NBA/epm_crawl.log",
    },
    {
        "name": "epm_actual",
        "cmd": [".venv/bin/python", "crawl_dunksandthrees_epm_actual.py"],
        "deps": [],
        "priority": 20,
        "probe_sql": _EPM_ACTUAL_GAP_SQL,
        "log": "/Volumes/12T/NBA/epm_actual_crawl.log",
    },
    {
        "name": "epm_history",
        "cmd": [".venv/bin/python", "crawl_dunksandthrees_epm_history.py"],
        "deps": [],
        "priority": 15,
        "probe_sql": _EPM_HISTORY_GAP_SQL,
        "log": "/Volumes/12T/NBA/epm_history_crawl.log",
    },
]

TASK_BY_NAME = {t["name"]: t for t in TASKS}
