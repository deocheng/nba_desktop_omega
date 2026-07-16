"""common/headshot_store.py — 球员头像（headshot）共享工具（增量功能，独立于 gamelog 爬虫）。

职责：
  * 计算本地落盘路径（HEADSHOT_ROOT 下，按 player_id 命名，避免按姓名建目录的歧义）
  * 从 BR 球员页 HTML 抽取头像 ``<img>`` 的 src（已实测选择器 ``#info .media-item img``）
  * 两级稳健下载：
      - Tier-1：requests / curl_cffi(impersonate=chrome124) + Referer + 桌面 UA + CF cookie 直连 GET
      - Tier-2：经 CDP 在「独立 page target」导航图片 URL，用 ``Network.getResponseBody`` 取字节（保底）
  * magic 字节校验，非图片（CF 挑战页 HTML）绝不落盘

本模块**不修改** ``common.browser`` 的任何公共行为；Tier-2 复用其裸 CDP 助手
（``_cdp_call_browser`` / ``_cdp_http_get``）开独立 target，绝不影响 gamelog 的标签页，
也绝不与 gamelog 争用 9222（双锁脚本保证两者不会并行）。

头像托管在 BR 自身域名（``www.basketball-reference.com``，**非** ``cdn.nba.com``），
因此复用同一 CF 会话即可取，与 ``ingest_br_pbp.py`` 提到的 cdn 403 无关。
"""
from __future__ import annotations

import base64
import logging
import os
import urllib.parse
from pathlib import Path

logger = logging.getLogger(__name__)

# ── 常量 ──────────────────────────────────────────────────────────────────
HEADSHOT_ROOT = Path("/Volumes/12T/NBA/球星/headshots")
SELECTOR = "#info .media-item img"                 # 已实测验证（Architect 实测 LeBron James 命中 1 个 <img>）
BR_HEADSHOT_HOST = "https://www.basketball-reference.com"
DESKTOP_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# 图片 magic 字节签名
_MAGIC_JPEG = b"\xff\xd8\xff"
_MAGIC_PNG = b"\x89PNG\r\n\x1a\n"
_WEBP_RIFF = b"RIFF"
_WEBP_WEBP = b"WEBP"


# ── 路径 / 落盘 ────────────────────────────────────────────────────────────
def ensure_root() -> None:
    """确保本地落盘根目录存在（等价于 mkdir -p）。"""
    HEADSHOT_ROOT.mkdir(parents=True, exist_ok=True)


def magic_ext(data: bytes) -> str | None:
    """根据前若干字节判定图片扩展名：jpg / png / webp；未知返回 None。

    用于落盘时按真实格式取扩展名（BR headshot 多为 jpg，少数历史球员可能是 png/webp）。
    """
    if not data:
        return None
    if data[:3] == _MAGIC_JPEG:
        return "jpg"
    if data[:8] == _MAGIC_PNG:
        return "png"
    if data[:4] == _WEBP_RIFF and data[8:12] == _WEBP_WEBP:
        return "webp"
    return None


def _is_valid_image(data: bytes) -> bool:
    """仅当 magic 命中 jpg/png/webp 才视为合法图片（防 CF 挑战页 HTML 误存）。"""
    return magic_ext(data) is not None


def headshot_path_for(player_id: str, src: str | None = None) -> Path:
    """返回头像落盘路径。

    默认 ``{player_id}.jpg``；若 ``src`` 末段为 png/webp，则取对应扩展名。
    注意：最终落盘时仍以 download_image / fetch 后的 magic 字节为准（见 download_image
    的扩展名修正），此处作为「预期路径」，用于 src 已明确扩展名的情形。
    """
    ext = "jpg"
    if src:
        suffix = urllib.parse.urlparse(src).path.rsplit(".", 1)[-1].lower()
        if suffix in ("jpg", "jpeg", "png", "webp"):
            ext = "jpg" if suffix == "jpeg" else suffix
    return HEADSHOT_ROOT / f"{player_id}.{ext}"


# ── HTML 抽取 ─────────────────────────────────────────────────────────────
def extract_headshot_src(html: str) -> str | None:
    """用 BeautifulSoup 抽取 SELECTOR 命中 ``<img>`` 的 src，并规整为绝对 URL。

    取不到（BR 球员页本身无头像，如早期/无 NBA 生涯球员）返回 None（= missing）。
    BR headshot src 形如 ``/req/202605210/images/headshots/{pid}.jpg``，带日期前缀、
    会随时间变化，因此**必须运行时抽取，绝不硬编码**。
    """
    from bs4 import BeautifulSoup

    if not html:
        return None
    soup = BeautifulSoup(html, "html.parser")
    img = soup.select_one(SELECTOR)
    if img is None:
        return None
    src = img.get("src")
    if not src:
        return None
    # src 通常为绝对 URL（含 /req/日期/ 前缀），此处统一规整为绝对 URL。
    return urllib.parse.urljoin(BR_HEADSHOT_HOST + "/", src)


# ── CF cookie 读取 ─────────────────────────────────────────────────────────
def _load_cf_cookies() -> dict | None:
    """从 ``BR_COOKIE_FILE`` 读取 CF cookie，返回 ``{name: value}`` 字典（供 requests/curl_cffi 使用）。

    文件格式：``[{"name","value"}]`` 或单 dict 或 ``{"n": {"name","value"}}``。
    读取失败 / 文件缺失返回 None（Tier-1 退化为无 cookie，再由 Tier-2 CDP 保底）。
    """
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


# ── Tier-1：直连 HTTP 下载 ──────────────────────────────────────────────────
def download_image(url: str, dest: Path, referer: str,
                   cookies: dict | None = None) -> "Path | None":
    """Tier-1：直连 GET 头像图片，magic 校验后落盘。

    成功返回最终落盘路径（已按 magic 字节修正扩展名），失败（403 / 超时 / 非图片 /
    命中 CF 挑战页 HTML）返回 None。**绝不在失败时落盘。**

    下载通道：优先 curl_cffi（TLS 指纹模拟 impersonate=chrome124，更抗 CF），
    否则退回普通 requests。均带 Referer + 桌面 UA + 从 BR_COOKIE_FILE 读取的 CF cookie。
    """
    import requests

    if cookies is None:
        cookies = _load_cf_cookies()

    headers = {
        "User-Agent": DESKTOP_UA,
        "Referer": referer or BR_HEADSHOT_HOST + "/",
        "Accept": "image/avif,image/webp,image/png,image/jpeg,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }

    try:
        try:
            from curl_cffi import requests as cffi_req
            resp = cffi_req.get(
                url, headers=headers, cookies=cookies or {},
                impersonate="chrome124", timeout=30,
            )
            status = resp.status_code
            content = resp.content
        except ImportError:
            resp = requests.get(
                url, headers=headers, cookies=cookies or {}, timeout=30,
            )
            status = resp.status_code
            content = resp.content
    except Exception as exc:  # noqa: BLE001 - 网络层失败 → 交给 Tier-2
        logger.debug("Tier-1 直连失败 (%s): %s", url, exc)
        return None

    if status != 200 or not content:
        logger.debug("Tier-1 非 200/空响应 (%s): status=%s", url, status)
        return None
    if not _is_valid_image(content):
        # 命中 CF 挑战页 HTML 等非图片字节 → 绝不落盘
        logger.debug("Tier-1 响应非图片（疑似 CF 挑战页），拒绝落盘 (%s)", url)
        return None

    # 按 magic 字节修正扩展名（极少数 png/webp 情形）
    ext = magic_ext(content) or "jpg"
    final = dest.parent / f"{dest.stem}.{ext}"
    ensure_root()
    final.write_bytes(content)
    # 若预期 dest 与修正后的 final 不同名，清理可能残留的空文件
    if final != dest and dest.exists() and dest.stat().st_size == 0:
        try:
            dest.unlink()
        except Exception:  # noqa: BLE001
            pass
    logger.debug("Tier-1 落盘成功: %s (%d bytes, %s)", final, len(content), ext)
    return final


# ── Tier-2：CDP 独立 target 取字节（保底） ──────────────────────────────────
def fetch_image_via_cdp(driver, url: str, timeout: int = 30) -> bytes | None:
    """Tier-2：经 CDP 在「独立 page target」导航图片 URL，用 ``Network.getResponseBody`` 取字节。

    ``driver`` 参数保留以对齐公共 API（实际内部复用 ``common.browser`` 的裸 CDP 助手开
    独立 target，绝不影响 gamelog 标签页 / 主爬虫的球员页 target）。复用用户浏览器已有
    CF 会话，图片与球员页同域同会话，100% 可靠。

    返回图片字节；失败 / 非图片（CF 挑战页）返回 None。
    """
    from common.browser import _cdp_call_browser, _cdp_http_get

    # 1) 在用户 Chrome 中开一个独立空白 target
    try:
        res = _cdp_call_browser("Target.createTarget",
                                {"url": "about:blank", "newWindow": False})
        tid = (res or {}).get("targetId")
    except Exception as exc:  # noqa: BLE001
        logger.warning("CDP createTarget 失败: %s", exc)
        return None
    if not tid:
        return None

    try:
        # 2) 解析该 target 的 page 级 websocket
        targets = _cdp_http_get("/json")
        entry = next((t for t in targets if t.get("id") == tid), None)
        if not entry or "webSocketDebuggerUrl" not in entry:
            return None
        target_ws = entry["webSocketDebuggerUrl"]

        import asyncio
        import json
        import websockets

        target_name = urllib.parse.urlparse(url).path.rstrip("/").split("/")[-1]

        async def _go() -> bytes | None:
            async with websockets.connect(
                target_ws, max_size=None, ping_interval=None, open_timeout=15
            ) as ws:
                _cid = {"v": 0}

                async def _cmd(method: str, params=None) -> int:
                    _cid["v"] += 1
                    await ws.send(json.dumps(
                        {"id": _cid["v"], "method": method, "params": params or {}}
                    ))
                    return _cid["v"]

                await _cmd("Network.enable")
                await _cmd("Page.enable")
                await _cmd("Page.navigate", {"url": url})

                url_map: dict = {}
                body_req_id: str | None = None
                loop = asyncio.get_running_loop()
                deadline = loop.time() + timeout
                while loop.time() < deadline:
                    try:
                        raw = await asyncio.wait_for(ws.recv(), timeout=5)
                    except asyncio.TimeoutError:
                        continue
                    msg = json.loads(raw)
                    # 命令 ack（带 id 且含 result/error）不是事件，忽略
                    if msg.get("id") is not None:
                        continue
                    method = msg.get("method")
                    params = msg.get("params", {})
                    if method == "Network.requestWillBeSent":
                        rid = params.get("requestId")
                        url_map[rid] = params.get("request", {}).get("url", "")
                    elif method == "Network.responseReceived":
                        rid = params.get("requestId")
                        url_map[rid] = params.get("response", {}).get("url", "")
                    elif method == "Network.loadingFinished":
                        rid = params.get("requestId")
                        u = url_map.get(rid, "")
                        if u and u.rstrip("/").split("/")[-1] == target_name:
                            body_req_id = rid
                            break
                    elif method == "Network.loadingFailed":
                        rid = params.get("requestId")
                        u = url_map.get(rid, "")
                        if u and u.rstrip("/").split("/")[-1] == target_name:
                            return None  # 目标图片加载失败

                if body_req_id is None:
                    return None

                # 3) 取 response body（base64 编码）
                get_id = await _cmd("Network.getResponseBody", {"requestId": body_req_id})
                while True:
                    raw = await asyncio.wait_for(ws.recv(), timeout=10)
                    msg = json.loads(raw)
                    if msg.get("id") == get_id:
                        if "error" in msg:
                            return None
                        res_body = msg.get("result", {})
                        body = res_body.get("body")
                        if body is None:
                            return None
                        is_b64 = res_body.get("base64", True)
                        data = base64.b64decode(body) if is_b64 else body.encode("utf-8", "replace")
                        return data

        data = asyncio.run(_go())
    finally:
        # 4) 关闭独立 target（绝不关用户浏览器）
        try:
            _cdp_call_browser("Target.closeTarget", {"targetId": tid})
        except Exception:  # noqa: BLE001
            pass

    if data and _is_valid_image(data):
        return data
    if data:
        logger.debug("Tier-2 取到字节但非图片（疑似 CF 挑战页），丢弃")
    return None
