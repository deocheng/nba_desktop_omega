"""common/player_nickname.py — 球员本人「绰号(nickname)」抽取与抓取工具。

增量维度（详见 sql/006_add_player_nickname.sql）。独立模块，零耦合于 gamelog /
headshots 爬虫，可单独单测（见 tests/test_player_nickname.py）。

数据源: https://www.basketball-reference.com/players/{first}/{player_id}.html

绰号真实位置（**已实测确认**）:
  * 页面底部 FAQ: `<h3>What are X's nicknames?</h3>`
    后跟 `<p>{逗号分隔绰号列表} are nicknames for X.</p>`
    —— 这是现代/历史球员页**唯一普遍存在**的绰号来源。
  * `<span class="nickname">TEXT</span>`（#info 内）在实测样本中**未出现**，
    但为防御性兼容仍作为「主选择器」优先尝试（若某球员页有则直接用，最干净）。

设计要点:
  * ``extract_nickname(html)`` 为纯函数、离线可测、零网络依赖：
      - Tier-1: ``<span class="nickname">`` → 返回该文本（单一权威绰号）。
      - Tier-2: FAQ ``<p>`` → 解析出逗号分隔列表，规整后逗号连接返回。
      - 无绰号（"There are no nicknames for X."）→ 返回 None。
  * ``fetch_player_page(player_id)`` 用 requests / curl_cffi(impersonate) 直连 GET，
    **不触碰 9222 Chrome**（零干扰铁律），带桌面 UA + Referer + 可选 CF cookie。
  * 落库由 external_crawler/crawler/crawl_br_nicknames.py 负责（UPDATE dim_players.nickname）。
"""
from __future__ import annotations

import logging
import os
import re
import urllib.parse
from typing import List, Optional

logger = logging.getLogger(__name__)

# cache-first: 复用 player_page_cache 的本地文件系统缓存(主球员页 HTML)。
# 命中即返回, 未命中走下方 curl_cffi 抓取并落盘; bio_ext 爬虫经本模块
# fetch_player_page 间接获得 cache-first 行为, 不再每轮撞 BR 403。
from common.player_page_cache import get_cached_html, save_html  # noqa: E402

# ── 常量 ──────────────────────────────────────────────────────────────────
BR_HOST = "https://www.basketball-reference.com"
PLAYER_PAGE_URL = BR_HOST + "/players/{first}/{player_id}.html"
DESKTOP_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# Tier-1：#info 内的 <span class="nickname">（防御性，实测样本中未出现）
_NICKNAME_SPAN_RE = re.compile(
    r'<span[^>]+class="nickname"[^>]*>(.*?)</span>', re.IGNORECASE | re.DOTALL
)

# Tier-2：FAQ 段落。先定位 <h3>What are ... nicknames?</h3>，再取其后的 <p>。
_NICKNAME_FAQ_H3_RE = re.compile(
    r"What are .*? nicknames\?", re.IGNORECASE
)
# FAQ 文本形如:
#   "{list} are nicknames for {name}."   （多名绰号，复数）
#   "Reef is a nickname for {name}."      （单名绰号，单数 —— 见 QA 回归 abrdu.../ablefo01 等）
# 两者都要切：取 " ... for " 之前的列表部分。
_NICKNAME_FAQ_SPLIT_RE = re.compile(
    r"\s+(?:is a nickname for|are nicknames for)\s+", re.IGNORECASE
)
_NO_NICKNAME_RE = re.compile(
    r"There (?:are|is) no nicknames? for", re.IGNORECASE
)


# ── 纯函数：抽取 ───────────────────────────────────────────────────────────
def _clean_token(token: str) -> str:
    """清理单个绰号 token：去首尾空白、折叠内部多空格、去尾部句点。"""
    t = re.sub(r"\s+", " ", token).strip()
    t = t.strip(".").strip()
    return t


def extract_nickname(html: Optional[str]) -> Optional[str]:
    """从 BR 球员页 HTML 抽取球员本人绰号。

    返回规整后的绰号字符串；多名时以 ``, `` 连接（如 ``King James, LBJ, Chosen One``）。
    取不到（页面无绰号 / 非法 HTML / CF 挑战页）返回 None。

    Args:
        html: BR 球员页完整 HTML 字符串；空值 / None → None（绝不抛异常）。

    Returns:
        绰号字符串或 None。
    """
    if not html:
        return None

    # ── Tier-1: <span class="nickname">（最干净，单一权威绰号）──
    m = _NICKNAME_SPAN_RE.search(html)
    if m:
        text = _clean_token(m.group(1))
        if text:
            return text

    # ── Tier-2: FAQ 段落 ──
    # 定位 <h3>...nicknames?</h3> 之后紧邻的 <p>...</p>
    h3_match = _NICKNAME_FAQ_H3_RE.search(html)
    if not h3_match:
        return None

    # 从 h3 之后截取一段 HTML，找第一个 <p> 内容
    rest = html[h3_match.end():]
    p_match = re.search(r"<p[^>]*>(.*?)</p>", rest, re.IGNORECASE | re.DOTALL)
    if not p_match:
        return None

    # 去标签，仅留文本
    para_text = re.sub(r"<[^>]+>", "", p_match.group(1))
    para_text = re.sub(r"\s+", " ", para_text).strip()

    if not para_text or _NO_NICKNAME_RE.search(para_text):
        return None

    # 切掉结尾的 " are nicknames for X."，保留前面的列表
    list_part = _NICKNAME_FAQ_SPLIT_RE.split(para_text, maxsplit=1)[0]
    list_part = list_part.strip()
    if not list_part:
        return None

    # 逗号分隔 → 规整 → 去重（保持顺序）→ 连接
    tokens: List[str] = [
        _clean_token(tok) for tok in list_part.split(",")
    ]
    tokens = [t for t in tokens if t]
    if not tokens:
        return None

    seen = set()
    deduped: List[str] = []
    for t in tokens:
        low = t.lower()
        if low in seen:
            continue
        seen.add(low)
        deduped.append(t)

    return ", ".join(deduped)


# ── CF cookie 读取（可选，供 fetch 使用）────────────────────────────────────
def _load_cf_cookies() -> Optional[dict]:
    """从 ``BR_COOKIE_FILE`` 读取 CF cookie，返回 ``{name: value}``（失败返回 None）。"""
    cookie_file = os.environ.get("BR_COOKIE_FILE")
    if not cookie_file or not os.path.exists(cookie_file):
        return None
    try:
        import json
        with open(cookie_file, "r", encoding="utf-8") as fh:
            raw = json.load(fh)
    except Exception as exc:  # noqa: BLE001 - best-effort
        logger.warning("读 BR_COOKIE_FILE 失败: %s", exc)
        return None
    cookies: dict = {}
    items = raw if isinstance(raw, list) else [raw]
    for c in items:
        if not isinstance(c, dict):
            continue
        name = c.get("name") or c.get("Name")
        value = c.get("value")
        if value is None:
            value = c.get("Value") or c.get("content")
        if name and value is not None:
            cookies[name] = value
    return cookies or None


# ── HTTP 抓取（直连，不碰 9222 Chrome）─────────────────────────────────────
def fetch_player_page(player_id: str, timeout: int = 30,
                      cookies: Optional[dict] = None) -> Optional[str]:
    """直连 GET BR 球员页 HTML（用于后端补抽 nickname）。

    优先 curl_cffi（TLS 指纹 impersonate=chrome124，更抗 CF），
    否则退回普通 requests。均带桌面 UA + Referer + 可选 CF cookie。

    命中 CF 挑战页（"Just a moment" / "Checking your browser"）或任何异常 → 返回 None，
    **绝不抛出**，由调用方决定重试 / 跳过。

    Args:
        player_id: BBRef 球员 id（如 ``antetgi01``）。
        timeout: 请求超时（秒）。
        cookies: 显式传入的 CF cookie 字典；为 None 时尝试从 BR_COOKIE_FILE 读取。

    Returns:
        HTML 字符串或 None。
    """
    if not player_id:
        return None
    # cache-first: 命中本地缓存直接返回, 不碰 BR(避免每轮撞 403)
    cached = get_cached_html(player_id)
    if cached is not None:
        return cached
    first = player_id[0].lower()
    url = PLAYER_PAGE_URL.format(first=first, player_id=player_id)
    if cookies is None:
        cookies = _load_cf_cookies()

    headers = {
        "User-Agent": DESKTOP_UA,
        "Referer": BR_HOST + "/",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }

    try:
        try:
            from curl_cffi import requests as cffi_req
            resp = cffi_req.get(
                url, headers=headers, cookies=cookies or {},
                impersonate="chrome124", timeout=timeout,
            )
            status, text = resp.status_code, resp.text
        except ImportError:
            import requests
            resp = requests.get(
                url, headers=headers, cookies=cookies or {}, timeout=timeout,
            )
            status, text = resp.status_code, resp.text
    except Exception as exc:  # noqa: BLE001 - 网络层失败 → 交回调方重试
        logger.debug("fetch_player_page(%s) 失败: %s", player_id, exc)
        return None

    if status != 200 or not text:
        logger.debug("fetch_player_page(%s) 非 200/空: status=%s", player_id, status)
        return None
    if "Just a moment" in text or "Checking your browser" in text:
        # 命中 CF 挑战页 → 视为失败
        logger.debug("fetch_player_page(%s) 命中 CF 挑战页", player_id)
        return None
    # 落盘, 下次直接走缓存
    save_html(player_id, text)
    return text


def player_page_url(player_id: str) -> str:
    """返回某球员的 BR 球员页绝对 URL（供日志 / 复用）。"""
    if not player_id:
        return ""
    first = player_id[0].lower()
    return PLAYER_PAGE_URL.format(first=first, player_id=player_id)
