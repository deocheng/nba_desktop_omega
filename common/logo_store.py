"""Team logo 抽取 + 节流落盘（BR 队页 ``<img class="teamlogo">``）。

设计要点（遵循访问限制铁律 #0）：
- 抽取必须在**运行时**从抓取到的 HTML 做。BR 的 ``/req/<日期>/`` 前缀会随时间变化，
  绝不硬编码 URL（同 common/headshot_store.py 的约定）。
- 落盘文件名保留 BR 原始命名 ``{slug}-{year}.png``（已编码 队-年），如 ``HOU-2001.png``。
- **节流 + 幂等**：存在且非空则跳过；下载间有最小间隔，避免触发访问限制。
- 下载走 cdn.ssref.net（BR 静态资源 CDN，与需过 CF 的主站隔离），属低风险静态 GET。

典型用法（在队页爬虫 _crawl_one 内，已拿到 html 后调用一次）：
    src = extract_team_logo_src(html)
    if src:
        save_team_logo(slug, season, src)
"""
from __future__ import annotations

import os
import time
from pathlib import Path
from urllib.parse import urljoin

from bs4 import BeautifulSoup

LOGO_ROOT = Path(os.environ.get("NBA_LOGO_ROOT", "/Volumes/12T/NBA/logo"))
_THROTTLE_S = float(os.environ.get("LOGO_THROTTLE_S", "1.5"))
_last_fetch = 0.0


def extract_team_logo_src(html: str) -> "str | None":
    """从队页 HTML 抽取队标绝对 URL；抽不到返回 None。

    优先 ``<img class="teamlogo">``；兜底 ``div.media-item`` 内的 ``<img>``。
    相对 ``/req/...`` 路径补全到 cdn.ssref.net。
    """
    if not html:
        return None
    soup = BeautifulSoup(html, "html.parser")
    img = soup.find("img", class_="teamlogo")
    if img is None:
        media = soup.find("div", class_="media-item")
        if media is not None:
            img = media.find("img")
    if img is None:
        return None
    src = (img.get("src") or "").strip()
    if not src:
        return None
    if src.startswith("//"):
        src = "https:" + src
    elif src.startswith("/"):
        # BR 静态资源 CDN
        src = "https://cdn.ssref.net" + src
    return src


def _throttled() -> None:
    global _last_fetch
    wait = _THROTTLE_S - (time.time() - _last_fetch)
    if wait > 0:
        time.sleep(wait)
    _last_fetch = time.time()


def save_team_logo(slug: str, season: int, src: str,
                   root: "Path | str" = LOGO_ROOT) -> "str | None":
    """下载并落盘队标；返回本地路径或 None（跳过/失败）。幂等。"""
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    dst = root / f"{slug}-{season}.png"
    if dst.exists() and dst.stat().st_size > 500:
        return str(dst)  # 已存在，跳过
    _throttled()
    try:
        import requests
        r = requests.get(
            src,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0 Safari/537.36"
                )
            },
            timeout=20,
        )
        if r.status_code != 200 or len(r.content) < 200:
            return None
        dst.write_bytes(r.content)
        return str(dst)
    except Exception:  # noqa: BLE001
        return None
