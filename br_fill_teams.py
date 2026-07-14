#!/usr/bin/env python3
"""
用 undetected_chromedriver 绕过 BR Cloudflare, 爬缺客队名的比赛 boxscore, 回填 dim_games。

要点:
- game_id 结尾是主队代码(NBA码), home_team_abbr 已是 BR 代码, 用后者替换尾部构造 URL
- CF 挑战约 8s 自动通过, 需轮询等待真实内容
- scorebox 块内 team 链接顺序为 [客队, 主队]
- BR boxscore 404 视为权威源无此比赛详情: 标记 br_no_boxscore=true, 永不再爬, 不去其他源凑

用法:
  python br_fill_teams.py --limit 3 --dry-run
  python br_fill_teams.py                 # 全量(断点续跑)
"""
import argparse, re, time, random, sys, os, shutil
import psycopg2

DB = dict(host="localhost", port=5433, user="postgres", dbname="nba")
BASE = "https://www.basketball-reference.com/boxscores/{gid}.html"

# 放项目目录, 避免 /tmp 被清导致脚本/配置丢失
HERE = os.path.dirname(os.path.abspath(__file__))
UDC_DIR = os.path.join(HERE, ".uc_br_profile")
os.makedirs(UDC_DIR, exist_ok=True)
MAX_DRIVER_RETRY = 5
MAX_PAGE_RETRY = 3


def to_br_gid(game_id, home_abbr):
    """game_id 尾部 3 位是 NBA 主队代码, home_team_abbr 已是 BR 代码。
    用 BR 代码替换尾部 3 位构造 BR boxscore URL。"""
    if home_abbr and len(game_id) >= 3:
        return game_id[:-3] + home_abbr
    return game_id


def load_known_404():
    """已弃用: 404 标记现直接存 dim_games.br_no_boxscore。保留空函数避免引用报错。"""
    return set()


def get_targets(conn, limit):
    with conn.cursor() as cur:
        cur.execute(f"""
            SELECT game_id, game_date, home_team_abbr, home_team_name
            FROM dim_games
            WHERE (away_team_abbr IS NULL OR away_team_abbr='')
              AND br_no_boxscore = false
            ORDER BY game_date
            {('LIMIT %d' % limit) if limit else ''}
        """)
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


def fetch_teams(driver, url):
    """返回 [(客abbr,客name),(主abbr,主name)] 或 (None, status)。
    若 Chrome session 已失效则抛 SessionGone, 由主循环重建 driver 后重试。"""
    from selenium.common.exceptions import WebDriverException
    try:
        driver.get(url)
        html = ""
        for _ in range(20):  # 最多 ~40s
            time.sleep(2)
            try:
                html = driver.page_source
                title = driver.title
            except WebDriverException:
                raise SessionGone()
            if not cf_challenge(html, title) and len(html) > 60000:
                break
        else:
            return None, "cf_timeout"
        if "Page Not Found" in html or "404" in driver.title:
            return None, "404"
        m = re.search(r'<div class="scorebox">(.*?)<div class="scorebox_meta">', html, re.S)
        if not m:
            return None, "no_scorebox"
        links = re.findall(r'/teams/([A-Z]{3})/\d{4}\.html[^>]*>\s*([^<]+?)\s*</a>', m.group(1))
        uniq = []
        for a, n in links:
            if a not in [x[0] for x in uniq]:
                uniq.append((a, n.strip()))
        if len(uniq) < 2:
            return None, f"only_{len(uniq)}_teams"
        return uniq[:2], "ok"
    except WebDriverException as e:
        if "invalid session id" in str(e) or "browser has closed" in str(e):
            raise SessionGone()
        raise


class SessionGone(Exception):
    pass


def run_once(args):
    """跑一轮: 处理当前所有待补记录, 直到全部完成或 driver 无法恢复。
    返回 'empty'(已完成) / 'done' / 'interrupted' / 'crashed'(需外层重建)。"""
    conn = psycopg2.connect(**DB)
    conn.autocommit = False
    targets = get_targets(conn, args.limit)
    print(f"[i] 待处理: {len(targets)}  dry_run={args.dry_run}", flush=True)
    if not targets:
        conn.close()
        return "empty"
    driver = None
    ok = fail = 0
    fails = []
    rc = "crashed"
    try:
        driver = build_driver()
        for i, (gid, gdate, h_abbr, h_name) in enumerate(targets, 1):
            br_gid = to_br_gid(gid, h_abbr)
            url = BASE.format(gid=br_gid)
            teams, status = None, None
            for attempt in range(1, MAX_PAGE_RETRY + 1):
                try:
                    teams, status = fetch_teams(driver, url)
                    if teams is not None or status in ("404",):
                        break
                except SessionGone:
                    print(f"  ! driver 崩溃, 重建中... (场 {gid})", flush=True)
                    try: driver.quit()
                    except Exception: pass
                    driver = build_driver()
                    teams, status = None, "session_rebuilt"
            if teams is None:
                print(f"[{i}/{len(targets)}] {gid} FAIL({status}) {url}", flush=True)
                fail += 1; fails.append((gid, status))
                if status == "404":
                    # BR 权威源无此比赛 boxscore 页: 打标记, 永不再爬, 不去其他源凑
                    if not args.dry_run:
                        with conn.cursor() as cur:
                            cur.execute(
                                "UPDATE dim_games SET br_no_boxscore=true WHERE game_id=%s",
                                (gid,))
                        conn.commit()
                time.sleep(args.sleep)
                continue
            (a_abbr, a_name), (hb, hn) = teams  # 客, 主
            print(f"[{i}/{len(targets)}] {gid} {gdate}  主 {hb}/{hn}  <- 客 {a_abbr}/{a_name}", flush=True)
            if not args.dry_run:
                with conn.cursor() as cur:
                    cur.execute("""
                        UPDATE dim_games
                        SET away_team_abbr = %s,
                            away_team_name = %s,
                            home_team_name = COALESCE(NULLIF(home_team_name,''), %s)
                        WHERE game_id = %s
                    """, (a_abbr, a_name, hn, gid))
                conn.commit()
            ok += 1
            time.sleep(args.sleep + random.uniform(0, 1.5))
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
    print(f"\n[done] 成功 {ok}  失败 {fail}", flush=True)
    if fails:
        print("失败明细:", fails[:30], flush=True)
    return rc


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--sleep", type=float, default=3.0)
    ap.add_argument("--max-restart", type=int, default=20,
                    help="整个进程级崩溃后最多自动重启轮数")
    args = ap.parse_args()

    restart = 0
    while True:
        rc = run_once(args)
        if rc in ("empty", "interrupted", "done"):
            print(f"[watchdog] 结束 rc={rc}", flush=True)
            break
        # crashed -> 清掉可能残留的 chrome, 重建 profile 目录, 重启
        restart += 1
        if restart > args.max_restart:
            print(f"[watchdog] 已达最大重启次数 {args.max_restart}, 退出", flush=True)
            break
        print(f"[watchdog] 检测到崩溃, 第 {restart} 次自动重启...", flush=True)
        os.system("pkill -f 'chrome.*uc_br_profile' 2>/dev/null; pkill -f 'undetected_chromedriver' 2>/dev/null")
        time.sleep(3)
        shutil.rmtree(UDC_DIR, ignore_errors=True)
        os.makedirs(UDC_DIR, exist_ok=True)
        time.sleep(2)


if __name__ == "__main__":
    main()
