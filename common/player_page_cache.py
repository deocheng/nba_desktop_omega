"""common/player_page_cache.py — BR 球员主页面 HTML 的 cache-first 文件系统缓存。

设计要点:
  * 缓存目录: <项目根>/raw_archive/br_players/{首字母}/{player_id}.html
  * cache-first: get_cached_html 命中即返回; 未命中才由调用方抓取(或
    fetch_player_page 线上抓) 并 save_html 落盘。
  * save_html 原子写(临时文件 + os.replace), 失败不污染缓存。
  * fetch_player_page: cache-first 直连主球员页(curl_cffi 抗 CF), 命中缓存跳过线上;
    供 nickname / bio_ext 爬虫(无浏览器通道)使用。gamelog 爬虫走浏览器,
    应通过 save_html 注入主球员页 HTML。
  * 主球员页(含绰号 FAQ / #bling 荣誉 / 亲属) 才是缓存目标;
    gamelog 赛季拆分页不含这些字段, 不能缓存错页面。
"""
from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# ── 共享 Cloudflare 防撞 + 自恢复熔断器 ──
# 本模块是 curl 通道（nickname / bio_ext 爬虫走它，无浏览器）。
# 挂一个模块级 CFBreaker：命中 CF 挑战页即计入熔断，连续达上限
# → 冷却（零线上请求）→ 冷却后自恢复；max_cooldowns=0 默认无限自恢复。
# 这样 nicknames / bio_ext 爬虫自动获得防撞，不用各写一遍。
from common.cf_breaker import CFBreaker  # noqa: E402

_BREAKER = CFBreaker()

# 缓存根(绝对路径): 经环境变量 NBA_ARCHIVE_ROOT 重定向到外置 12T 盘;
# 默认 /Volumes/12T/NBA/raw_archive → CACHE_ROOT = <NBA_ARCHIVE_ROOT>/br_players
_ARCHIVE_ROOT = os.environ.get("NBA_ARCHIVE_ROOT", "/Volumes/12T/NBA/raw_archive")
CACHE_ROOT = Path(_ARCHIVE_ROOT) / "br_players"

BR_HOST = "https://www.basketball-reference.com"
PLAYER_PAGE_URL = BR_HOST + "/players/{first}/{player_id}.html"
DESKTOP_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


def cache_path(player_id: str) -> Path:
    """返回某球员主页面 HTML 的缓存路径。"""
    if not player_id:
        return CACHE_ROOT / "_bad" / "empty.html"
    first = player_id[0].lower()
    return CACHE_ROOT / first / f"{player_id}.html"


def is_cached(player_id: str) -> bool:
    """该球员主页面是否已缓存(文件存在且 >0 字节)。"""
    p = cache_path(player_id)
    try:
        return p.exists() and p.stat().st_size > 0
    except OSError:
        return False


def get_cached_html(player_id: str) -> Optional[str]:
    """读取缓存的球员主页面 HTML; 未命中 / 空文件 -> None。"""
    if not is_cached(player_id):
        return None
    try:
        return cache_path(player_id).read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        logger.debug("get_cached_html(%s) 读失败: %s", player_id, exc)
        return None


def save_html(player_id: str, html: str) -> bool:
    """原子写: 先写临时文件再 os.replace 落最终路径。

    供「外部已抓到的 html(如浏览器 page_source)」直接落盘 —— 这是本任务的
    关键入口, 因为 gamelog 爬虫走浏览器通道、不调用 fetch_player_page。

    Returns:
        是否成功写入。
    """
    if not player_id or not html:
        return False
    dest = cache_path(player_id)
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        # 临时文件与最终文件同目录, 保证 os.replace 是原子改名(同文件系统)
        fd, tmp = tempfile.mkstemp(dir=str(dest.parent), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(html)
            os.replace(tmp, dest)
        finally:
            if os.path.exists(tmp):
                try:
                    os.remove(tmp)
                except OSError:
                    pass
    except OSError as exc:
        logger.warning("save_html(%s) 失败: %s", player_id, exc)
        return False
    return True


def _load_cf_cookies() -> Optional[dict]:
    """从 BR_COOKIE_FILE 读取 CF cookie, 返回 {name: value}(失败返回 None)。"""
    cookie_file = os.environ.get("BR_COOKIE_FILE")
    if not cookie_file or not os.path.exists(cookie_file):
        return None
    try:
        import json
        with open(cookie_file, "r", encoding="utf-8") as fh:
            raw = json.load(fh)
    except Exception as exc:  # noqa: BLE001 - 最佳努力
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


def fetch_player_page(player_id: str, timeout: int = 30,
                      cookies: Optional[dict] = None) -> Optional[str]:
    """cache-first 直连主球员页; 命中缓存直接返回, 否则 curl_cffi 抓取并落盘。

    返回 HTML 字符串或 None(命中 CF 挑战页 / 异常 / 非 200)。绝不抛异常。

    Args:
        player_id: BBRef 球员 id(如 ``antetgi01``)。
        timeout: 请求超时(秒)。
        cookies: 显式传入的 CF cookie 字典; 为 None 时尝试从 BR_COOKIE_FILE 读取。

    Returns:
        HTML 字符串或 None。
    """
    if not player_id:
        return None
    # cache-first: 命中本地缓存直接返回, 不碰 BR
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
    except Exception as exc:  # noqa: BLE001 - 网络层失败 -> 交回调方重试
        logger.debug("fetch_player_page(%s) 失败: %s", player_id, exc)
        return None

    if status != 200 or not text:
        logger.debug("fetch_player_page(%s) 非 200/空: status=%s", player_id, status)
        return None
    if "Just a moment" in text or "Checking your browser" in text:
        # 命中 CF 挑战页 -> 计入熔断器（内含退避/冷却 sleep）
        _BREAKER.on_breach()
        logger.debug("fetch_player_page(%s) 命中 CF 挑战页", player_id)
        return None
    # 落盘, 下次直接走缓存
    _BREAKER.on_success()
    save_html(player_id, text)
    return text


def player_page_url(player_id: str) -> str:
    """返回某球员的主球员页绝对 URL(供日志 / 复用)。"""
    if not player_id:
        return ""
    first = player_id[0].lower()
    return PLAYER_PAGE_URL.format(first=first, player_id=player_id)
