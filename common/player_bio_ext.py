"""common/player_bio_ext.py — 球员主数据维度增量(bio_ext)抽取与落库。

增量维度（详见 sql/007_add_player_bio_ext.sql / docs/ARCH_player_bio_ext.md）。
独立模块，零耦合于 gamelog / headshots / pbp 爬虫，可单独单测
（见 tests/test_player_bio_ext.py）。

数据源: https://www.basketball-reference.com/players/{first}/{player_id}.html

**选择器已实测确认（见 tests/fixtures/ 三个真实快照）**:
  * Relatives / ABA Debut / Died / Hall of Fame / Career Length：全部位于
    ``#info > #meta`` 内的 `<p>` 文本行（注意 ``Relatives :`` 冒号前有空格；
    ``ABA Debut:`` 与 ``NBA Debut:`` 共处同一 `<p>`）。
  * Honors 块：``#info > #bling > ul > li``（每个 <li> 即一条荣誉；
    部分球员无 #bling → 返回空列表）。
  * Jersey 号码：``#info > .uni_holder`` 内的 SVG ``<text>``（数字 token，
    按球队/赛季重复，取去重集合）。

设计要点:
  * ``PlayerBioExtExtractor`` 的 ``extract_*`` 为纯函数、离线可测、零网络依赖。
  * ``extract_all(html)`` 一次性跑完所有抽取，返回可直接交给 upsert 的 dict。
  * ``fetch_player_page`` 复用 ``common.player_nickname``（curl_cffi 抗 CF，
    失败返回 None，不碰 9222 Chrome）。
  * ``upsert_player_bio_ext(conn, pid, data)``：同一 player_id 事务内
    UPDATE dim_players + DELETE/INSERT player_career_honors，避免表与镜像漂移。
"""
from __future__ import annotations

import logging
import re
from datetime import date, datetime
from typing import Dict, List, Optional

from bs4 import BeautifulSoup

from common.player_nickname import fetch_player_page, player_page_url

logger = logging.getLogger(__name__)

# ── 常量 ──────────────────────────────────────────────────────────────────
# honor_type 枚举（见 ARCH §4.1）。parse_honor_line 仅输出这些值 + 'other'。
VALID_HONOR_TYPES = frozenset({
    "hall_of_fame", "all_star", "nba_champ", "aba_champ", "all_nba", "all_aba",
    "all_defensive", "all_rookie", "mvp", "as_mvp", "aba_all_time_team",
    "nba_75_team", "mbwa_aba_poy", "other",
})

# 日期 "Month D, YYYY"（先归一化 \xa0 与多余空白）
_MONTH_DAY_YEAR_RE = re.compile(r"([A-Z][a-z]+)\s+(\d{1,2}),\s*(\d{4})")
_DATE_FMT = "%B %d, %Y"

# #meta <p> 行内抽取正则
_RELATIVES_RE = re.compile(r"^\s*Relatives\s*:\s*(.+?)\s*$", re.IGNORECASE)
_ABA_DEBUT_RE = re.compile(r"ABA Debut\s*:\s*([A-Z][a-z]+\s+\d{1,2},\s*\d{4})")
_DIED_RE = re.compile(r"Died\s*:\s*([A-Z][a-z]+\s+\d{1,2},\s*\d{4})")
_HOF_RE = re.compile(
    r"Hall of Fame\s*:\s*Inducted as\s+(\w+)\s+in\s+(\d{4})", re.IGNORECASE
)
_CAREER_LEN_RE = re.compile(r"Career Length\s*:\s*(\d+)", re.IGNORECASE)

# 荣誉行解析：前导 "Nx " 次数 + 任意 4 位年份
_HONOR_COUNT_RE = re.compile(r"^(\d+)\s*[xX]\s+")
# 单年份 "1983"；赛季区间 "1971-72" 取区间末年（NBA 赛季命名惯例）
_HONOR_YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")
_HONOR_RANGE_RE = re.compile(r"\b(19|20)(\d{2})-(\d{2})\b")


# ── 工具 ───────────────────────────────────────────────────────────────────
def _soup(html: Optional[str]) -> BeautifulSoup:
    """HTML → BeautifulSoup；空/非法返回空 soup（绝不抛异常）。"""
    if not html:
        return BeautifulSoup("", "html.parser")
    return BeautifulSoup(html, "html.parser")


def _normalize_ws(text: str) -> str:
    """折叠 \xa0 与多余空白为单个空格，去首尾。"""
    return re.sub(r"\s+", " ", text).strip()


def _parse_month_day_year(text: Optional[str]) -> Optional[date]:
    """从文本抽 "Month D, YYYY" 并解析为 date；失败返回 None。"""
    if not text:
        return None
    m = _MONTH_DAY_YEAR_RE.search(text)
    if not m:
        return None
    try:
        return datetime.strptime(m.group(0), _DATE_FMT).date()
    except ValueError:
        return None


def _meta_lines(soup: BeautifulSoup) -> List[str]:
    """返回 ``#info > #meta`` 内每个 ``<p>`` 的归一化文本行。"""
    info = soup.find(id="info")
    if not info:
        return []
    meta = info.find(id="meta")
    if not meta:
        return []
    lines: List[str] = []
    for p in meta.find_all("p"):
        txt = _normalize_ws(p.get_text(" ", strip=False))
        if txt:
            lines.append(txt)
    return lines


# ── 纯函数：抽取（内部 soup 版，供 extract_all 复用）─────────────────────────
def _extract_relatives(soup: BeautifulSoup) -> Optional[str]:
    for line in _meta_lines(soup):
        m = _RELATIVES_RE.match(line)
        if m:
            val = _normalize_ws(m.group(1))
            return val or None
    return None


def _extract_aba_debut(soup: BeautifulSoup) -> Optional[date]:
    for line in _meta_lines(soup):
        m = _ABA_DEBUT_RE.search(line)
        if m:
            return _parse_month_day_year(m.group(1))
    return None


def _extract_died(soup: BeautifulSoup) -> Optional[date]:
    for line in _meta_lines(soup):
        m = _DIED_RE.search(line)
        if m:
            return _parse_month_day_year(m.group(1))
    return None


def _extract_hof(soup: BeautifulSoup) -> (Optional[int], Optional[str]):
    """返回 (hof_inducted_year, hof_as)；无则 (None, None)。"""
    for line in _meta_lines(soup):
        m = _HOF_RE.search(line)
        if m:
            return int(m.group(2)), _normalize_ws(m.group(1))
    return None, None


def _extract_career_length(soup: BeautifulSoup) -> Optional[int]:
    for line in _meta_lines(soup):
        m = _CAREER_LEN_RE.search(line)
        if m:
            return int(m.group(1))
    return None


def _extract_jersey_numbers(soup: BeautifulSoup) -> Optional[List[str]]:
    """从 ``#info .uni_holder`` SVG <text> 抽数字 token 并去重（保序）。

    返回去重后的号码列表；无号码容器或空 → None。
    """
    info = soup.find(id="info")
    if not info:
        return None
    uh = info.find(class_="uni_holder")
    if not uh:
        return None
    seen: set = set()
    out: List[str] = []
    for t in uh.find_all("text"):
        token = _normalize_ws(t.get_text())
        if token and token.isdigit():
            if token not in seen:
                seen.add(token)
                out.append(token)
    return out or None


def _extract_honors(soup: BeautifulSoup, hof_year: Optional[int] = None) -> List[Dict]:
    """解析 ``#bling`` 内每条荣誉（无 #bling → 空列表）。"""
    honors: List[Dict] = []
    bling = soup.find(id="bling")
    if not bling:
        return honors
    for li in bling.find_all("li"):
        raw = _normalize_ws(li.get_text(" ", strip=True))
        if raw:
            honors.append(parse_honor_line(raw, hof_year=hof_year))
    return honors


# ── 公共纯函数（html 入参，离线可测）────────────────────────────────────────
def extract_relatives(html: Optional[str]) -> Optional[str]:
    """从 BR 球员页 HTML 抽取亲属文本（Relatives 行）。无 → None。"""
    return _extract_relatives(_soup(html))


def extract_aba_debut(html: Optional[str]) -> Optional[date]:
    """抽取 ABA 首秀日期（ABA Debut: 行）。无 ABA → None。"""
    return _extract_aba_debut(_soup(html))


def extract_died(html: Optional[str]) -> Optional[date]:
    """抽取离世日期（Died: 行，仅已故球员有）。在世/未知 → None。"""
    return _extract_died(_soup(html))


def extract_hof(html: Optional[str]) -> (Optional[int], Optional[str]):
    """抽取名人堂 (年份, 身份)。非名人堂 → (None, None)。"""
    return _extract_hof(_soup(html))


def extract_career_length(html: Optional[str]) -> Optional[int]:
    """抽取生涯长度（年，整数）。无 → None。"""
    return _extract_career_length(_soup(html))


def extract_jersey_numbers(html: Optional[str]) -> Optional[List[str]]:
    """抽取生涯球衣号码（去重数组）。无 → None。"""
    return _extract_jersey_numbers(_soup(html))


def extract_honors(html: Optional[str], hof_year: Optional[int] = None) -> List[Dict]:
    """抽取生涯荣誉列表（每条为 parse_honor_line 结果 dict）。无 → 空列表。"""
    return _extract_honors(_soup(html), hof_year=hof_year)


def parse_honor_line(raw: str, hof_year: Optional[int] = None) -> Dict:
    """将单条荣誉原始文本归一化为结构化 dict。

    Args:
        raw: 原始荣誉文本（如 "16x All Star" / "1983 NBA Champ" / "Hall of Fame"）。
        hof_year: 可选，名人堂入选年份；当本行被归类为 hall_of_fame 且无年份时填入。

    Returns:
        dict: {honor_raw, honor_type, honor_count, honor_year, honor_detail}
        honor_type ∈ VALID_HONOR_TYPES；无法识别归为 'other'。
    """
    text = _normalize_ws(raw)
    # 前导 "Nx " 次数
    count: Optional[int] = None
    m_count = _HONOR_COUNT_RE.match(text)
    if m_count:
        count = int(m_count.group(1))
    # 年份：赛季区间 "1971-72" 取末年（1972）；否则取首个 4 位年份
    year: Optional[int] = None
    m_range = _HONOR_RANGE_RE.search(text)
    if m_range:
        year = int(m_range.group(1) + m_range.group(3))  # 世纪 + 2 位末年
    else:
        m_year = _HONOR_YEAR_RE.search(text)
        if m_year:
            year = int(m_year.group(0))

    honor_type, detail = _classify_honor(text)

    # Hall of Fame 优先用传入的入选年份（bling 行本身无年份）
    if honor_type == "hall_of_fame" and hof_year is not None:
        year = hof_year

    return {
        "honor_raw": text,
        "honor_type": honor_type,
        "honor_count": count,
        "honor_year": year,
        "honor_detail": detail,
    }


def _classify_honor(text: str) -> (str, Optional[str]):
    """按优先级将荣誉文本归类为 honor_type，并附带 detail。"""
    t = text.lower()
    if re.search(r"hall of fame", t):
        # detail = 入选身份（若有 "as X"）；bling 行通常无，留 None
        m = re.search(r"as\s+(\w+)", t)
        return "hall_of_fame", (m.group(1) if m else None)
    if re.search(r"all[- ]star", t):
        return "all_star", None
    if re.search(r"aba champ", t):
        return "aba_champ", None
    if re.search(r"nba champ", t):
        return "nba_champ", None
    if re.search(r"all-nba", t):
        return "all_nba", None
    if re.search(r"all-aba", t):
        return "all_aba", None
    if re.search(r"all-defensive", t):
        return "all_defensive", None
    if re.search(r"all-rookie", t):
        return "all_rookie", None
    if re.search(r"as mvp|all[- ]star mvp", t):
        return "as_mvp", None
    if re.search(r"finals mvp", t):
        return "mvp", None
    if re.search(r"aba all-time team", t):
        return "aba_all_time_team", None
    if re.search(r"nba 75th|75th anniv", t):
        return "nba_75_team", "Team"
    if re.search(r"mbwa aba poy", t):
        return "mbwa_aba_poy", None
    if re.search(r"\bmvp\b", t):
        return "mvp", None
    if re.search(r"champ", t):
        return "other", None
    return "other", None


# ── 汇总抽取 ───────────────────────────────────────────────────────────────
class PlayerBioExtExtractor:
    """bio_ext 抽取器（纯函数集合 + extract_all 汇总）。"""

    extract_relatives = staticmethod(extract_relatives)
    extract_aba_debut = staticmethod(extract_aba_debut)
    extract_died = staticmethod(extract_died)
    extract_hof = staticmethod(extract_hof)
    extract_career_length = staticmethod(extract_career_length)
    extract_jersey_numbers = staticmethod(extract_jersey_numbers)
    extract_honors = staticmethod(extract_honors)
    parse_honor_line = staticmethod(parse_honor_line)

    @classmethod
    def extract_all(cls, html: Optional[str]) -> Dict:
        """一次性抽取全部 bio_ext 维度，返回可直接交给 upsert 的 dict。

        Returns dict 字段:
            aba_debut, died, hof_inducted_year, hof_as, is_hall_of_famer,
            career_length_years, relatives, jersey_numbers (list|None),
            career_honors_text (list|None), honors (list[dict])
        """
        soup = _soup(html)
        hof_year, hof_as = _extract_hof(soup)
        honors = _extract_honors(soup, hof_year=hof_year)

        # career_honors_text = 去重后的 honor_raw 列表（展示镜像）
        honor_raws: List[str] = []
        seen: set = set()
        for h in honors:
            r = h["honor_raw"]
            if r not in seen:
                seen.add(r)
                honor_raws.append(r)

        return {
            "aba_debut": _extract_aba_debut(soup),
            "died": _extract_died(soup),
            "hof_inducted_year": hof_year,
            "hof_as": hof_as,
            "is_hall_of_famer": hof_year is not None,
            "career_length_years": _extract_career_length(soup),
            "relatives": _extract_relatives(soup),
            "jersey_numbers": _extract_jersey_numbers(soup),
            "career_honors_text": honor_raws or None,
            "honors": honors,
        }


# ── 落库（与抽取解耦；crawler 调用；同一 player_id 事务内）──────────────────
def upsert_player_bio_ext(conn, player_id: str, data: Dict, source_url: Optional[str] = None) -> None:
    """将 bio_ext 抽取结果写入 PG：同一 player_id 事务内完成。

    包含：
      * UPDATE dim_players（全部新列 + bio_ext_scraped_at = now()）
      * DELETE + INSERT player_career_honors（荣誉归一化表）
    保表与 career_honors_text 镜像一致，避免漂移。

    Args:
        conn: psycopg2 连接（由 crawler 打开）。
        player_id: BBRef 球员 id。
        data: PlayerBioExtExtractor.extract_all 的返回值。
        source_url: 可选来源 URL（写入 player_career_honors）。

    注意：本函数内部提交（per-player 自治事务）；失败回滚并重抛。
    """
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE public.dim_players SET
                    aba_debut            = %(aba_debut)s,
                    died                 = %(died)s,
                    hof_inducted_year    = %(hof_inducted_year)s,
                    hof_as               = %(hof_as)s,
                    is_hall_of_famer     = %(is_hall_of_famer)s,
                    career_length_years  = %(career_length_years)s,
                    relatives            = %(relatives)s,
                    jersey_numbers       = %(jersey_numbers)s,
                    career_honors_text   = %(career_honors_text)s,
                    bio_ext_scraped_at   = now()
                WHERE player_id = %(player_id)s
                """,
                {
                    "aba_debut": data.get("aba_debut"),
                    "died": data.get("died"),
                    "hof_inducted_year": data.get("hof_inducted_year"),
                    "hof_as": data.get("hof_as"),
                    "is_hall_of_famer": data.get("is_hall_of_famer"),
                    "career_length_years": data.get("career_length_years"),
                    "relatives": data.get("relatives"),
                    "jersey_numbers": data.get("jersey_numbers"),
                    "career_honors_text": data.get("career_honors_text"),
                    "player_id": player_id,
                },
            )
            cur.execute(
                "DELETE FROM public.player_career_honors WHERE player_id = %s",
                (player_id,),
            )
            for h in data.get("honors", []) or []:
                cur.execute(
                    """
                    INSERT INTO public.player_career_honors
                        (player_id, honor_raw, honor_type, honor_count,
                         honor_year, honor_detail, source_url)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        player_id,
                        h.get("honor_raw"),
                        h.get("honor_type"),
                        h.get("honor_count"),
                        h.get("honor_year"),
                        h.get("honor_detail"),
                        source_url,
                    ),
                )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
