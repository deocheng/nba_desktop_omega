"""crawl_br_player_page_extras.py — BR 球员主页面 "More" 菜单 5 类缺失数据爬虫。

数据源: https://www.basketball-reference.com/players/{letter}/{slug}.html
  主球员页 HTML 内含 5 张 "More" 菜单锚点表（2026-07-29 已用 LeBron 样本核实，
  全部在同一份 HTML 内，非独立子页）：
    * Game Highs        -> #highs-reg-season (Regular) / #highs-playoffs (Playoffs)
    * Playoffs Series   -> #playoffs_series
    * Similarity Scores -> #sims-thru (through) / #sims-career
    * All-Star Games    -> #all_star
    * Adjusted Shooting -> #adj_shooting (Regular) / #adj_shooting_post (Playoffs)
    * Overview 文本块    -> #info（顶部 meta 简介：full_name/instagram/绰号串/各 meta 标签/整段 raw）

设计：抓**主页面一次**即解析全部 6 类（避免逐表重复抓 3MB 页 ×N 倍限速成本）。
复用 common.br_team_page.BRTeamPageCrawler 的全部已验证原语（fetch_team_page 含
CF/404 检测、rate_limit、register_failure、_upsert_rows、get_driver/ensure_cf_cleared）。
解析层为纯函数，便于单测。

入库: 6 张表 + 404 隔离表；upsert ON CONFLICT 幂等。

用法
----
  python crawl_br_player_page_extras.py --resume
  python crawl_br_player_page_extras.py --slugs jamesle01,antetgi01 --limit 5
  python crawl_br_player_page_extras.py --rework jamesle01
"""
from __future__ import annotations

import argparse
import logging
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import psycopg2
from bs4 import BeautifulSoup, Comment

from common.br_team_page import (
    BRTeamPageCrawler,
    DB_CONFIG,
    safe_int,
    safe_float,
    _row_data_stats,
)
from common.browser import ensure_cf_cleared
from common.player_page_cache import is_valid_player_page

logger = logging.getLogger("player_page_extras")

# BR 主页面基地址（.html 后缀，非目录式）
BR_MAIN_URL = "https://www.basketball-reference.com/players/{letter}/{slug}.html"

# over_header 占位列（data-stat 为这些值时该行是多级表头，非数据）
_OVER_HEADER_STATS = {
    "header_empty_0", "header_per_g", "block_auto_header_Totals",
    "header_tmp1", "header_tmp2", "header_lg_adj",
    "block_auto_header_Shooting %",
}

# 主页面缓存（供 --rework）
RAW_ARCHIVE = "raw_archive/br_players"

# ── 纯函数：解析 ────────────────────────────────────────────────────────────
def _season_end(s: Optional[str]) -> Optional[int]:
    """'2003-04' -> 2004；非法返回 None。"""
    if not s:
        return None
    m = re.match(r"(\d{4})-(\d{2})", s.strip())
    if not m:
        return None
    return 2000 + int(m.group(2))


def _find_table(soup: BeautifulSoup, table_id: str):
    """注释感知表查找（BR 季后赛/部分表包在 HTML 注释里）。"""
    t = soup.find("table", id=table_id)
    if t is not None:
        return t
    for c in soup.find_all(string=lambda x: isinstance(x, Comment)):
        if f'id="{table_id}"' in c:
            sub = BeautifulSoup(c, "html.parser")
            t = sub.find("table", id=table_id)
            if t is not None:
                return t
    return None


def _iter_data_rows(table) -> Dict[str, str]:
    """yield 每个数据行的 {data-stat: text}，跳过 thead / over_header / 占位行。"""
    for row in table.find_all("tr"):
        if "thead" in (row.get("class") or []):
            continue
        if "over_header" in (row.get("class") or []):
            continue
        vals = _row_data_stats(row)
        if not vals:
            continue
        if any(k in _OVER_HEADER_STATS for k in vals):
            continue
        yield vals


def parse_game_highs(html: str, season_type: str) -> List[Dict]:
    soup = BeautifulSoup(html, "html.parser")
    tid = "highs-reg-season" if season_type == "Regular" else "highs-playoffs"
    t = _find_table(soup, tid)
    if t is None:
        return []
    out = []
    for v in _iter_data_rows(t):
        s = v.get("season")
        se = _season_end(s)
        if not s or s == "Season" or se is None:
            continue
        out.append({
            "season_type": season_type,
            "season_end": se,
            "season_text": s,
            "age": safe_int(v.get("age")),
            "team": (v.get("team") or None),
            "league": (v.get("league") or None),
            "time_on_court": (v.get("time_on_court") or None),
            "fg": safe_int(v.get("fg")), "fga": safe_int(v.get("fga")),
            "fg3": safe_int(v.get("fg3")), "fg3a": safe_int(v.get("fg3a")),
            "fg2": safe_int(v.get("fg2")), "fg2a": safe_int(v.get("fg2a")),
            "ft": safe_int(v.get("ft")), "fta": safe_int(v.get("fta")),
            "orb": safe_int(v.get("orb")), "drb": safe_int(v.get("drb")),
            "trb": safe_int(v.get("trb")), "ast": safe_int(v.get("ast")),
            "stl": safe_int(v.get("stl")), "blk": safe_int(v.get("blk")),
            "tov": safe_int(v.get("tov")), "pf": safe_int(v.get("pf")),
            "pts": safe_int(v.get("pts")),
            "game_score": safe_float(v.get("game_score")),
        })
    return out


def parse_playoffs_series(html: str) -> List[Dict]:
    soup = BeautifulSoup(html, "html.parser")
    t = _find_table(soup, "playoffs_series")
    if t is None:
        return []
    out = []
    for v in _iter_data_rows(t):
        s = v.get("year_id")
        se = _season_end(s)
        psr = v.get("ps_round")
        if not s or s == "Season" or se is None or not psr:
            # 跳过表头行与 "Career Totals" 等汇总行（无 ps_round）
            continue
        out.append({
            "season_end": se,
            "season_text": s,
            "age": safe_int(v.get("age")),
            "team_abbr": (v.get("team_name_abbr") or None),
            "lg": (v.get("comp_name_abbr") or None),
            "ps_round": psr,
            "opp_abbr": (v.get("opp_name_abbr") or None),
            "series_result": (v.get("series_result") or None),
            "games": safe_int(v.get("games")),
            "mp_per_g": safe_float(v.get("mp_per_g")),
            "pts_per_g": safe_float(v.get("pts_per_g")),
            "trb_per_g": safe_float(v.get("trb_per_g")),
            "ast_per_g": safe_float(v.get("ast_per_g")),
            "stl_per_g": safe_float(v.get("stl_per_g")),
            "blk_per_g": safe_float(v.get("blk_per_g")),
            "fg": safe_int(v.get("fg")), "fga": safe_int(v.get("fga")),
            "fg_pct": safe_float(v.get("fg_pct")),
            "fg3": safe_int(v.get("fg3")), "fg3a": safe_int(v.get("fg3a")),
            "fg3_pct": safe_float(v.get("fg3_pct")),
            "fg2": safe_int(v.get("fg2")), "fg2a": safe_int(v.get("fg2a")),
            "fg2_pct": safe_float(v.get("fg2_pct")),
            "efg_pct": safe_float(v.get("efg_pct")),
            "ft": safe_int(v.get("ft")), "fta": safe_int(v.get("fta")),
            "ft_pct": safe_float(v.get("ft_pct")),
            "orb": safe_int(v.get("orb")), "drb": safe_int(v.get("drb")),
            "trb": safe_int(v.get("trb")), "ast": safe_int(v.get("ast")),
            "stl": safe_int(v.get("stl")), "blk": safe_int(v.get("blk")),
            "tov": safe_int(v.get("tov")), "pf": safe_int(v.get("pf")),
            "pts": safe_int(v.get("pts")),
            "awards": (v.get("awards") or None),
        })
    return out


def parse_similarity(html: str, scope: str) -> List[Dict]:
    soup = BeautifulSoup(html, "html.parser")
    tid = "sims-thru" if scope == "thru" else "sims-career"
    t = _find_table(soup, tid)
    if t is None:
        return []
    out = []
    for v in _iter_data_rows(t):
        name = v.get("player")
        if not name or name == "Player":
            continue
        scores = [safe_float(v.get(f"year{i}")) for i in range(1, 24)]
        out.append({
            "scope": scope,
            "comparable_name": name,
            "sim_score": safe_float(v.get("sim_score")),
            "year_scores": scores,  # 入库时转 jsonb
        })
    return out


def parse_all_star(html: str) -> List[Dict]:
    soup = BeautifulSoup(html, "html.parser")
    t = _find_table(soup, "all_star")
    if t is None:
        return []
    out = []
    for v in _iter_data_rows(t):
        s = v.get("season")
        se = _season_end(s)
        if not s or s == "Season" or se is None:
            continue
        out.append({
            "season_end": se,
            "season_text": s,
            "age": safe_int(v.get("age")),
            "team_id": (v.get("team_id") or None),
            "lg_id": (v.get("lg_id") or None),
            "pos": (v.get("pos") or None),
            "g": safe_int(v.get("g")), "gs": safe_int(v.get("gs")),
            "mp": (v.get("mp") or None),
            "fg": safe_int(v.get("fg")), "fga": safe_int(v.get("fga")),
            "fg_pct": safe_float(v.get("fg_pct")),
            "fg3": safe_int(v.get("fg3")), "fg3a": safe_int(v.get("fg3a")),
            "fg3_pct": safe_float(v.get("fg3_pct")),
            "ft": safe_int(v.get("ft")), "fta": safe_int(v.get("fta")),
            "ft_pct": safe_float(v.get("ft_pct")),
            "orb": safe_int(v.get("orb")), "drb": safe_int(v.get("drb")),
            "trb": safe_int(v.get("trb")), "ast": safe_int(v.get("ast")),
            "stl": safe_int(v.get("stl")), "blk": safe_int(v.get("blk")),
            "tov": safe_int(v.get("tov")), "pf": safe_int(v.get("pf")),
            "pts": safe_int(v.get("pts")),
        })
    return out


def parse_adj_shooting(html: str, season_type: str) -> List[Dict]:
    soup = BeautifulSoup(html, "html.parser")
    tid = "adj_shooting" if season_type == "Regular" else "adj_shooting_post"
    t = _find_table(soup, tid)
    if t is None:
        return []
    out = []
    for v in _iter_data_rows(t):
        s = v.get("year_id")
        se = _season_end(s)
        if not s or s == "Season" or se is None:
            continue
        out.append({
            "season_type": season_type,
            "season_end": se,
            "season_text": s,
            "age": safe_int(v.get("age")),
            "team_abbr": (v.get("team_name_abbr") or None),
            "lg": (v.get("comp_name_abbr") or None),
            "pos": (v.get("pos") or None),
            "games": safe_int(v.get("games")),
            "games_started": safe_int(v.get("games_started")),
            "mp": safe_int(v.get("mp")),
            "fg_pct": safe_float(v.get("fg_pct")),
            "fg2_pct": safe_float(v.get("fg2_pct")),
            "fg3_pct": safe_float(v.get("fg3_pct")),
            "efg_pct": safe_float(v.get("efg_pct")),
            "ft_pct": safe_float(v.get("ft_pct")),
            "ts_pct": safe_float(v.get("ts_pct")),
            "fta_per_fga_pct": safe_float(v.get("fta_per_fga_pct")),
            "fg3a_per_fga_pct": safe_float(v.get("fg3a_per_fga_pct")),
            "adj_fg_pct": safe_float(v.get("adj_fg_pct")),
            "adj_fg2_pct": safe_float(v.get("adj_fg2_pct")),
            "adj_fg3_pct": safe_float(v.get("adj_fg3_pct")),
            "adj_efg_pct": safe_float(v.get("adj_efg_pct")),
            "adj_ft_pct": safe_float(v.get("adj_ft_pct")),
            "adj_ts_pct": safe_float(v.get("adj_ts_pct")),
            "adj_fta_per_fga_pct": safe_float(v.get("adj_fta_per_fga_pct")),
            "adj_fg3a_per_fga_pct": safe_float(v.get("adj_fg3a_per_fga_pct")),
            "fg_pts_added": safe_float(v.get("fg_pts_added")),
            "ts_pts_added": safe_float(v.get("ts_pts_added")),
            "awards": (v.get("awards") or None),
        })
    return out


# 标签集合（用于 _ov_field 的"下一个标签"lookahead，避免跨字段吞值）
_OV_LABELS = ("Position", "Shoots", "Team", "Born", "Relatives", "High School",
              "Recruiting Rank", "Draft", "NBA Debut", "Experience")


def _ov_field(text: str, label: str) -> Optional[str]:
    """从 #info 文本中取 `Label: value`，value 取到下一个已知标签或 ▪ 或结尾为止。"""
    pat = re.compile(
        rf"{label}\s*:\s*(.+?)(?=\s+(?:{'|'.join(_OV_LABELS)})\s*:|▪|$)",
        re.IGNORECASE | re.DOTALL,
    )
    m = pat.search(text)
    if not m:
        return None
    val = re.sub(r"\s+", " ", m.group(1)).strip().rstrip("▪").strip()
    return val or None


def parse_overview(html: str) -> Optional[Dict]:
    """解析主页面顶部 #info 文本块（球员 Overview）。

    返回单人一行 dict；#info 缺失（CF 挑战页 / 404 页）返回 None。
    含：full_name / instagram / 绰号展示串(nickname_display) / 各 meta 标签 / 整段原始文本。
    """
    soup = BeautifulSoup(html, "html.parser")
    info = soup.find("div", id="info")
    if info is None:
        return None
    text = re.sub(r"\s+", " ", info.get_text(" ", strip=True))

    # 全名：第一个含 "▪" 的 <p>，取 "▪" 之前的文本（避免把展示名/发音引导混进来）
    full_name = None
    for _p in info.find_all("p"):
        _pt = _p.get_text(" ", strip=True)
        if "▪" in _pt:
            full_name = _pt.split("▪")[0].strip()
            break
    if not full_name:
        h1 = info.find("h1")
        if h1:
            full_name = h1.get_text(strip=True)

    # Instagram 句柄 + 其后括号里的绰号展示串
    instagram = None
    m = re.search(r"Instagram:\s*([A-Za-z0-9_.]+)", text)
    if m:
        instagram = m.group(1)
    nickname_display = None
    m = re.search(r"Instagram:\s*[A-Za-z0-9_.]+\s*\(([^)]+)\)", text)
    if m:
        nickname_display = m.group(1).strip()

    position_text = _ov_field(text, "Position")
    # shoots 仅取单词（高度/体重紧跟其后，属独立字段）
    shoots = None
    m = re.search(r"Shoots:\s*(\w+)", text)
    if m:
        shoots = m.group(1)
    # height / weight（如 "Right 6-9 , 250lb (206cm, 113kg)"）
    height_display = None
    weight_display = None
    m = re.search(r"(\d+-\d+)\s*,\s*(\d+)\s*lb", text)
    if m:
        height_display = m.group(1)
        weight_display = f"{m.group(2)}lb"
    team_text = _ov_field(text, "Team")
    born_text = _ov_field(text, "Born")
    relatives_text = _ov_field(text, "Relatives")
    high_school = _ov_field(text, "High School")
    recruiting_rank = _ov_field(text, "Recruiting Rank")
    draft_text = _ov_field(text, "Draft")
    nba_debut = _ov_field(text, "NBA Debut")
    # experience 仅取 "N years"（其后无标签，会吞到页尾，须限定）
    experience_text = None
    m = re.search(r"Experience:\s*(\d+\s*years?)", text, re.IGNORECASE)
    if m:
        experience_text = m.group(1)

    return {
        "full_name": full_name,
        "instagram": instagram,
        "nickname_display": nickname_display,
        "position_text": position_text,
        "shoots": shoots,
        "height_display": height_display,
        "weight_display": weight_display,
        "team_text": team_text,
        "born_text": born_text,
        "relatives_text": relatives_text,
        "high_school": high_school,
        "recruiting_rank": recruiting_rank,
        "draft_text": draft_text,
        "nba_debut": nba_debut,
        "experience_text": experience_text,
        "overview_raw": text,
    }


# ── 爬虫类 ─────────────────────────────────────────────────────────────────
class PlayerPageExtrasCrawler(BRTeamPageCrawler):
    """BR 球员主页面 5 类缺失数据爬虫。

    一次抓取主页面，解析全部 5 类并分别 upsert。CF/404 由 fetch_team_page 处理。
    """
    DOMAIN = "player_page_extras"
    TASK_TYPE = "br_player_page_extras"
    # 各表冲突键（供 _upsert_rows）
    CONFLICT = {
        "player_game_highs": ("player_id", "season_type", "season_end"),
        "player_playoffs_series": ("player_id", "season_text", "ps_round", "opp_abbr"),
        "player_similarity_scores": ("player_id", "scope", "comparable_name"),
        "player_all_star_games": ("player_id", "season_text"),
        "player_adjusted_shooting": ("player_id", "season_type", "season_end"),
        "player_page_overview": ("player_id",),
    }

    def build_url(self, slug: str) -> str:
        letter = (slug[0].lower() if slug else "a")
        return BR_MAIN_URL.format(letter=letter, slug=slug)

    # ── 枚举宇宙（与 shooting 同构）──
    def enumerate_players(self, conn) -> List[str]:
        cur = conn.cursor()
        cur.execute(
            "SELECT br_player_id FROM player_gamelog WHERE br_player_id IS NOT NULL "
            "UNION SELECT player_id FROM dim_players WHERE player_id IS NOT NULL"
        )
        rows = [r[0] for r in cur.fetchall() if r[0]]
        cur.close()
        seen, out = set(), []
        for s in rows:
            if s not in seen:
                seen.add(s)
                out.append(s)
        return out

    def _player_done(self, conn, slug: str) -> bool:
        """判定整页已处理（「是否已尝试」语义，2026-08-01 修复）。

        旧逻辑只查 player_game_highs 是否有行 → 无 Game Highs 表的新秀
        （如 Caleb Wilson / wilsoca01）永远判未完成、每轮重抓（曾单日被抓 124 次）。
        现改为三态任一即视为完成：
          1) dim_players.player_page_extras_scraped_at 非空（成功落库标记）
          2) player_page_extras_404 已隔离（确认 404）
          3) crawl_failures 已登记该 slug（瞬态重试耗尽）
        与 bio_ext 的 resume 语义统一。
        """
        cur = conn.cursor()
        try:
            cur.execute(
                "SELECT 1 FROM dim_players WHERE player_id=%s "
                "AND player_page_extras_scraped_at IS NOT NULL LIMIT 1", (slug,))
            if cur.fetchone() is not None:
                return True
            cur.execute(
                "SELECT 1 FROM player_page_extras_404 WHERE slug=%s LIMIT 1", (slug,))
            if cur.fetchone() is not None:
                return True
            cur.execute(
                "SELECT 1 FROM crawl_failures WHERE task_type='br_player_page_extras' "
                "AND game_id=%s LIMIT 1", (f"player_page_extras|{slug}|all",))
            return cur.fetchone() is not None
        finally:
            cur.close()

    def _quarantine_slug(self, conn, slug: str) -> None:
        if conn is None:
            return
        cur = conn.cursor()
        try:
            cur.execute(
                "INSERT INTO player_page_extras_404 (slug, note) VALUES (%s, %s) "
                "ON CONFLICT (slug) DO NOTHING", (slug, "http_404"))
            conn.commit()
        finally:
            cur.close()

    def _mark_scraped(self, conn, slug: str) -> None:
        """成功解析落库后标记整页已尝试（幂等；slug 不在 dim_players 时静默跳过）。

        写入 player_page_extras_scraped_at，作为 resume 的「已完成」判据。
        即便该页解析出 0 行（如新秀无 Game Highs 表），只要页有效即标记，
        避免每轮重抓（修复 wilsoca01 类死循环）。
        """
        if conn is None:
            return
        cur = conn.cursor()
        try:
            cur.execute(
                "UPDATE dim_players SET player_page_extras_scraped_at = now() "
                "WHERE player_id=%s", (slug,))
            conn.commit()
        except Exception as _e:  # noqa: BLE001
            try:
                conn.rollback()
            except Exception:
                pass
            logger.warning("_mark_scraped 写入失败（已忽略）: %s", _e)
        finally:
            cur.close()

    # ── 缓存（供 --rework）──
    def save_raw_html(self, slug: str, html: str) -> Path:
        d = Path(RAW_ARCHIVE) / slug
        d.mkdir(parents=True, exist_ok=True)
        p = d / "main.html"
        p.write_text(html, encoding="utf-8")
        return p

    # ── 单球员 ──
    def _crawl_player(self, conn, driver, slug: str) -> int:
        url = self.build_url(slug)
        html = self.fetch_team_page(driver, url)
        if not html:
            if self._last_fetch_404:
                self._quarantine_slug(conn, slug)
                logger.warning("  ⚠️ %s 命中 BR 404 → 隔离", slug)
                return 0
            self.register_failure(conn, f"player_page_extras|{slug}|all")
            return 0
        # 页面有效性门槛（2026-08-01 加固）：fetch_team_page 已筛 CF/404，
        # 此处再验一次，拦截「通过了 CF 标记但 DOM 未渲染完/截断」的脏页，
        # 避免把脏页静默标记完成、造成不可逆缺口。与 bio_ext 同构。
        if not is_valid_player_page(html):
            logger.warning(
                "    页面无效（残页/截断/CF 挑战，len=%d），记 failed 跳过（保留重试）",
                len(html))
            self.register_failure(conn, f"player_page_extras|{slug}|all")
            return 0
        self.save_raw_html(slug, html)
        n = self._consume(conn, slug, html)
        self._mark_scraped(conn, slug)   # 成功落库后标完成，杜绝死循环
        return n

    def _consume(self, conn, slug: str, html: str) -> int:
        recs = []
        recs += [dict(r, player_id=slug) for r in parse_game_highs(html, "Regular")]
        recs += [dict(r, player_id=slug) for r in parse_game_highs(html, "Playoffs")]
        recs += [dict(r, player_id=slug) for r in parse_playoffs_series(html)]
        recs += [dict(r, player_id=slug) for r in parse_similarity(html, "thru")]
        recs += [dict(r, player_id=slug) for r in parse_similarity(html, "career")]
        recs += [dict(r, player_id=slug) for r in parse_all_star(html)]
        recs += [dict(r, player_id=slug) for r in parse_adj_shooting(html, "Regular")]
        recs += [dict(r, player_id=slug) for r in parse_adj_shooting(html, "Playoffs")]

        # Overview 文本块（#info，每球员一行）
        ov = parse_overview(html)
        n = 0
        # 按目标表分组 upsert
        gh = [r for r in recs if "season_type" in r and r.get("season_text") and
              r.get("season_end") and "time_on_court" in r]
        ps = [r for r in recs if "ps_round" in r]
        sim = [r for r in recs if "comparable_name" in r]
        asg = [r for r in recs if "team_id" in r and "mp" in r]
        adj = [r for r in recs if "adj_fg_pct" in r]
        # 重新分桶更稳妥：用特征列区分
        n += self._upsert_rows(conn, "player_game_highs", gh, self.CONFLICT["player_game_highs"])
        n += self._upsert_rows(conn, "player_playoffs_series", ps, self.CONFLICT["player_playoffs_series"])
        n += self._upsert_rows(conn, "player_similarity_scores",
                               [{**r, "year_scores": _json(r["year_scores"])} for r in sim],
                               self.CONFLICT["player_similarity_scores"])
        n += self._upsert_rows(conn, "player_all_star_games", asg, self.CONFLICT["player_all_star_games"])
        n += self._upsert_rows(conn, "player_adjusted_shooting", adj, self.CONFLICT["player_adjusted_shooting"])
        if ov:
            ov_row = dict(ov, player_id=slug,
                          source_url=self.build_url(slug))
            n += self._upsert_rows(conn, "player_page_overview", [ov_row],
                                   self.CONFLICT["player_page_overview"])
        conn.commit()
        return n

    def rework_from_archive(self, slug: str) -> int:
        path = Path(RAW_ARCHIVE) / slug / "main.html"
        if not path.exists():
            logger.warning("[rework] 归档缺失: %s", path)
            return 0
        html = path.read_text(encoding="utf-8")
        conn = psycopg2.connect(**DB_CONFIG)
        try:
            n = self._consume(conn, slug, html)
        finally:
            conn.close()
        logger.info("[rework] %s 重放完成: %d 行", slug, n)
        return n

    # ── 主循环 ──
    def run_players(self, conn, slugs: Optional[List[str]] = None,
                    resume: bool = False, dry_run: bool = False,
                    limit: Optional[int] = None) -> int:
        if slugs is None:
            slugs = self.enumerate_players(conn)
        if limit is not None:
            slugs = slugs[: max(0, limit)]
        if not slugs:
            logger.info("枚举为空，无需抓取")
            return 0
        logger.info("待处理 slug 数: %d", len(slugs))
        total = 0
        driver = None
        try:
            if not dry_run:
                driver = self.get_driver()
                try:
                    ensure_cf_cleared(driver)
                except Exception as _e:
                    logger.warning("CF 握手前置检查异常（仍继续）: %s", _e)
            for i, slug in enumerate(slugs):
                if resume and self._player_done(conn, slug):
                    logger.info("  [resume] 跳过 %s（已落库）", slug)
                    continue
                if dry_run:
                    logger.info("  [dry-run] 计划抓取 %s", slug)
                    continue
                n = 0
                try:
                    n = self._crawl_player(conn, driver, slug)
                except Exception as exc:
                    logger.error("  抓取失败 %s: %s", slug, exc)
                    self.register_failure(conn, f"player_page_extras|{slug}|all")
                    conn.commit()
                    n = 0
                total += n
                logger.info("  %s: upsert %d 行", slug, n)
                if i < len(slugs) - 1:
                    self.rate_limit()
        finally:
            if driver is not None:
                try:
                    self.quit_driver()
                except Exception:
                    pass
        logger.info("完成：upsert %d 行（处理 %d slug）", total, len(slugs))
        return total


def _json(x):
    import json
    return json.dumps(x, ensure_ascii=False)


def main() -> None:
    p = argparse.ArgumentParser(description="BR 球员主页面 5 类缺失数据爬虫")
    p.add_argument("--slugs", type=str, default=None, help="逗号分隔 slug（小批量测试）")
    p.add_argument("--limit", type=int, default=None, help="最多处理 N 个 slug")
    p.add_argument("--resume", action="store_true", help="跳过已落库 slug")
    p.add_argument("--dry-run", action="store_true", help="只枚举+打印，不取浏览器/不写库")
    p.add_argument("--rework", type=str, default=None, help="从归档重解析某 slug")
    args = p.parse_args()

    crawler = PlayerPageExtrasCrawler()

    if args.rework:
        n = crawler.rework_from_archive(args.rework.strip())
        print(f"[rework] {args.rework}: upsert {n} 行")
        return

    conn = psycopg2.connect(**DB_CONFIG)
    try:
        slugs_list = ([s.strip() for s in args.slugs.split(",") if s.strip()]
                      if args.slugs else None)
        total = crawler.run_players(conn, slugs=slugs_list,
                                   resume=args.resume, dry_run=args.dry_run,
                                   limit=args.limit)
        print(f"完成：upsert {total} 行")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
