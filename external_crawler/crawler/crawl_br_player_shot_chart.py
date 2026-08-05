"""crawl_br_player_shot_chart.py — BR 球员 shot chart 逐球散点 → player_shot_chart。

数据源（已实测锁定）：/players/{letter}/{slug}/shooting/{year} 主队页内的
  <div class="shot-area"> 里每球一个
    <div class="tooltip make|miss" style="top:Xpx;left:Ypx;" tip="...">
逐球数据（球场像素坐标 + 命中/分值/距离/日期/对阵/节次）**完全在静态
HTML**，无需 XHR。实测 LeBron 2018：2089 球全解析、0 失败。

坐标系统：BR 用 500px 宽半场 SVG（court-nba-bbr.svg）。
  x_px = div 的 left（0=左边线，500=右）；y_px = div 的 top（0=远端对手
  篮下，500=近端本方篮下）。x_norm=(left-250)/250∈[-1,1]（左负右正，0=中线）；
  y_norm=top/500∈[0,1]（0=对手篮，1=本方篮）。

game 关联：用 dim_games 缓存（game_date, home/away_team_abbr）→ game_id +
  season_type（Regular Season/Playoffs）。shot-area 含整季 RS+PO，故按日期 JOIN
  即得 season_type，无需另抓子页。

复用：common.br_player_page.BRPlayerPageCrawler（反屏蔽/限速/CF/upsert/失败登记/
  原始 HTML 归档全部来自基类，零新建）。runner 设 BROWSER_BACKEND=cdp 连用户
  已清 CF 的 Chrome(9222)。

用法
----
  python crawl_br_player_shot_chart.py --dry-run
  python crawl_br_player_shot_chart.py --slugs jamesle01 --season 2018 --dump-html /tmp/x.html
  python crawl_br_player_shot_chart.py --resume --limit 5
  python crawl_br_player_shot_chart.py --rework jamesle01 2018
"""
import argparse
import logging
import re
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import psycopg2
from bs4 import BeautifulSoup, Comment

from common.br_player_page import BRPlayerPageCrawler, DB_CONFIG
from common.browser import quit_driver, reconnect_driver  # 模块级（基类无这些方法，勿用 self.xxx）
from common.season_priority import season_tier  # 赛季抓取优先级（2010+ > 2000s > 1980s > pre-1980）
from common.season_type_norm import canon_season_type  # season_type 写入约定统一对齐 dim_games

# ── 常量 ───────────────────────────────────────────────────────────────
DOMAIN = "player_shot_chart"


class TransientFetchError(RuntimeError):
    """瞬态抓取故障（CF 挑战/空响应/连接问题）——绝不写 crawl_failures。"""
TABLE = "player_shot_chart"
RAW_ARCHIVE = "raw_archive/br_players_shot"
MON2NUM = {
    "Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6,
    "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12,
}
CONFLICT_COLS = (
    "player_id", "game_date", "opponent_abbr",
    "period", "time_remaining", "x_px", "y_px",
)

# ── 解析纯函数 ──────────────────────────────────────────────────────────
_DATE_RE = re.compile(r"^(?P<mon>[A-Za-z]+)\s+(?P<day>\d+),\s*(?P<yr>\d+),\s*(?P<mu>.+)$")
_SHOT_RE = re.compile(r"(Made|Missed)\s+(?P<val>\d)-pointer\s+from\s+(?P<dist>\d+)\s+ft")
_QTR_RE = re.compile(r"(?P<q>\d)(?:st|nd|rd|th)?\s*Qtr|OT")
_TIME_RE = re.compile(r"(\d+):(\d+)")


def _parse_tip(tip: str) -> Optional[Dict]:
    """解析 shot tooltip 文本 → 结构化字段。失败返回 None。"""
    if not tip:
        return None
    parts = [p.strip() for p in tip.split("<br>")]
    m = _DATE_RE.match(parts[0])
    if not m:
        return None
    mon = MON2NUM.get(m.group("mon").title())
    if mon is None:
        return None
    try:
        game_date = f"{int(m.group('yr')):04d}-{mon:02d}-{int(m.group('day')):02d}"
    except ValueError:
        return None
    mu = m.group("mu").strip()           # "CLE vs BOS" / "CLE at MIL"
    toks = mu.split()
    is_home = None
    opp = None
    if len(toks) >= 3:
        is_home = (toks[1].lower() == "vs")   # vs=主，at=客
        opp = toks[2]
    quarter = parts[1] if len(parts) > 1 else None
    period = None
    time_remaining = None
    if quarter:
        q = _QTR_RE.search(quarter)
        if q:
            period = 5 if q.group(0).upper().startswith("OT") else int(q.group("q"))
        t = _TIME_RE.search(quarter)
        if t:
            time_remaining = f"{t.group(1)}:{t.group(2)}"
    shot = parts[2] if len(parts) > 2 else ""
    sm = _SHOT_RE.search(shot)
    value = int(sm.group("val")) if sm else None
    dist = int(sm.group("dist")) if sm else None
    return dict(
        game_date=game_date, opponent_abbr=opp, is_home=is_home,
        period=period, time_remaining=time_remaining,
        shot_value=value, dist_ft=dist,
    )


def parse_shot_chart_html(html: str) -> List[Dict]:
    """从 BR shot chart 页 HTML 抽取全部逐球记录（原始，未注入 player/game）。"""
    if not html:
        return []
    soup = BeautifulSoup(html, "lxml")
    area = soup.find("div", class_="shot-area")
    if area is None:
        # 🔴 BR 经典套路：静态 HTML 里 shot-area 被包在 <!-- --> 注释内，
        # 由页面 JS 运行时解注入 DOM。在线抓取(渲染后 DOM)能直接找到，
        # 但本地归档/未渲染快照必须 Comment 感知才解析得到（与 team_lineups 同坑）。
        for c in soup.find_all(string=lambda t: isinstance(t, Comment)):
            if "shot-area" in c:
                inner = BeautifulSoup(c, "lxml")
                area = inner.find("div", class_="shot-area")
                if area is not None:
                    break
        if area is None:
            return []
    out: List[Dict] = []
    for d in area.find_all("div", class_=re.compile(r"tooltip")):
        cls = " ".join(d.get("class", []))
        made = "make" in cls
        style = d.get("style", "")
        top = re.search(r"top:\s*([\d.]+)px", style)
        left = re.search(r"left:\s*([\d.]+)px", style)
        if not top or not left:
            continue
        tip = d.get("tip", "") or d.get("title", "")
        rec = _parse_tip(tip)
        if rec is None:
            continue
        rec.update(
            made=made,
            x_px=float(left.group(1)),
            y_px=float(top.group(1)),
        )
        out.append(rec)
    return out


# ── 具体爬虫 ────────────────────────────────────────────────────────────
class PlayerShotChartCrawler(BRPlayerPageCrawler):
    DOMAIN = DOMAIN
    TASK_TYPE = "br_player_shot_chart"
    TABLE = TABLE
    RAW_ARCHIVE = RAW_ARCHIVE
    CONFLICT_COLS = CONFLICT_COLS

    # (slug, season) 已落库判定：player_shot_chart 有该行即视为已抓（一页覆盖整季）
    def _pair_done(self, conn, slug: str, season: int) -> bool:
        cur = conn.cursor()
        cur.execute(
            f"SELECT 1 FROM {self.TABLE} WHERE player_id=%s AND season=%s LIMIT 1",
            (slug, season),
        )
        found = cur.fetchone() is not None
        cur.close()
        return found

    def register_failure(self, conn, token: str) -> None:
        """幂等版：已存在同 (game_id, task_type) 则跳过，杜绝重复堆积。

        基类原实现是裸 INSERT（crawl_failures 主键在 id，无
        (game_id,task_type) 唯一约束）→ 同对会被反复插入。
        此处先查后插；已知缺口（404/空页）只记一次，--resume
        重跑不再重抓、不再堆重复失败行。
        """
        if conn is None:
            return
        try:
            conn.rollback()
        except Exception:  # noqa: BLE001
            pass
        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT 1 FROM crawl_failures "
                "WHERE game_id=%s AND task_type=%s LIMIT 1",
                (token, self.TASK_TYPE),
            )
            if cur.fetchone() is not None:
                cur.close()
                return
            cur.execute(
                "INSERT INTO crawl_failures (game_id, task_type, resolved) "
                "VALUES (%s, %s, %s)",
                (token, self.TASK_TYPE, False),
            )
            conn.commit()
            cur.close()
        except Exception as _e:  # noqa: BLE001
            try:
                conn.rollback()
            except Exception:  # noqa: BLE001
                pass
            logger.warning("register_failure 写入失败（已忽略）: %s", _e)

    def build_url(self, slug: str, season: int) -> str:
        letter = (slug[0].lower() if slug else "a")
        return (f"https://www.basketball-reference.com/players/"
                f"{letter}/{slug}/shooting/{season}")

    def save_raw_html(self, slug: str, season: int, html: str) -> Path:
        d = Path(self.RAW_ARCHIVE) / slug
        d.mkdir(parents=True, exist_ok=True)
        p = d / f"shooting_{season}.html"
        p.write_text(html, encoding="utf-8")
        return p

    # ── 上赛季(2026=2025-26)常规赛胜率榜：team_abbr -> win_pct ──
    def load_team_ranking(self, conn, season: int = 2026) -> Dict[str, float]:
        """上赛季常规赛成绩排名：从 dim_games 比分现算 team_abbr→win_pct(0..1)。

        完全数据驱动、零额外爬取。season=2026 即 2025-26 赛季
        （dim_games.season 存结束年）。用 home/away_pts 现算胜负，
        不依赖可能为空 home_wl/away_wl 列。
        """
        cur = conn.cursor()
        cur.execute(
            """
            WITH g AS (
              SELECT home_team_abbr AS t, home_pts AS pf, away_pts AS pa FROM dim_games
                WHERE season=%(s)s AND season_type ILIKE '%%regular%%' AND home_pts IS NOT NULL
              UNION ALL
              SELECT away_team_abbr AS t, away_pts AS pf, home_pts AS pa FROM dim_games
                WHERE season=%(s)s AND season_type ILIKE '%%regular%%' AND away_pts IS NOT NULL
            )
            SELECT t,
                   count(*) FILTER (WHERE pf>pa)::numeric / NULLIF(count(*),0) AS win_pct
            FROM g GROUP BY t
            """,
            {"s": season},
        )
        ranking = {r[0]: (float(r[1]) if r[1] is not None else 0.0) for r in cur.fetchall()}
        cur.close()
        return ranking

    def load_player_team_map(self, conn) -> Dict[str, str]:
        """每个 slug → 其上赛季(2026)球队；无 2026 行则用其最近赛季球队。

        用于把「球员」映射到上赛季战绩榜（而非逐季行球队），从而让
        好队/好球员的全部历史赛季整体靠前（满足「优秀队伍和球员先入库」）。
        """
        cur = conn.cursor()
        cur.execute("SELECT DISTINCT player_id, team FROM player_shooting WHERE season=2026")
        m: Dict[str, str] = {r[0]: r[1] for r in cur.fetchall()}
        cur.execute(
            "SELECT player_id, team FROM player_shooting p "
            "WHERE season = (SELECT MAX(season) FROM player_shooting p2 WHERE p2.player_id=p.player_id)"
        )
        for pid, team in cur.fetchall():
            m.setdefault(pid, team)
        cur.close()
        return m

    def load_active_stars(self, conn) -> set:
        """现役明星球员集合（slug 文本）：all_star_selections 中登过全明星，
        且 dim_players.year_to>=2025（即 2024-25 或 2025-26 仍出战 → 现役）。
        player_id 与 player_shooting 对齐，可直接用于 Tier 判定。"""
        cur = conn.cursor()
        cur.execute(
            """
            SELECT DISTINCT a.player_id
            FROM all_star_selections a
            JOIN dim_players d ON d.player_id = a.player_id
            WHERE d.year_to >= 2025
            """
        )
        s = {r[0] for r in cur.fetchall()}
        cur.close()
        return s

    def load_spurs_pairs(self, conn) -> set:
        """马刺(SAS)球员的 (player_id, season) 集合，用于 Tier1 优先。
        按 (球员,赛季) 维度（不再按球队行重复），因 player_shot_chart 唯一键不含 team。"""
        cur = conn.cursor()
        cur.execute(
            "SELECT DISTINCT player_id, season FROM player_shooting WHERE team='SAS'"
        )
        s = {(r[0], int(r[1])) for r in cur.fetchall()}
        cur.close()
        return s

    # ── 枚举 (slug, season) 对 ───────────────────────────────────
    def enumerate_pairs(self, conn, priority_gap: bool = False) -> List[Tuple[str, int]]:
        """待抓 (slug, season) 对，来自已落库的 player_shooting。

        排序（优先级从高到低）：
          〇 赛季分层（全局政策，最外层）：2010~现在 > 2000~2009 > 1980~1999 > 1980 以前；
          ① 现役明星球员（全明星 + dim_players.year_to>=2025）全部赛季最优先；
          ② 马刺(SAS)各赛季（用户是马刺球迷）；
          ③ 其余按「球员上赛季(2025-26)所在球队的常规赛胜率」降序。
        现役明星 / 马刺 Tier 内部均按赛季新→旧；其余按胜率→赛季新→旧。
        胜率榜现算自 dim_games，零额外爬取。

        排除：① 已在 player_shot_chart 落库；② 已登记失败（404/空页）。
        priority_gap=True 时仅返回「该 (slug,season) 在 player_shot_chart 缺失」的对。
        """
        cur = conn.cursor()
        if priority_gap:
            cur.execute(
                """
                SELECT DISTINCT ps.player_id, ps.season
                FROM player_shooting ps
                LEFT JOIN player_shot_chart sc
                       ON sc.player_id = ps.player_id AND sc.season = ps.season
                LEFT JOIN crawl_failures cf
                       ON cf.task_type='br_player_shot_chart'
                      AND cf.game_id = 'br_player_shot_chart|' || ps.player_id || '|' || ps.season::text
                WHERE sc.player_id IS NULL AND cf.game_id IS NULL
                """
            )
        else:
            cur.execute(
                """
                SELECT DISTINCT ps.player_id, ps.season
                FROM player_shooting ps
                LEFT JOIN player_shot_chart sc
                       ON sc.player_id = ps.player_id AND sc.season = ps.season
                LEFT JOIN crawl_failures cf
                       ON cf.task_type='br_player_shot_chart'
                      AND cf.game_id = 'br_player_shot_chart|' || ps.player_id || '|' || ps.season::text
                WHERE sc.player_id IS NULL AND cf.game_id IS NULL
                """
            )
        rows = [(r[0], int(r[1])) for r in cur.fetchall() if r[0]]
        cur.close()
        # ── 优先级排序：现役明星最前 → 马刺 → 其余按上赛季(2026)球队胜率降序 ──
        ranking = self.load_team_ranking(conn, season=2026)
        team_map = self.load_player_team_map(conn)
        active_star = self.load_active_stars(conn)
        spurs_pairs = self.load_spurs_pairs(conn)   # set of (player_id, season)
        SPURS = "SAS"

        def _key(row):
            slug, season = row
            is_active_star = (slug in active_star)
            is_spurs = (slug, season) in spurs_pairs
            last_team = team_map.get(slug)
            win_pct = ranking.get(last_team, 0.0)
            if is_active_star:
                sub = (0, -int(season), slug)
            elif is_spurs:
                sub = (1, -int(season), slug)
            else:
                sub = (2, -win_pct, -int(season), slug)
            # 最外层 = 赛季分层优先级（用户 2026-08-01 政策）：
            #   2010~现在 > 2000~2009 > 1980~1999 > 1980 以前
            # 层内保留既有「现役明星→马刺→胜率」子序。
            return (season_tier(season), sub)

        rows.sort(key=_key)
        n_star = sum(1 for r in rows if r[0] in active_star)
        n_spurs = sum(1 for r in rows if (r[0], r[1]) in spurs_pairs)
        logger.info("枚举排序完成：共 %d 对（按(球员,赛季)去重；现役明星 %d 对 / 马刺 %d 对），其余按 2025-26 胜率降序",
                    len(rows), n_star, n_spurs)
        return rows

    # ── dim_games 缓存（game_date, team_abbr）→ (game_id, season_type, home, away) ──
    def load_games_cache(self, conn) -> Dict[Tuple[str, str], Tuple[str, str, str, str]]:
        """(比赛日, 球队) → (game_id, season_type, home, away)。
        同时以主/客队为键，使「按对手查」即可定位比赛（shot chart 每条只带对手与 is_home，
        而 player_shot_chart 无 team 列，无需球员所属队参与）。"""
        cur = conn.cursor()
        cur.execute(
            "SELECT game_date, home_team_abbr, away_team_abbr, game_id, season_type "
            "FROM dim_games WHERE game_date IS NOT NULL"
        )
        cache: Dict[Tuple[str, str], Tuple[str, str, str, str]] = {}
        for gd, h, a, gid, st in cur.fetchall():
            gd = gd.isoformat() if hasattr(gd, "isoformat") else str(gd)
            if h:
                cache[(gd, h)] = (gid, st, h, a)
            if a:
                cache[(gd, a)] = (gid, st, h, a)
        cur.close()
        return cache

    def _resolve_game(self, cache, game_date, opponent_abbr) -> Tuple[Optional[str], Optional[str]]:
        """按 (比赛日, 对手) 定位比赛 → (game_id, season_type)。
        一条 shot 自带 game_date + opponent_abbr（解析自 tooltip），足以唯一锁定
        dim_games 中的那场比赛，无需球员所属球队参与（player_shot_chart 也无 team 列）。
        season_type 直接透传 dim_games 权威值，经 canon_season_type 归一（保证与 dim_games 字典一致，不再 remap 成 'Regular'）。"""
        if not game_date or not opponent_abbr:
            return (None, None)
        hit = cache.get((game_date, opponent_abbr))
        if not hit:
            return (None, None)
        gid, st, _home, _away = hit
        return (gid, canon_season_type(st))

    # ── 解析 + 注入 player/game ─────────────────────────────────────
    def build_rows(self, conn, slug: str, season: int, rec: Dict, games_cache) -> Dict:
        gid, stype = self._resolve_game(games_cache, rec.get("game_date"), rec.get("opponent_abbr"))
        row = dict(rec)
        row["player_id"] = slug
        row["season"] = int(season)
        row["game_id"] = gid
        row["season_type"] = stype
        # 坐标归一
        row["x_norm"] = round((row["x_px"] - 250.0) / 250.0, 4)
        row["y_norm"] = round(row["y_px"] / 500.0, 4)
        return row

    def parse(self, html, season_type="Regular", team=None):
        return parse_shot_chart_html(html)

    def upsert(self, conn, rows):
        # 按唯一键去重（同一批内重复键会触发 ON CONFLICT DO UPDATE
        # cardinality 报错；BR shot-area 偶发同球列两次，保留首次）。
        seen = {}
        uniq = []
        for r in rows:
            k = tuple(r.get(c) for c in self.CONFLICT_COLS)
            if k not in seen:
                seen[k] = 1
                uniq.append(r)
        if len(uniq) < len(rows):
            logger.warning("  ⚠️ 去重 %d→%d 行（唯一键重复）", len(rows), len(uniq))
        return self._upsert_rows(conn, self.TABLE, uniq, self.CONFLICT_COLS)

    # ── 单 (slug,season) 抓取 ─────────────────────────────────────
    def _crawl_pair(self, conn, driver, slug: str, season: int, games_cache) -> int:
        """抓取单对。

        失败分级（🔴 2026-07-28 修，防瞬态故障污染 crawl_failures）：
        - BR 404               → register_failure（永久，合理跳过）
        - 页面正常但无 shot 数据 → register_failure（真无数据，如 1997-99 无 shot chart）
        - CF 挑战页 / 空响应    → 抛 TransientFetchError（不登记！上层暂停重试）
        - 其他异常(WS 500 等)   → 原样上抛（上层按瞬态处理，不登记）
        """
        url = self.build_url(slug, season)
        html = self.fetch_team_page(driver, url)
        if not html:
            if getattr(self, "_last_fetch_404", False):
                self.register_failure(conn, f"{self.TASK_TYPE}|{slug}|{season}")
                logger.warning("  ⚠️ %s/%s 命中 BR 404 → 登记跳过", slug, season)
                return 0
            if getattr(self, "_last_fetch_cf", False):
                raise TransientFetchError(f"CF 挑战页: {slug}/{season}")
            raise TransientFetchError(f"空响应/导航失败: {slug}/{season}")
        recs = parse_shot_chart_html(html)
        if not recs:
            # 🔴 2026-07-30 修：0 球须区分「真无数据」vs「残页」。
            # 残页 = 既无 shot-area 容器（含注释版）也无 "No shooting" 提示
            #   （散点 widget JS 未渲染完就取了 DOM，或 CF 半拦截骨架页）。
            # 残页绝不登记 crawl_failures（否则永久跳过=静默缺口）、
            # 也不落归档（防污染本地重放），抛瞬态走上层等待重试。
            has_area = "shot-area" in html
            no_data_note = "No shooting" in html
            if not (has_area or no_data_note):
                raise TransientFetchError(
                    f"残页(无shot-area且无无数据提示): {slug}/{season}"
                )
            self.save_raw_html(slug, season, html)
            self.register_failure(conn, f"{self.TASK_TYPE}|{slug}|{season}")
            logger.warning("  ⚠️ %s/%s 页面完整但 0 球（真无数据）→ 登记", slug, season)
            return 0
        self.save_raw_html(slug, season, html)
        rows = [self.build_rows(conn, slug, season, r, games_cache) for r in recs]
        n = self.upsert(conn, rows)
        conn.commit()
        return n

    # ── 瞬态故障暂停重试 ──────────────────────────────────────────
    # CF 挑战 / WebSocket 拒连 / 导航失败 等属环境问题：数据仍在 BR 上，
    # 绝不登记 crawl_failures（否则 resume 永久跳过 = 静默缺口）。
    # 策略：等 TRANSIENT_WAIT_S 后重建浏览器连接重试，最多 TRANSIENT_MAX_RETRY
    # 次（约 30 分钟）；耗尽则整体退出（留给下次 --resume），并打醒目日志。
    # 渐进等待：前几次快速重试（Chrome 冻结后台标签/会话单次失效场景），
    # 之后长等（真 CF/断网场景，给用户留点验证时间）。
    TRANSIENT_WAITS = [5, 5, 15, 30]   # 第1-4次重试的等待秒数
    TRANSIENT_WAIT_S = 60              # 第5次起
    TRANSIENT_MAX_RETRY = 30           # CF 类（全局墙）：沿用大上限 + cf_breaker 冷却，耗尽则整体退出
    # 🔴 2026-07-30 加固：非 CF 瞬态（残页/WS 拒连/空响应）单对重试上限。
    # 超过则「本回跳过该对、放行后续」，杜绝单坏 URL 卡死全爬虫（如 bealbr01/2017 残页）。
    NON_CF_PAIR_MAX_RETRY = 6

    def _rebuild_driver(self, old_driver):
        """瞬态故障后重建浏览器连接：复用同一专用 tab 重连（不关 tab、不新建空白页）。

        改用 common.browser.reconnect_driver —— 它直接重连到本爬虫已开的那个 page
        target（新开 ws 即可），绝不 quit+重建（那会关掉旧 tab 又开新 about:blank，
        既闪空白页又漏 tab）。仅当该 target 真死了才全量重建。
        """
        try:
            return reconnect_driver()
        except Exception as exc:  # noqa: BLE001
            logger.warning("  [瞬态] 重建浏览器连接失败: %s", exc)
            return None

    # ── 主循环（迭代 (slug,season) 对）──────────────────────
    def run_pairs(self, conn, pairs, resume=False, dry_run=False, limit=None,
                  skip_done_check=False):
        if limit is not None:
            pairs = pairs[: max(0, limit)]
        if not pairs:
            logger.info("枚举为空，无需抓取")
            return 0
        logger.info("待处理 (slug,season) 对: %d", len(pairs))
        games_cache = self.load_games_cache(conn) if not dry_run else {}
        total = 0
        skipped_pairs = 0
        driver = None
        try:
            if not dry_run:
                driver = self.get_driver()
            for i, (slug, season) in enumerate(pairs):
                if resume and not skip_done_check and self._pair_done(conn, slug, season):
                    logger.info("  [resume] 跳过 %s/%s（已落库）", slug, season)
                    continue
                if dry_run:
                    logger.info("  [dry-run] 计划抓取 %s/%s", slug, season)
                    continue
                # ── 单对抓取 + 瞬态故障暂停重试（不登记失败）──
                n = 0
                attempt = 0
                while True:
                    try:
                        n = self._crawl_pair(conn, driver, slug, season, games_cache)
                        break
                    except Exception as exc:  # noqa: BLE001  含 TransientFetchError
                        attempt += 1
                        try:
                            conn.rollback()
                        except Exception:  # noqa: BLE001
                            pass
                        # 区分 CF（全局墙）与非 CF（残页/WS 拒连/空响应）瞬态：
                        #   CF    → 沿用大上限 + cf_breaker 冷却；耗尽则整体退出（留待真人过验证后 --resume）。
                        #   非 CF → 小上限；耗尽则「本回跳过该对、放行后续」，杜绝单坏 URL 卡全爬虫。
                        is_cf = bool(getattr(self, "_last_fetch_cf", False)) or "CF" in str(exc).upper()
                        cap = self.TRANSIENT_MAX_RETRY if is_cf else self.NON_CF_PAIR_MAX_RETRY
                        if attempt > cap:
                            if is_cf:
                                logger.error(
                                    "🔴 [CF] %s/%s 连续 %d 次 CF 挑战，整体退出（未登记失败，"
                                    "请在 Chrome 打开 basketball-reference.com 点验证后 --resume）。"
                                    "最后错误: %s", slug, season, cap, exc)
                                logger.info("完成：upsert %d 球（提前退出于第 %d 对）", total, i)
                                return total
                            logger.warning(
                                "⏭️ [跳过] %s/%s 非CF瞬态重试 %d 次仍失败，本回跳过该对"
                                "（不登记 crawl_failures，下次 --resume 会重抓）。最后错误: %s",
                                slug, season, cap, exc)
                            skipped_pairs += 1
                            break
                        _wait = (self.TRANSIENT_WAITS[attempt - 1]
                                 if attempt <= len(self.TRANSIENT_WAITS)
                                 else self.TRANSIENT_WAIT_S)
                        logger.warning(
                            "⏸️ [瞬态] %s/%s 抓取失败(第 %d/%d 次%s): %s → 等 %ds 后重建连接重试"
                            "（若是 CF，请在 Chrome 打开 basketball-reference.com 点验证）",
                            slug, season, attempt, cap,
                            " [CF]" if is_cf else "", exc, _wait)
                        time.sleep(_wait)
                        nd = self._rebuild_driver(driver)
                        if nd is not None:
                            driver = nd
                total += n
                if n > 0:
                    logger.info("  %s/%s: upsert %d 球", slug, season, n)
                if i < len(pairs) - 1:
                    self.rate_limit()
        finally:
            if driver is not None:
                try:
                    quit_driver()
                except Exception:
                    pass
        logger.info("完成：upsert %d 球（处理 %d 对，跳过 %d 对）", total, len(pairs), skipped_pairs)
        return total

    def rework_from_archive(self, slug: str, season: int, conn) -> int:
        path = Path(self.RAW_ARCHIVE) / slug / f"shooting_{season}.html"
        if not path.exists():
            logger.warning("[rework] 归档缺失: %s", path)
            return 0
        html = path.read_text(encoding="utf-8")
        cache = self.load_games_cache(conn)
        recs = parse_shot_chart_html(html)
        if not recs:
            logger.warning("[rework] %s/%s 解析 0 球", slug, season)
            return 0
        rows = [self.build_rows(conn, slug, season, x, cache) for x in recs]
        n = self.upsert(conn, rows)
        conn.commit()
        logger.info("[rework] %s/%s 重放完成: %d 球", slug, season, n)
        return n


logger = logging.getLogger("br_player_shot_chart")  # noqa: E402  (置于类后)


def main() -> None:
    p = argparse.ArgumentParser(description="BR 球员 shot chart 逐球散点爬虫")
    p.add_argument("--slugs", type=str, default=None,
                   help="逗号分隔 slug（定点测试，例 jamesle01,curryst01）")
    p.add_argument("--season", type=int, default=None,
                   help="限定单季（配合 --slugs 用）")
    p.add_argument("--priority-gap", action="store_true",
                   help="仅枚举 player_shot_chart 缺失的 (slug,season) 对")
    p.add_argument("--dry-run", action="store_true",
                   help="只枚举+打印计划，不取浏览器、不写库")
    p.add_argument("--resume", action="store_true",
                   help="跳过已落库 (slug,season) 对（断点续传）")
    p.add_argument("--rework", type=str, default=None,
                   help="从归档重解析某 slug（免爬）：--rework jamesle01 后接 --season")
    p.add_argument("--limit", type=int, default=None,
                   help="最多处理 N 对（小批量验证，不跑全量）")
    p.add_argument("--dump-html", type=str, default=None,
                   help="把抓到的 HTML 落盘到该路径（调试用）")
    args = p.parse_args()

    crawler = PlayerShotChartCrawler(dry_run=args.dry_run, resume=args.resume)

    if args.rework:
        if args.season is None:
            print("[rework] 必须配合 --season 指定赛季")
            return
        conn = psycopg2.connect(**DB_CONFIG)
        try:
            n = crawler.rework_from_archive(args.rework, int(args.season), conn)
        finally:
            conn.close()
        print(f"[rework] {args.rework}/{args.season}: upsert {n} 球")
        return

    conn = psycopg2.connect(**DB_CONFIG)
    try:
        if args.slugs:
            slugs = [s.strip() for s in args.slugs.split(",") if s.strip()]
            # 取这些 slug 在 player_shooting 的全部 (slug,season)；team 不再用于枚举
            cur = conn.cursor()
            q = ("SELECT DISTINCT player_id, season FROM player_shooting "
                  "WHERE player_id = ANY(%s)")
            cur.execute(q, (slugs,))
            pairs = [(r[0], int(r[1])) for r in cur.fetchall()]
            cur.close()
            if args.season is not None:
                pairs = [(s, sea) for (s, sea) in pairs if sea == args.season]
        else:
            pairs = crawler.enumerate_pairs(conn, priority_gap=args.priority_gap)
        # enumerate_pairs 已在 DB 端过滤已完成/已失败对，run_pairs 无需再逐对查 _pair_done
        # （--slugs 手动路径不过滤，保留防御性检查）
        skip_done_check = (args.slugs is None)
        if args.limit is not None:
            pairs = pairs[: max(0, args.limit)]
        total = crawler.run_pairs(
            conn, pairs, resume=args.resume,
            dry_run=args.dry_run, limit=args.limit,
            skip_done_check=skip_done_check,
        )
        print(f"完成：upsert {total} 球（处理 {len(pairs)} 对）")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
