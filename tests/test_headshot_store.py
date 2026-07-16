"""common/headshot_store.py 离线单元测试（不联网、零干扰 12TB 盘）。

覆盖：
  * ``magic_ext``：jpg / png / webp / None / 空字节
  * ``_is_valid_image``：合法图片 → True；CF 挑战页 HTML → False
  * ``headshot_path_for``：默认 .jpg；png/webp 取真扩展名；根目录 = HEADSHOT_ROOT
  * ``extract_headshot_src``：``#info .media-item img`` → 绝对 URL；无 img → None
  * ``download_image``：Tier-1 成功落盘；CF-HTML / 403 / 异常 → None 且绝不写盘
  * ``fetch_image_via_cdp``：mock CDP 取字节成功；非图片字节 → None（Tier-2 magic 校验）

所有落盘均通过 monkeypatch 把 ``HEADSHOT_ROOT`` 指向 pytest 的 tmp_path，
绝不触碰真实 /Volumes/12T，绝不发生真实网络请求（curl_cffi / requests 均被 mock）。
"""
from __future__ import annotations

import base64
import json
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in __import__("sys").path:
    __import__("sys").path.insert(0, str(ROOT))

from common import headshot_store as store
from common.headshot_store import (
    _is_valid_image,
    download_image,
    extract_headshot_src,
    fetch_image_via_cdp,
    headshot_path_for,
    magic_ext,
)
from common import browser as browser_mod

# ── 图片字节样本 ──────────────────────────────────────────────────────────
JPG_BYTES = b"\xff\xd8\xff" + b"JFIF fake jpeg payload\x00\x01\x02"
PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"fake png payload"
WEBP_BYTES = b"RIFF" + b"\x00\x00\x00\x00" + b"WEBP" + b"fake webp"
UNKNOWN_BYTES = b"this is not an image at all"

# 真实 BR 球员页使用的 CF 挑战页结构（含 "Just a moment" / "请稍候"）
CF_HTML = (
    "<!DOCTYPE html><html lang=\"zh\"><head><title>Just a moment...</title></head>"
    "<body><div class=\"main-wrapper\"><h1>请稍候...</h1>"
    "<p>Checking your browser before accessing Basketball-Reference.</p></div>"
    "</body></html>"
).encode("utf-8")

REAL_ROOT = Path("/Volumes/12T/NBA/球星/headshots")

PLAYER_ID = "jamesle01"
IMG_URL = "https://www.basketball-reference.com/req/202605210/images/headshots/jamesle01.jpg"
IMG_URL_REL = "/req/202605210/images/headshots/jamesle01.jpg"

# 仿真实 BR 球员页：#info 内嵌 .media-item > img
PLAYER_HTML_WITH_IMG = f"""<!DOCTYPE html>
<html><head><title>LeBron James | Basketball-Reference.com</title></head>
<body>
<div id="info" class="players">
  <div class="media-item">
    <img src="{IMG_URL}" alt="Photo of LeBron James" width="220" height="220">
  </div>
  <div id="meta"><p>LeBron James</p></div>
</div>
</body></html>"""

PLAYER_HTML_REL = PLAYER_HTML_WITH_IMG.replace(IMG_URL, IMG_URL_REL)

PLAYER_HTML_NO_IMG = """<html><body>
<div id="info"><div class="media-item"><!-- no img here --></div></div>
</body></html>"""

PLAYER_HTML_IMG_OUTSIDE_INFO = """<html><body>
<div id="other"><div class="media-item">
  <img src="https://x/y.jpg" alt="should not match">
</div></div>
</body></html>"""


# ── magic_ext / _is_valid_image ───────────────────────────────────────────
@pytest.mark.parametrize("data,expected", [
    (JPG_BYTES, "jpg"),
    (PNG_BYTES, "png"),
    (WEBP_BYTES, "webp"),
    (UNKNOWN_BYTES, None),
    (b"", None),
])
def test_magic_ext(data, expected):
    assert magic_ext(data) == expected


def test_is_valid_image_true_for_jpg():
    assert _is_valid_image(JPG_BYTES) is True


def test_is_valid_image_false_for_cf_challenge_html():
    assert _is_valid_image(CF_HTML) is False


# ── headshot_path_for ─────────────────────────────────────────────────────
def test_real_root_constant_matches_spec():
    """落盘根目录必须是 /Volumes/12T/NBA/球星/headshots（不与现有按姓名目录冲突）。"""
    assert str(store.HEADSHOT_ROOT) == str(REAL_ROOT)


def test_headshot_path_for_default_jpg_and_root():
    """默认扩展名 .jpg，且路径落在 HEADSHOT_ROOT 下。"""
    p = headshot_path_for(PLAYER_ID)
    assert p.name == f"{PLAYER_ID}.jpg"
    assert p.parent == store.HEADSHOT_ROOT


@pytest.mark.parametrize("src,ext", [
    ("https://www.basketball-reference.com/x/y.png", "png"),
    ("https://www.basketball-reference.com/x/y.webp", "webp"),
    ("https://www.basketball-reference.com/x/y.jpeg", "jpg"),  # jpeg→jpg
    ("https://www.basketball-reference.com/x/y.jpg", "jpg"),
])
def test_headshot_path_for_real_ext(src, ext):
    """png/webp 取真扩展名；jpeg 归并为 jpg。"""
    p = headshot_path_for(PLAYER_ID, src)
    assert p.name == f"{PLAYER_ID}.{ext}"


# ── extract_headshot_src ───────────────────────────────────────────────────
def test_extract_headshot_src_absolute_url():
    assert extract_headshot_src(PLAYER_HTML_WITH_IMG) == IMG_URL


def test_extract_headshot_src_relative_url_resolved():
    """src 为相对路径时经 urljoin 规整为绝对 URL（/req/日期/ 前缀不硬编码）。"""
    assert extract_headshot_src(PLAYER_HTML_REL) == IMG_URL


def test_extract_headshot_src_missing_returns_none():
    assert extract_headshot_src(PLAYER_HTML_NO_IMG) is None


def test_extract_headshot_src_img_outside_info_returns_none():
    """选择器 #info .media-item img 必须命中 #info 内的 img，否则缺失即 None。"""
    assert extract_headshot_src(PLAYER_HTML_IMG_OUTSIDE_INFO) is None


def test_extract_headshot_src_empty_html_returns_none():
    assert extract_headshot_src("") is None


# ── download_image (Tier-1) ───────────────────────────────────────────────
@pytest.fixture
def patch_root(tmp_path, monkeypatch):
    """把 HEADSHOT_ROOT 指向临时目录，避免触碰 12TB 盘。"""
    monkeypatch.setattr(store, "HEADSHOT_ROOT", tmp_path)
    return tmp_path


def _fake_cffi_get(content: bytes, status: int = 200):
    """返回一个可被 curl_cffi.requests.get 调用的假函数。

    注意：不能用 ``class _Resp: content = content`` —— Python 3.10+ 的类体
    看不到外层函数闭包的 ``content``，会抛 NameError。用 SimpleNamespace 规避。
    """
    def _get(url, **kwargs):
        return types.SimpleNamespace(status_code=status, content=content)
    return _get


def test_download_image_tier1_success_writes_file(patch_root, monkeypatch):
    """Tier-1 返回合法图片字节 → 落盘并返回路径（按 magic 修正扩展名）。"""
    import curl_cffi.requests as cffi_requests
    monkeypatch.setattr(cffi_requests, "get", _fake_cffi_get(JPG_BYTES, 200))

    dest = store.HEADSHOT_ROOT / f"{PLAYER_ID}.jpg"
    out = download_image(IMG_URL, dest, referer="https://www.basketball-reference.com/",
                         cookies={})

    assert out is not None
    assert out.exists() and out.stat().st_size == len(JPG_BYTES)
    assert out.read_bytes() == JPG_BYTES
    assert out.name == f"{PLAYER_ID}.jpg"


def test_download_image_tier1_cf_html_never_written(patch_root, monkeypatch):
    """Tier-1 返回 CF 挑战页 HTML（非图片）→ 返回 None 且绝不落盘。"""
    import curl_cffi.requests as cffi_requests
    monkeypatch.setattr(cffi_requests, "get", _fake_cffi_get(CF_HTML, 200))

    dest = store.HEADSHOT_ROOT / f"{PLAYER_ID}.jpg"
    out = download_image(IMG_URL, dest, referer="https://www.basketball-reference.com/",
                         cookies={})

    assert out is None
    # 关键断言：没有任何文件被当作图片写盘
    assert not dest.exists()
    assert not (store.HEADSHOT_ROOT / f"{PLAYER_ID}.jpg").exists()
    assert not list(store.HEADSHOT_ROOT.glob(f"{PLAYER_ID}.*"))


def test_download_image_tier1_403_returns_none(patch_root, monkeypatch):
    """Tier-1 返回 403 → 返回 None 且不写盘。"""
    import curl_cffi.requests as cffi_requests
    monkeypatch.setattr(cffi_requests, "get", _fake_cffi_get(JPG_BYTES, 403))

    dest = store.HEADSHOT_ROOT / f"{PLAYER_ID}.jpg"
    out = download_image(IMG_URL, dest, referer="https://www.basketball-reference.com/",
                         cookies={})
    assert out is None
    assert not (store.HEADSHOT_ROOT / f"{PLAYER_ID}.jpg").exists()


def test_download_image_tier1_network_error_returns_none(patch_root, monkeypatch):
    """Tier-1 网络异常 → 返回 None（交由上层回退 Tier-2）。"""
    import curl_cffi.requests as cffi_requests
    def _boom(url, **kwargs):
        raise ConnectionError("simulated network failure")
    monkeypatch.setattr(cffi_requests, "get", _boom)

    dest = store.HEADSHOT_ROOT / f"{PLAYER_ID}.jpg"
    out = download_image(IMG_URL, dest, referer="https://www.basketball-reference.com/",
                         cookies={})
    assert out is None


def test_download_image_png_ext_from_magic(patch_root, monkeypatch):
    """PNG 字节落盘时按 magic 修正为 .png（即使 dest 名为 .jpg）。"""
    import curl_cffi.requests as cffi_requests
    monkeypatch.setattr(cffi_requests, "get", _fake_cffi_get(PNG_BYTES, 200))

    dest = store.HEADSHOT_ROOT / f"{PLAYER_ID}.jpg"
    out = download_image(IMG_URL, dest, referer="https://www.basketball-reference.com/",
                         cookies={})
    assert out is not None
    assert out.name == f"{PLAYER_ID}.png"
    assert out.read_bytes() == PNG_BYTES


# ── fetch_image_via_cdp (Tier-2，mock CDP) ────────────────────────────────
class _FakeWS:
    """极简 CDP WebSocket 替身：按序列返回预设消息。"""
    def __init__(self, messages):
        self._msgs = list(messages)
        self.sent = 0

    async def send(self, msg):
        self.sent += 1

    async def recv(self):
        if not self._msgs:
            # 兜底：返回一个不匹配的 loadingFailed，避免无限等待
            return json.dumps({"method": "Network.loadingFailed",
                               "params": {"requestId": "ZZZ"}})
        return self._msgs.pop(0)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


def _build_cdp_messages(url: str, body_bytes: bytes):
    """构造 CDP 事件序列：requestWillBeSent → loadingFinished → getResponseBody 结果。"""
    b64 = base64.b64encode(body_bytes).decode()
    return [
        json.dumps({"method": "Network.requestWillBeSent",
                    "params": {"requestId": "R1", "request": {"url": url}}}),
        json.dumps({"method": "Network.loadingFinished",
                    "params": {"requestId": "R1"}}),
        json.dumps({"id": 4, "result": {"body": b64, "base64": True}}),
    ]


@pytest.fixture
def mock_cdp(monkeypatch):
    """mock common.browser 的 CDP 助手与 websockets.connect。"""
    monkeypatch.setattr(browser_mod, "_cdp_call_browser",
                        lambda method, params=None: {"targetId": "T1"})
    monkeypatch.setattr(browser_mod, "_cdp_http_get",
                        lambda path: [{"id": "T1", "webSocketDebuggerUrl": "ws://fake"}])

    import websockets
    def _fake_connect(target_ws, **kwargs):
        return _FakeWS(_build_cdp_messages(IMG_URL, JPG_BYTES))
    monkeypatch.setattr(websockets, "connect", _fake_connect)


def test_fetch_image_via_cdp_returns_bytes(mock_cdp):
    """Tier-2 CDP 取回合法图片字节 → 返回字节。"""
    data = fetch_image_via_cdp(None, IMG_URL)
    assert data == JPG_BYTES


def test_fetch_image_via_cdp_rejects_non_image(mock_cdp, monkeypatch):
    """Tier-2 取回 CF 挑战页字节 → magic 校验拦截返回 None。"""
    import websockets
    def _fake_connect_cf(target_ws, **kwargs):
        return _FakeWS(_build_cdp_messages(IMG_URL, CF_HTML))
    monkeypatch.setattr(websockets, "connect", _fake_connect_cf)

    data = fetch_image_via_cdp(None, IMG_URL)
    assert data is None
