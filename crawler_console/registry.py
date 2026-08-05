# -*- coding: utf-8 -*-
"""爬虫注册表：NBA 数据平台全部现役爬虫的统一元数据。

字段说明：
- id:        唯一标识（API 路由用）
- name:      中文显示名
- group:     分组（球员数据 / 球队数据 / 调度与维护）
- kind:      "py" | "sh"
- script:    相对项目根的脚本路径
- args:      默认启动参数
- log:       日志文件绝对路径
- pattern:   pgrep -f 匹配模式（进程探测/停止用）
- br:        是否直接请求 Basketball-Reference（并发守卫用，同一时刻仅允许 1 个 BR 爬虫）
- needs_cdp: 是否需要 Chrome CDP 9222（用户过 CF 的浏览器）
- desc:      一句话说明
- tables:    落库目标表（主表在前；crawl_failures 为通用失败登记表不重复列出）
- cache:     本地缓存/归档位置与文件命名规则（相对项目根，除非绝对路径）
- url:       BR 数据源页面模板
"""

PROJECT_ROOT = "/Users/deocheng/Downloads/nba_desktop_omega_mac_migrate_2026-07-13"
VENV_PY = f"{PROJECT_ROOT}/.venv/bin/python"
LOG_DIR = "/Volumes/12T/NBA"

DB = dict(host="127.0.0.1", port=5433, dbname="nba", user="postgres",
          password="R!h0N-ctlg=xB01V_-1VJcFeCCuBjS6UCvV1")

CDP_ENV = {
    "BROWSER_BACKEND": "cdp",
    "CHROME_CDP_URL": "http://127.0.0.1:9222",
    "PGPASSWORD": DB["password"],
}

CRAWLERS = [
    # ── 球员数据 ────────────────────────────────────────────────
    dict(id="shot_chart", name="球员 Shot Chart（马刺优先）", group="球员数据", kind="py",
         script="external_crawler/crawler/crawl_br_player_shot_chart.py", args=["--resume"],
         log=f"{LOG_DIR}/shot_chart_crawl.log", pattern="crawl_br_player_shot_chart.py",
         br=True, needs_cdp=True,
         desc="逐球出手散点(x,y/命中/距离/节次)，SAS 钉最前+上季胜率降序",
         tables=["player_shot_chart"],
         cache="raw_archive/br_players_shot/{slug}/shooting_{year}.html",
         url="basketball-reference.com/players/{x}/{slug}/shooting/{year}"),
    dict(id="gamelog", name="球员 Gamelog", group="球员数据", kind="py",
         script="external_crawler/crawler/crawl_br_gamelog.py", args=["--resume"],
         log=f"{LOG_DIR}/gamelog_crawl.log", pattern="crawl_br_gamelog.py",
         br=True, needs_cdp=True, desc="球员逐场比赛日志",
         tables=["player_gamelog"],
         cache="JSON 整季缓存 {cache_dir}/gamelog_{season}.json（--cache-dir 指定）",
         url="basketball-reference.com/players/{x}/{slug}/gamelog/{year}"),
    dict(id="player_shooting", name="球员 Shooting（联盟页整季）", group="球员数据", kind="py",
         script="external_crawler/crawler/crawl_br_player_shooting.py", args=["--resume"],
         log=f"{LOG_DIR}/player_shooting_crawl.log", pattern="crawl_br_player_shooting.py",
         br=True, needs_cdp=True, desc="投篮距离/区域分布，已覆盖 1997-2026 全 30 季",
         tables=["player_shooting", "player_shooting_404"],
         cache="raw_archive/br_players/{slug}/shooting.html（单页含全部赛季 #shooting/#shooting_playoffs）",
         url="basketball-reference.com/players/{x}/{slug}.html#shooting"),
    dict(id="player_lineup", name="球员 Lineups", group="球员数据", kind="py",
         script="external_crawler/crawler/crawl_br_player_lineup.py", args=["--resume"],
         log=f"{LOG_DIR}/player_lineup_crawl.log", pattern="crawl_br_player_lineup.py",
         br=True, needs_cdp=True, desc="球员阵容组合数据（2/3/5 人组）",
         tables=["player_lineups", "player_lineups_404"],
         cache="raw_archive/br_players/{slug}/lineups_{year}.html",
         url="basketball-reference.com/players/{x}/{slug}/lineups/{year}"),
    dict(id="player_onoff", name="球员 On-Off", group="球员数据", kind="py",
         script="external_crawler/crawler/crawl_br_player_onoff.py", args=["--resume"],
         log=f"{LOG_DIR}/player_onoff_crawl.log", pattern="crawl_br_player_onoff.py",
         br=True, needs_cdp=True, desc="球员在场/离场正负值",
         tables=["player_onoff"],
         cache="raw_archive/br_players/{slug}/on_off_{year}.html",
         url="basketball-reference.com/players/{x}/{slug}/on-off/{year}"),
    dict(id="headshots", name="球员头像", group="球员数据", kind="py",
         script="external_crawler/crawler/crawl_br_headshots.py", args=["--resume"],
         log=f"{LOG_DIR}/headshots_crawl.log", pattern="crawl_br_headshots.py",
         br=True, needs_cdp=True, desc="球员头像图片下载",
         tables=["dim_players（headshot_path/headshot_status/headshot_scraped_at 列）"],
         cache="/Volumes/12T/NBA/headshots/{player_id}.{jpg|png}",
         url="basketball-reference.com/players/{x}/{slug}.html（<img> 头像）"),
    dict(id="nicknames", name="球员绰号", group="球员数据", kind="py",
         script="external_crawler/crawler/crawl_br_nicknames.py", args=[],
         log=f"{LOG_DIR}/nicknames_crawl.log", pattern="crawl_br_nicknames.py",
         br=True, needs_cdp=True, desc="球员绰号抓取",
         tables=["dim_players（nickname 等列）"],
         cache="raw_archive/br_players/{首字母}/{slug}.html（球员主页）",
         url="basketball-reference.com/players/{x}/{slug}.html"),
    dict(id="bio_ext", name="球员扩展档案", group="球员数据", kind="py",
         script="external_crawler/crawler/crawl_br_player_bio_ext.py", args=[],
         log=f"{LOG_DIR}/bio_ext_crawl.log", pattern="crawl_br_player_bio_ext.py",
         br=True, needs_cdp=True, desc="出生地/学校/选秀等扩展信息",
         tables=["dim_players（UPDATE 扩展列）", "player_career_honors（DELETE/INSERT）"],
         cache="raw_archive/br_players/{首字母}/{slug}.html（球员主页，复用）",
         url="basketball-reference.com/players/{x}/{slug}.html"),

    # ── 球队数据 ────────────────────────────────────────────────
    dict(id="team_data", name="球队 PBP + Logo（Phase 1）", group="球队数据", kind="sh",
         script="run_team_data.sh", args=[],
         log=f"{LOG_DIR}/team_data_crawl.log", pattern="crawl_br_team_pbp.py|run_team_data.sh",
         br=True, needs_cdp=True,
         desc="31 队 × 2000-2026 球队赛季 PBP 页 + 队标（当前 134/800+ 队季）",
         tables=["team_pbp_raw（长表，逐 data-stat）", "team_page_raw（同页队级表，零额外请求）"],
         cache="队标 /Volumes/12T/NBA/logo/{slug}-{season}.png；HTML 仅 --dump-html 手动落盘",
         url="basketball-reference.com/teams/{ABBR}/{year}.html"),
    dict(id="team_depth", name="球队深度轮换", group="球队数据", kind="py",
         script="external_crawler/crawler/crawl_br_team_depth.py", args=["--resume"],
         log=f"{LOG_DIR}/team_depth_crawl.log", pattern="crawl_br_team_depth.py",
         br=True, needs_cdp=True, desc="球队 depth chart",
         tables=["team_depth_chart"],
         cache="无 HTML 归档（直抓落库；失败登记 crawl_failures，token 前缀 br_team_depth）",
         url="basketball-reference.com/teams/{ABBR}/{year}_depth.html"),
    dict(id="team_lineups", name="球队阵容组合", group="球队数据", kind="py",
         script="external_crawler/crawler/crawl_br_team_lineups.py", args=["--resume"],
         log=f"{LOG_DIR}/team_lineups_crawl.log", pattern="crawl_br_team_lineups.py",
         br=True, needs_cdp=True, desc="球队级 lineup 数据",
         tables=["team_lineups"],
         cache="无 HTML 归档（失败登记 crawl_failures，token 前缀 br_team_lineups）",
         url="basketball-reference.com/teams/{ABBR}/{year}/lineups/"),
    dict(id="team_onoff", name="球队 On-Off", group="球队数据", kind="py",
         script="external_crawler/crawler/crawl_br_team_onoff.py", args=["--resume"],
         log=f"{LOG_DIR}/team_onoff_crawl.log", pattern="crawl_br_team_onoff.py",
         br=True, needs_cdp=True, desc="球队级 on-off 数据",
         tables=["team_on_off"],
         cache="无 HTML 归档（失败登记 crawl_failures，token 前缀 br_team_onoff）",
         url="basketball-reference.com/teams/{ABBR}/{year}/on-off/"),
    dict(id="team_referees", name="球队裁判记录", group="球队数据", kind="py",
         script="external_crawler/crawler/crawl_br_team_referees.py", args=["--resume"],
         log=f"{LOG_DIR}/team_referees_crawl.log", pattern="crawl_br_team_referees.py",
         br=True, needs_cdp=True, desc="比赛裁判数据",
         tables=["game_referees"],
         cache="无 HTML 归档（失败登记 crawl_failures，token 前缀 br_team_referees）",
         url="basketball-reference.com/teams/{ABBR}/{year}/referees/"),
    dict(id="transactions", name="交易/签约记录", group="球队数据", kind="py",
         script="external_crawler/crawler/crawl_br_transactions.py", args=[],
         log=f"{LOG_DIR}/transactions_crawl.log", pattern="crawl_br_transactions.py",
         br=True, needs_cdp=True, desc="球队 transactions 页",
         tables=["transactions"],
         cache="无 HTML 归档（直抓落库）",
         url="basketball-reference.com/teams/{ABBR}/{year}_transactions.html"),

    # ── 调度与维护 ──────────────────────────────────────────────
    dict(id="relay", name="接力调度器（shot chart→Phase 1）", group="调度与维护", kind="sh",
         script="run_after_shot_chart.sh", args=[],
         log=f"{LOG_DIR}/relay_scheduler.log", pattern="run_after_shot_chart.sh",
         br=False, needs_cdp=False,
         desc="等 shot chart 结束后自动拉起球队 PBP Phase 1，避免双爬虫并行打 BR",
         tables=["（不落库；纯进程调度）"],
         cache="无",
         url="—（每 120s pgrep 探测，结束后检查 CDP 再启 run_team_data.sh）"),
    dict(id="daily", name="每日维护", group="调度与维护", kind="py",
         script="external_crawler/crawler/daily_maintenance.py", args=[],
         log=f"{LOG_DIR}/daily_maintenance.log", pattern="daily_maintenance.py",
         br=True, needs_cdp=True, desc="日常增量更新（伤病/日程等）",
         tables=["player_gamelog（缺口回补）", "transactions", "伤病表（injuries 管线）"],
         cache="无独立缓存（顺序执行：缺口扫描→伤病→交易→校验）",
         url="多页面（gamelog / injuries / transactions）"),
]

# 盯梢巡检脚本（独立按钮，一次性运行取输出）
WATCHER = dict(
    script="/Users/deocheng/.workbuddy/skills/nba-crawler-watch/scripts/watch_crawlers.py",
    python=VENV_PY,
)
