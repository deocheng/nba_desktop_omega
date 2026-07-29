#!/usr/bin/env python3
"""
用 undetected_chromedriver 绕过 BR Cloudflare, 爬缺 PBP 的比赛逐回合数据, 写入 play_by_play。

复用:
- UC 浏览器层 (build_driver / cf_challenge / SessionGone / watchdog)  —— 同 br_fill_teams.py
- 解析器 parse_pbp                                                    —— br_pbp_parse.py (保证字段格式与已有 460 场 BBRef 一致)
- 字段映射 INSERT_SQL                                                 —— ingest_br_pbp.py

目标 (仅 BR 确实有 PBP 的):
- season_type IN (Regular Season, Playoffs, Play-In, NBA Cup) 且 game_date >= 2000-01-01
- 且 game_id / nba_api_id 均无 PBP (双 id 关联, 排除历史数字 id 假象)
- 且 pbp_no_data=false 且 br_no_boxscore=false

规则:
- URL: /boxscores/pbp/{game_id}.html   (game_id 已是 12 位 BR 格式)
- PBP 页 404 => 标记 dim_games.pbp_no_data=true, 永不再爬 (BR 权威源无此比赛 PBP)
- BR 速率硬上限: <= 15 请求/分钟 (最小间隔 4.5s + 滚动 60s 窗口), 用户明确要求, 超出会触发 CF 封禁
- season 按每场实际赛季覆盖 (parse_pbp 内写死 2026)
- 幂等: 写库前 DELETE FROM play_by_play WHERE gameid=game_id

用法:
  python br_fill_pbp.py --limit 3 --dry-run
  python br_fill_pbp.py                 # 全量(断点续跑)
  python br_fill_pbp.py --seasons 2023 2024 2025 2026   # 优先 2023→now
  python br_fill_pbp.py --since 2023-07-01                 # 仅近季(含新比赛增量)
"""
import argparse, re, time, sys, os, shutil, csv, json
import psycopg2
from psycopg2.extras import execute_batch

# 读取项目 .env 的 DB 凭据（含 DB_PASSWORD），使脚本可独立运行
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from br_pbp_parse import parse_pbp
from bs4 import BeautifulSoup
# 桥接：原始 BR HTML 落盘到 raw_archive/br/{season}/{gid}.html（原子写+去重）
from common.bridge_constants import season_start_year
import raw_archiver

DB = dict(
    host=os.environ.get("DB_HOST", "localhost"),
    port=int(os.environ.get("DB_PORT", 5433)),
    user=os.environ.get("DB_USER", "postgres"),
    password=os.environ.get("DB_PASSWORD") or os.environ.get("PGPASSWORD", ""),
    dbname=os.environ.get("DB_NAME", "nba"),
)
BASE = "https://www.basketball-reference.com/boxscores/pbp/{gid}.html"

# 原始 HTML 存档目录 (不放弃任何原始数据, 便于离线重解析/改进解析器)
RAW_DIR = os.path.join(HERE, "pbp_raw")
os.makedirs(RAW_DIR, exist_ok=True)
ISSUES_CSV = os.path.join(HERE, "pbp_issues.csv")


def _br_team_code(suffix, d):
    """把 game_id 尾部球队缩写按比赛日期修正成 BR 当时实际使用的 code。
    d: 'YYYY-MM-DD' 字符串。BR URL 使用历史 franchise code, 而库里 game_id
    可能用现代缩写 (如 2000 年的 New Jersey 存成 BRK), 直接拼 URL 会假 404。"""
    if suffix in ('NJN', 'BRK'):          # Nets: 新泽西 -> 布鲁克林(2012-13)
        return 'NJN' if d < '2012-07-01' else 'BRK'
    if suffix in ('SEA', 'OKC'):          # 超音速 -> 雷霆(2008-09)
        return 'SEA' if d < '2008-07-01' else 'OKC'
    if suffix in ('VAN', 'MEM'):          # 灰熊: 温哥华 -> 孟菲斯(2001-02)
        return 'VAN' if d < '2001-07-01' else 'MEM'
    if suffix in ('CHH', 'NOH', 'NOK', 'NOP'):
        # 老黄蜂(夏洛特)->鹈鹕 franchise
        if d < '2002-07-01':
            return 'CHH'                   # 夏洛特黄蜂
        if d < '2005-07-01':
            return 'NOH'                   # 新奥尔良黄蜂
        if d < '2007-07-01':
            return 'NOK'                   # 卡特里娜, OKC 临时
        if d < '2013-07-01':
            return 'NOH'                   # 迁回新奥尔良
        return 'NOP'                       # 鹈鹕(2013-14)
    if suffix in ('CHA', 'CHO'):
        # 新球队 franchise: 山猫(2004) -> 新黄蜂(2014)
        if d < '2002-07-01':
            return 'CHH'                   # 2000 年 CHO 实为老黄蜂
        if d < '2014-07-01':
            return 'CHA'                   # 夏洛特山猫
        return 'CHO'                       # 新夏洛特黄蜂
    return suffix


def to_br_gid(game_id, gdate):
    """game_id -> BR URL 用的 gid。前9位(日期+序号)不变, 尾部球队 code 按日期修正。"""
    d = gdate if isinstance(gdate, str) else gdate.isoformat()
    prefix, suffix = game_id[:9], game_id[9:]
    return prefix + _br_team_code(suffix, d)


# 独立 profile 目录 (与客队名爬虫隔离)
UDC_DIR = os.path.join(HERE, ".uc_pbp_profile")
os.makedirs(UDC_DIR, exist_ok=True)
MAX_PAGE_RETRY = 3

INSERT_SQL = """
    INSERT INTO play_by_play (
        gameid, season, eventnum, period, clock, clock_seconds,
        h_pts, a_pts, team, playerid, player,
        event_type, subtype, action_verb, result, x, y, dist, description, current_team,
        homedescription, visitordescription, neutraldescription,
        scorehome, scorevisitor, scoremargin, source
    ) VALUES (
        %(gameid)s, %(season)s, %(eventnum)s, %(period)s, %(clock)s, %(clock_seconds)s,
        %(h_pts)s, %(a_pts)s, %(team)s, %(playerid)s, %(player)s,
        %(event_type)s, %(subtype)s, %(action_verb)s, %(result)s, %(x)s, %(y)s, %(dist)s, %(description)s, %(current_team)s,
        %(homedescription)s, %(visitordescription)s, %(neutraldescription)s,
        %(scorehome)s, %(scorevisitor)s, %(scoremargin)s, %(source)s
    )
"""


# ---- 语义层 + 异常留存 (原则: 数据全面性/准确性, 不放弃与结构不符的异常数据) ----
SEMANTIC_SQL = """
    INSERT INTO pbp_semantic (
        gameid, eventnum, actor, actor_team, action, action_detail, outcome, points, raw_description
    ) VALUES (
        %(gameid)s, %(eventnum)s, %(actor)s, %(actor_team)s, %(action)s, %(action_detail)s, %(outcome)s, %(points)s, %(raw_description)s
    )
"""

ISSUES_SQL = """
    INSERT INTO pbp_parse_issues (gameid, br_gid, eventnum, issue_type, raw_text) VALUES (%s, %s, %s, %s, %s)
"""

KNOWN_EVENTS = {
    '', 'shot', 'free throw', 'rebound', 'turnover', 'foul', 'substitution',
    'timeout', 'jump ball', 'violation', 'assist', 'block', 'steal',
    'period start', 'end of period', 'injury', 'instant replay', 'technical'
}
NO_TEAM_EVENTS = {'period start', 'end of period', 'timeout', ''}


def init_schema(conn):
    """建语义层 + 异常留存表 (幂等)."""
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS pbp_semantic (
                id bigserial PRIMARY KEY,
                gameid text,
                eventnum int,
                actor text,
                actor_team text,
                action text,
                action_detail text,
                outcome text,
                points int,
                raw_description text,
                parsed_at timestamptz DEFAULT now()
            );
            CREATE INDEX IF NOT EXISTS idx_pbp_semantic_gameid ON pbp_semantic(gameid);
            CREATE TABLE IF NOT EXISTS pbp_parse_issues (
                id bigserial PRIMARY KEY,
                gameid text,
                br_gid text,
                eventnum int,
                issue_type text,
                raw_text text,
                created_at timestamptz DEFAULT now()
            );
            CREATE INDEX IF NOT EXISTS idx_pbp_issues_gameid ON pbp_parse_issues(gameid);
        """)
        conn.commit()


def _norm_action(row):
    av = (row.get('action_verb') or '').lower()
    et = (row.get('event_type') or '').lower()
    blob = av + ' ' + et   # 同时看 action_verb 与 event_type, 后者更可靠
    if 'free throw' in blob or 'freethrow' in blob:
        return 'free_throw'
    if 'make' in blob or row.get('result') == 'Made':
        return 'make_shot'
    if 'miss' in blob or row.get('result') == 'Missed':
        return 'miss_shot'
    if 'rebound' in blob:
        return 'rebound'
    if 'assist' in blob:
        return 'assist'
    if 'turnover' in blob:
        return 'turnover'
    if 'foul' in blob:
        return 'foul'
    if 'substitution' in blob or blob.strip() == 'sub':
        return 'substitution'
    if 'timeout' in blob:
        return 'timeout'
    if 'jump ball' in blob:
        return 'jump_ball'
    if 'violation' in blob:
        return 'violation'
    if 'block' in blob:
        return 'block'
    if 'steal' in blob:
        return 'steal'
    return et.replace(' ', '_') or 'unknown'


def extract_semantics(rows):
    """从结构化 row 提取语义层 (不动 play_by_play 原始结构, 另建语义视图)."""
    out = []
    for r in rows:
        desc = (r.get('homedescription') or r.get('visitordescription') or
                r.get('neutraldescription') or r.get('description') or '').strip()
        action_cat = _norm_action(r)
        detail = (r.get('subtype') or '').strip()
        if not detail and r.get('dist'):
            try:
                if float(r['dist']) >= 23:
                    detail = '3-pt'
            except (ValueError, TypeError):
                pass
        outcome = (r.get('result') or '').strip()
        points = 0
        if action_cat == 'free_throw':
            points = 0 if outcome == 'Missed' else 1
        elif action_cat == 'make_shot':
            try:
                d = r.get('dist')
                is_three = (detail == '3-pt') or (
                    d is not None and str(d).strip() != '' and float(d) >= 23)
            except (ValueError, TypeError):
                is_three = (detail == '3-pt')
            points = 3 if is_three else 2
        # miss_shot 及非得分事件 => points=0
        out.append(dict(
            gameid=r.get('gameid'), eventnum=r.get('eventnum'),
            actor=(r.get('player') or '').strip(),
            actor_team=(r.get('team') or '').strip(),
            action=action_cat, action_detail=detail, outcome=outcome,
            points=points, raw_description=desc[:1000]))
    return out


def collect_issues(rows, gid, br_gid):
    """收集与表结构/解析预期不符的行, 留存不丢弃 (供分析改进解析器)."""
    issues = []
    for r in rows:
        et = (r.get('event_type') or '').strip().lower()
        desc = (r.get('homedescription') or r.get('visitordescription') or
                r.get('neutraldescription') or r.get('description') or '').strip()
        ev = r.get('eventnum')
        if et and et not in KNOWN_EVENTS:
            issues.append((gid, br_gid, ev, 'unknown_event_type', desc[:500]))
        if not desc and et not in ('period start', 'end of period'):
            issues.append((gid, br_gid, ev, 'empty_description', ''))
        if et in ('shot', 'free throw') and not (r.get('player') or '').strip():
            issues.append((gid, br_gid, ev, 'missing_player_for_shot', desc[:500]))
        if r.get('clock_seconds') is None and et not in NO_TEAM_EVENTS:
            issues.append((gid, br_gid, ev, 'unparseable_clock', desc[:500]))
        if not (r.get('team') or '').strip() and et not in NO_TEAM_EVENTS:
            issues.append((gid, br_gid, ev, 'missing_team', desc[:500]))
    return issues


def append_issues_csv(issue_rows):
    if not issue_rows:
        return
    write_header = not os.path.exists(ISSUES_CSV)
    with open(ISSUES_CSV, 'a', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        if write_header:
            w.writerow(['gameid', 'br_gid', 'eventnum', 'issue_type', 'raw_text'])
        for ir in issue_rows:
            w.writerow(ir)


class RateLimiter:
    """BR 请求硬上限: 最小间隔 + 滚动 60s 窗口, 绝不超过 max_per_minute。"""
    def __init__(self, max_per_minute=15, min_interval=4.5):
        self.max_per_minute = max(1, int(max_per_minute))
        self.min_interval = max(1.0, float(min_interval))
        self._times = []
        self._last = 0.0

    def wait(self):
        now = time.time()
        sleep_for = 0.0
        since_last = now - self._last
        if since_last < self.min_interval:
            sleep_for = self.min_interval - since_last
        cutoff = now - 60.0
        self._times = [t for t in self._times if t > cutoff]
        if len(self._times) >= self.max_per_minute:
            sleep_for = max(sleep_for, self._times[0] + 60.0 - now)
        if sleep_for > 0:
            time.sleep(sleep_for)
        now = time.time()
        self._times.append(now)
        self._last = now


class SessionGone(Exception):
    pass


def get_targets(conn, limit, since=None, seasons=None):
    """只取 BR 确实有 PBP 的缺口: 常规赛/季后赛/Play-In/NBA Cup, 2000 后,
    双 id 均无 PBP, 未标记 pbp_no_data / br_no_boxscore；且【不】抓取可桥接场。

    排除逻辑（铁律：BR 抓取永远不加 --force，幂等、不重爬已覆盖场）：
      1) play_by_play 已按 game_id（BR gid）有 PBP → 排除
      2) play_by_play 已按 nba_api_id 有 PBP → 排除（下设 PBP 已挂 nba_api_id，
         约 4655 场「PBP 已挂 nba_api_id、BR gid 下没有」由桥接覆盖，绝不重爬）
      3) game_id_map.pbp_under_api = true → 显式桥接跳过（与 2) 同源，做双保险）
      4) pbp_no_data / br_no_boxscore = true → 排除（BR 权威源无此 PBP）

    since='YYYY-MM-DD' 仅取该日及之后; seasons=[2023,2024,...] 仅取指定赛季
    (用于"优先 2023→now"——避免从 2000 升序空跑历史已补齐的场)."""
    range_clause = ""
    params = []
    if seasons:
        # 指定赛季：日期地板设为 1996-10-01（BR PBP 真实起点=1996-97 赛季，
        # 更早的 1995-96 及以前 BR 无 PBP，爬也是 404 白费）
        params.append('1996-10-01')
        range_clause = "AND g.season = ANY(%s)"
        params.append([int(s) for s in seasons])  # list -> psycopg2 转 ARRAY，配 ANY()
    elif since:
        params.append(since)
    else:
        params.append('2000-01-01')
    with conn.cursor() as cur:
        cur.execute(f"""
            SELECT g.game_id, g.game_date, g.season, g.away_team_abbr, g.home_team_abbr
            FROM dim_games g
            WHERE g.season_type IN ('Regular Season','Playoffs','Play-In','NBA Cup')
              AND g.game_date >= %s
              AND (g.pbp_no_data IS NULL OR g.pbp_no_data = false)
              AND (g.br_no_boxscore IS NULL OR g.br_no_boxscore = false)
              AND NOT EXISTS (SELECT 1 FROM play_by_play p WHERE p.gameid = g.game_id)
              AND NOT EXISTS (SELECT 1 FROM play_by_play p
                              WHERE g.nba_api_id IS NOT NULL AND p.gameid = g.nba_api_id::text)
              AND NOT EXISTS (SELECT 1 FROM game_id_map m
                              WHERE m.br_gid = g.game_id AND m.pbp_under_api = true)
              {range_clause}
            ORDER BY g.game_date
            {('LIMIT %d' % limit) if limit else ''}
        """, params)
        return cur.fetchall()


def build_driver():
    import undetected_chromedriver as uc
    opts = uc.ChromeOptions()
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--window-size=1280,900")
    opts.add_argument(f"--user-data-dir={UDC_DIR}")
    opts.add_argument("--disable-gpu")
    d = uc.Chrome(options=opts, version_main=149, headless=False)
    d.set_page_load_timeout(60)
    d.implicitly_wait(3)
    return d


def cf_challenge(html, title):
    return ("Just a moment" in html or "cf-browser-verification" in html
            or "请稍候" in title or "cf-chl" in html)


def fetch_pbp_soup(driver, url, br_gid=None, season=None, game_date=None):
    """返回 (soup, status)。status: 'ok' / '404' / 'cf_timeout' / 'no_pbp_table'。
    session 失效抛 SessionGone。
    season: BR 赛季起始年（用于 raw_archive/br/{season}/{gid}.html 落盘）。"""
    from selenium.common.exceptions import WebDriverException
    try:
        driver.get(url)
        html = ""
        for _ in range(20):  # 最多 ~40s 等 CF
            time.sleep(2)
            try:
                html = driver.page_source
                title = driver.title
            except WebDriverException:
                raise SessionGone()
            if not cf_challenge(html, title) and len(html) > 40000:
                break
        else:
            return None, "cf_timeout"
        if "Page Not Found" in html or "404" in (driver.title or ""):
            return None, "404"
        soup = BeautifulSoup(html, "lxml")
        tbl = soup.find("table", id="pbp") or soup.find(
            "table", id=lambda x: x and "pbp" in x.lower())
        if tbl is None:
            return None, "no_pbp_table"
        if br_gid:
            # 落盘原始 BR HTML 到 raw_archive/br/{season}/{gid}.html（原子写+去重）
            try:
                if season is None and game_date is not None:
                    season = season_start_year(game_date)
                raw_archiver.save_br_html(season, br_gid, html)
            except Exception as e:
                print(f"  ! 归档 BR HTML 失败 {br_gid}: {e}", flush=True)
            # 保留旧 pbp_raw 存档（双存，便于离线解析脆弱解析器，不删既有行为）
            try:
                with open(os.path.join(RAW_DIR, f"{br_gid}.html"), "w", encoding="utf-8") as fh:
                    fh.write(html)
            except Exception as e:
                print(f"  ! 存原始HTML失败 {br_gid}: {e}", flush=True)
        return soup, "ok"
    except WebDriverException as e:
        if "invalid session id" in str(e) or "browser has closed" in str(e):
            raise SessionGone()
        raise


def run_once(args):
    conn = psycopg2.connect(**DB)
    conn.autocommit = False
    init_schema(conn)   # 确保语义层 / 异常留存表存在
    targets = get_targets(conn, args.limit,
                         since=args.since, seasons=args.seasons)
    print(f"[i] 待处理 PBP 缺口: {len(targets)}  dry_run={args.dry_run}", flush=True)
    if not targets:
        conn.close()
        return "empty"
    driver = None
    limiter = RateLimiter(max_per_minute=args.rate_per_min, min_interval=args.min_interval)
    ok = fail = total_events = 0
    fails = []
    rc = "crashed"
    try:
        driver = build_driver()
        for i, (gid, gdate, season, a_abbr, h_abbr) in enumerate(targets, 1):
            br_gid = to_br_gid(gid, gdate)   # BR URL 用历史 franchise code
            url = BASE.format(gid=br_gid)
            soup, status = None, None
            for attempt in range(1, MAX_PAGE_RETRY + 1):
                try:
                    limiter.wait()  # 严格 <=15 BR 请求/分钟
                    soup, status = fetch_pbp_soup(driver, url, br_gid, season=season)
                    if soup is not None or status == "404":
                        break
                except SessionGone:
                    print(f"  ! driver 崩溃, 重建中... (场 {gid})", flush=True)
                    try: driver.quit()
                    except Exception: pass
                    driver = build_driver()
                    soup, status = None, "session_rebuilt"
            if soup is None:
                print(f"[{i}/{len(targets)}] {gid} FAIL({status}) {url}", flush=True)
                fail += 1; fails.append((gid, status))
                if status == "404":
                    if not args.dry_run:
                        with conn.cursor() as cur:
                            cur.execute(
                                "UPDATE dim_games SET pbp_no_data=true WHERE game_id=%s",
                                (gid,))
                        conn.commit()
                continue
            rows = parse_pbp(soup, a_abbr or "", h_abbr or "", gid)
            if not rows:
                print(f"[{i}/{len(targets)}] {gid} FAIL(parsed_0_events) {url}", flush=True)
                fail += 1; fails.append((gid, "parsed_0"))
                continue
            # season 按实际赛季覆盖 (parse_pbp 写死 2026)
            for r in rows:
                r["season"] = season
            semantics = extract_semantics(rows)
            issues = collect_issues(rows, gid, br_gid)
            print(f"[{i}/{len(targets)}] {gid} {gdate} S{season}  {a_abbr}@{h_abbr}  "
                  f"events={len(rows)}  semantic={len(semantics)}  issues={len(issues)}", flush=True)
            if not args.dry_run:
                with conn.cursor() as cur:
                    cur.execute("DELETE FROM play_by_play WHERE gameid=%s", (gid,))
                    execute_batch(cur, INSERT_SQL, rows, page_size=200)
                    if semantics:
                        cur.execute("DELETE FROM pbp_semantic WHERE gameid=%s", (gid,))
                        execute_batch(cur, SEMANTIC_SQL, semantics, page_size=200)
                    if issues:
                        cur.execute("DELETE FROM pbp_parse_issues WHERE gameid=%s", (gid,))
                        execute_batch(cur, ISSUES_SQL, issues, page_size=200)
                    # 根因修复：成功写入 PBP 后必须翻转 pbp_imported 标志，
                    # 否则 dashboard 覆盖率代理指标（dim_games.pbp_imported）永远不同步
                    # —— 这正是 03-04~14-15 整段显示 0% 覆盖的真因。
                    # （404 分支已 SET pbp_no_data=true 做对称处理，此处补成功分支。）
                    cur.execute("UPDATE dim_games SET pbp_imported=true WHERE game_id=%s", (gid,))
                conn.commit()
                append_issues_csv(issues)   # 本地 CSV 累积 (双存)
            total_events += len(rows)
            ok += 1
        rc = "done"
    except KeyboardInterrupt:
        print("\n[interrupted] 用户中断", flush=True)
        rc = "interrupted"
    except Exception as e:
        print(f"\n[FATAL] {type(e).__name__}: {e}", flush=True)
        rc = "crashed"
    finally:
        if driver is not None:
            try: driver.quit()
            except Exception: pass
        try: conn.close()
        except Exception: pass
    print(f"\n[done] 成功 {ok}  失败 {fail}  写入事件 {total_events}", flush=True)
    if fails:
        print("失败明细:", fails[:30], flush=True)
    return rc


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--rate-per-min", type=int, default=15, help="BR 请求/分钟硬上限")
    ap.add_argument("--min-interval", type=float, default=4.5, help="两次请求最小间隔秒")
    ap.add_argument("--max-restart", type=int, default=30)
    ap.add_argument("--since", type=str, default=None,
                    help="仅爬 game_date >= 此日期的场 (如 2023-07-01), 用于优先近季")
    ap.add_argument("--seasons", nargs='+', type=int, default=None,
                    help="仅爬指定赛季 (如 --seasons 2023 2024 2025 2026), 优先近季")
    args = ap.parse_args()

    restart = 0
    while True:
        rc = run_once(args)
        if rc in ("empty", "interrupted", "done"):
            print(f"[watchdog] 结束 rc={rc}", flush=True)
            break
        restart += 1
        if restart > args.max_restart:
            print(f"[watchdog] 已达最大重启次数 {args.max_restart}, 退出", flush=True)
            break
        print(f"[watchdog] 检测到崩溃, 第 {restart} 次自动重启...", flush=True)
        os.system("pkill -f 'chrome.*uc_pbp_profile' 2>/dev/null; pkill -f 'undetected_chromedriver' 2>/dev/null")
        time.sleep(3)
        shutil.rmtree(UDC_DIR, ignore_errors=True)
        os.makedirs(UDC_DIR, exist_ok=True)
        time.sleep(2)


if __name__ == "__main__":
    main()
