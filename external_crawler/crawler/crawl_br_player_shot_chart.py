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
from bs4 import BeautifulSoup

from common.br_player_page import BRPlayerPageCrawler, DB_CONFIG
from common.browser import quit_driver  # 模块级（基类无 quit_driver 方法，勿用 self.quit_driver）

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

    # ── 枚举 (slug, season, team) 对 ───────────────────────────────
    def enumerate_pairs(self, conn, priority_gap: bool = False) -> List[Tuple[str, int, str]]:
        """待抓 (slug, season, team) 对，来自已落库的 player_shooting。

        排序（优先级从高到低）：
          ① 马刺(SAS)各赛季数据永远最优先（用户是马刺球迷）；
          ② 其余按「球员上赛季(2025-26)所在球队的常规赛胜率」降序；
          ③ 同队并列则按 slug、再按赛季新→旧。
        这样优秀队伍和球员先入库。胜率榜现算自 dim_games，零额外爬取。

        排除：① 已在 player_shot_chart 落库；② 已登记失败（404/空页）。
        priority_gap=True 时仅返回「该 (slug,season) 在 player_shot_chart 缺失」的对。
        """
        cur = conn.cursor()
        if priority_gap:
            cur.execute(
                """
                SELECT DISTINCT ps.player_id, ps.season, ps.team
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
                SELECT DISTINCT ps.player_id, ps.season, ps.team
                FROM player_shooting ps
                LEFT JOIN player_shot_chart sc
                       ON sc.player_id = ps.player_id AND sc.season = ps.season
                LEFT JOIN crawl_failures cf
                       ON cf.task_type='br_player_shot_chart'
                      AND cf.game_id = 'br_player_shot_chart|' || ps.player_id || '|' || ps.season::text
                WHERE sc.player_id IS NULL AND cf.game_id IS NULL
                """
            )
        rows = [(r[0], int(r[1]), r[2]) for r in cur.fetchall() if r[0]]
        cur.close()
        # ── 优先级排序：马刺最前，其余按上赛季(2026)球队胜率降序 ──
        ranking = self.load_team_ranking(conn, season=2026)
        team_map = self.load_player_team_map(conn)
        SPURS = "SAS"

        def _key(row):
            slug, season, team = row
            is_spurs = (team == SPURS)
            last_team = team_map.get(slug, team)
            win_pct = ranking.get(last_team, 0.0)
            return (0 if is_spurs else 1, -win_pct, slug, -int(season))

        rows.sort(key=_key)
        n_spurs = sum(1 for r in rows if r[2] == SPURS)
        logger.info("枚举排序完成：共 %d 对（马刺优先 %d 对），非马刺按 2025-26 胜率降序",
                    len(rows), n_spurs)
        return rows

    # ── dim_games 缓存（game_date, home, away）→ (game_id, season_type) ──
    def load_games_cache(self, conn) -> Dict[Tuple[str, str, str], Tuple[str, str]]:
        cur = conn.cursor()
        cur.execute(
            "SELECT game_date, home_team_abbr, away_team_abbr, game_id, season_type "
            "FROM dim_games WHERE game_date IS NOT NULL"
        )
        cache: Dict[Tuple[str, str, str], Tuple[str, str]] = {}
        for gd, h, a, gid, st in cur.fetchall():
            gd = gd.isoformat() if hasattr(gd, "isoformat") else str(gd)
            cache[(gd, h, a)] = (gid, st)
        cur.close()
        return cache

    def _resolve_game(self, cache, game_date, player_team, opp) -> Tuple[Optional[str], Optional[str]]:
        if not game_date or not player_team or not opp:
            return (None, None)
        hit = cache.get((game_date, player_team, opp)) or cache.get((game_date, opp, player_team))
        if not hit:
            return (None, None)
        gid, st = hit
        # season_type 归一：'Regular Season'→'Regular'，'Playoffs'→'Playoffs'
        if st and st.lower().startswith("playoff"):
            st = "Playoffs"
        elif st and "regular" in st.lower():
            st = "Regular"
        return (gid, st)

    # ── 解析 + 注入 player/game ─────────────────────────────────────
    def build_rows(self, conn, slug: str, season: int, team: str,
                 rec: Dict, games_cache) -> Dict:
        gid, stype = self._resolve_game(games_cache, rec.get("game_date"), team, rec.get("opponent_abbr"))
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
    def _crawl_pair(self, conn, driver, slug: str, season: int, team: str,
                    games_cache) -> int:
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
        self.save_raw_html(slug, season, html)
        recs = parse_shot_chart_html(html)
        if not recs:
            self.register_failure(conn, f"{self.TASK_TYPE}|{slug}|{season}")
            logger.warning("  ⚠️ %s/%s 页面正常但 0 球（真无数据/结构变）→ 登记", slug, season)
            return 0
        rows = [self.build_rows(conn, slug, season, team, r, games_cache) for r in recs]
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
    TRANSIENT_MAX_RETRY = 30

    def _rebuild_driver(self, old_driver):
        """瞬态故障后重建浏览器连接（旧会话可能已死）。失败返回 None。"""
        try:
            quit_driver()
        except Exception:  # noqa: BLE001
            pass
        try:
            return self.get_driver()
        except Exception as exc:  # noqa: BLE001
            logger.warning("  [瞬态] 重建浏览器连接失败: %s", exc)
            return None

    # ── 主循环（迭代 (slug,season,team) 对）──────────────────────
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
        driver = None
        try:
            if not dry_run:
                driver = self.get_driver()
            for i, (slug, season, team) in enumerate(pairs):
                if resume and not skip_done_check and self._pair_done(conn, slug, season):
                    logger.info("  [resume] 跳过 %s/%s（已落库）", slug, season)
                    continue
                if dry_run:
                    logger.info("  [dry-run] 计划抓取 %s/%s (team=%s)", slug, season, team)
                    continue
                # ── 单对抓取 + 瞬态故障暂停重试（不登记失败）──
                n = 0
                attempt = 0
                while True:
                    try:
                        n = self._crawl_pair(conn, driver, slug, season, team, games_cache)
                        break
                    except Exception as exc:  # noqa: BLE001  含 TransientFetchError
                        attempt += 1
                        try:
                            conn.rollback()
                        except Exception:  # noqa: BLE001
                            pass
                        if attempt > self.TRANSIENT_MAX_RETRY:
                            logger.error(
                                "🔴 [瞬态] %s/%s 重试 %d 次仍失败，整体退出（未登记失败，"
                                "下次 --resume 会重抓）。最后错误: %s",
                                slug, season, self.TRANSIENT_MAX_RETRY, exc)
                            logger.info("完成：upsert %d 球（提前退出于第 %d 对）", total, i)
                            return total
                        _wait = (self.TRANSIENT_WAITS[attempt - 1]
                                 if attempt <= len(self.TRANSIENT_WAITS)
                                 else self.TRANSIENT_WAIT_S)
                        logger.warning(
                            "⏸️ [瞬态] %s/%s 抓取失败(第 %d/%d 次): %s → 等 %ds 后重建连接重试"
                            "（若是 CF，请在 Chrome 打开 basketball-reference.com 点验证）",
                            slug, season, attempt, self.TRANSIENT_MAX_RETRY, exc, _wait)
                        time.sleep(_wait)
                        nd = self._rebuild_driver(driver)
                        if nd is not None:
                            driver = nd
                total += n
                logger.info("  %s/%s: upsert %d 球", slug, season, n)
                if i < len(pairs) - 1:
                    self.rate_limit()
        finally:
            if driver is not None:
                try:
                    quit_driver()
                except Exception:
                    pass
        logger.info("完成：upsert %d 球（处理 %d 对）", total, len(pairs))
        return total

    def rework_from_archive(self, slug: str, season: int, conn) -> int:
        path = Path(self.RAW_ARCHIVE) / slug / f"shooting_{season}.html"
        if not path.exists():
            logger.warning("[rework] 归档缺失: %s", path)
            return 0
        html = path.read_text(encoding="utf-8")
        team = None
        cur = conn.cursor()
        cur.execute("SELECT team FROM player_shooting WHERE player_id=%s AND season=%s LIMIT 1",
                    (slug, season))
        r = cur.fetchone()
        if r:
            team = r[0]
        cur.close()
        cache = self.load_games_cache(conn)
        recs = parse_shot_chart_html(html)
        if not recs:
            logger.warning("[rework] %s/%s 解析 0 球", slug, season)
            return 0
        rows = [self.build_rows(conn, slug, season, team, x, cache) for x in recs]
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
            # 取这些 slug 在 player_shooting 的全部 (slug,season,team)
            cur = conn.cursor()
            q = ("SELECT DISTINCT player_id, season, team FROM player_shooting "
                  "WHERE player_id = ANY(%s)")
            cur.execute(q, (slugs,))
            pairs = [(r[0], int(r[1]), r[2]) for r in cur.fetchall()]
            cur.close()
            if args.season is not None:
                pairs = [(s, sea, t) for (s, sea, t) in pairs if sea == args.season]
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
