"""common/player_nickname.py 离线单元测试（不联网、零干扰 5433 PG / 9222 Chrome）。

覆盖:
  * ``extract_nickname``:
      - Tier-1 ``<span class="nickname">`` → 返回该文本（单一权威绰号）
      - Tier-2 FAQ ``<p>{list} are nicknames for X.</p>`` → 规整逗号连接
      - 无绰号（"There are no nicknames for X."）→ None
      - 空 / 非法 HTML → None
      - 多空格 / 尾部句点 / 重复项 → 规整去重
  * ``fetch_player_page``（mock 网络，绝不发生真实请求）:
      - curl_cffi 返回合法 HTML → 返回文本
      - 返回 CF 挑战页 HTML → None
      - 403 / 异常 → None

所有网络均被 monkeypatch mock；DB 完全不涉及。
"""
from __future__ import annotations

import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in __import__("sys").path:
    __import__("sys").path.insert(0, str(ROOT))

from common import player_nickname as nk


@pytest.fixture(autouse=True)
def _isolate_player_page_cache(monkeypatch, tmp_path):
    """所有 fetch/cache 测试隔离到临时目录, 不污染真实 raw_archive/br_players。"""
    import common.player_page_cache as ppc
    monkeypatch.setattr(ppc, "CACHE_ROOT", tmp_path / "br_players")


# ── 合成样本 HTML ──────────────────────────────────────────────────────────
PLAYER_ID = "antetgi01"

# Tier-1：#info 内 <span class="nickname">
HTML_SPAN = f"""<html><body>
<div id="info" class="players">
  <div id="meta">
    <h1><span>Giannis Antetokounmpo</span></h1>
    <span class="nickname">The Greek Freak</span>
  </div>
</div>
</body></html>"""

# Tier-2：FAQ 段落（多名，带多余空格 / 尾部句点）
HTML_FAQ = f"""<html><body>
<div id="info" class="players"><h1><span>LeBron James</span></h1></div>
<section>
  <h3>What are LeBron James' nicknames?</h3>
  <p>King James,   LBJ, Chosen One, Bron-Bron, The Little Emperor are nicknames for LeBron James.</p>
</section>
</body></html>"""

# 无绰号
HTML_NO_NICK = f"""<html><body>
<div id="info" class="players"><h1><span>Role Player</span></h1></div>
<section>
  <h3>What are Role Player's nicknames?</h3>
  <p>There are no nicknames for Role Player.</p>
</section>
</body></html>"""

# CF 挑战页
CF_HTML = (
    "<!DOCTYPE html><html lang=\"zh\"><head><title>Just a moment...</title></head>"
    "<body><div class=\"main-wrapper\"><h1>请稍候...</h1>"
    "<p>Checking your browser before accessing Basketball-Reference.</p></div>"
    "</body></html>"
)


# ── extract_nickname: 纯函数 ───────────────────────────────────────────────
def test_extract_from_span_returns_text():
    assert nk.extract_nickname(HTML_SPAN) == "The Greek Freak"


def test_extract_from_faq_normalizes_and_joins():
    # 逗号分隔、去多余空格、去尾部句点、连接
    assert nk.extract_nickname(HTML_FAQ) == "King James, LBJ, Chosen One, Bron-Bron, The Little Emperor"


def test_extract_no_nickname_returns_none():
    assert nk.extract_nickname(HTML_NO_NICK) is None


def test_extract_singular_nickname():
    """BR 单绰号球员用单数 'is a nickname for'（如 Shareef Abdur-Rahim → 'Reef'）。

    回归用例（QA 发现）：此前 _NICKNAME_FAQ_SPLIT_RE 只匹配复数
    'are nicknames for'，导致此类球员被存成整句垃圾。修复后只取绰号本身。
    """
    html = (
        "<html><body><h3>What are Shareef Abdur-Rahim's nicknames?</h3>"
        "<p>Reef is a nickname for Shareef Abdur-Rahim.</p></body></html>"
    )
    assert nk.extract_nickname(html) == "Reef"


def test_extract_empty_html_returns_none():
    assert nk.extract_nickname("") is None
    assert nk.extract_nickname(None) is None


def test_extract_plain_html_no_faq_returns_none():
    assert nk.extract_nickname("<html><body><p>hello</p></body></html>") is None


def test_extract_span_takes_precedence_over_faq():
    html = HTML_SPAN.replace(
        "</div>\n</body>",
        "</div>\n<section><h3>What are X's nicknames?</h3>"
        "<p>Foo, Bar are nicknames for X.</p></section>\n</body>",
    )
    # 即使 FAQ 也存在，Tier-1 span 优先
    assert nk.extract_nickname(html) == "The Greek Freak"


def test_extract_dedupes_and_strips():
    html = (
        "<html><body><h3>What are X's nicknames?</h3>"
        "<p>  The Beard , The Beard ,  El Chapo . are nicknames for X.</p>"
        "</body></html>"
    )
    assert nk.extract_nickname(html) == "The Beard, El Chapo"


# ── fetch_player_page: mock 网络 ───────────────────────────────────────────
def _fake_cffi_get(text: str, status: int = 200):
    def _get(url, **kwargs):
        return types.SimpleNamespace(status_code=status, text=text)
    return _get


def test_fetch_returns_html_on_success(monkeypatch):
    import curl_cffi.requests as cffi_requests
    body = HTML_FAQ
    monkeypatch.setattr(cffi_requests, "get", _fake_cffi_get(body, 200))
    assert nk.fetch_player_page(PLAYER_ID) == body


def test_fetch_returns_none_on_cf_challenge(monkeypatch):
    import curl_cffi.requests as cffi_requests
    monkeypatch.setattr(cffi_requests, "get", _fake_cffi_get(CF_HTML, 200))
    assert nk.fetch_player_page(PLAYER_ID) is None


def test_fetch_returns_none_on_403(monkeypatch):
    import curl_cffi.requests as cffi_requests
    monkeypatch.setattr(cffi_requests, "get", _fake_cffi_get("x", 403))
    assert nk.fetch_player_page(PLAYER_ID) is None


def test_fetch_returns_none_on_network_error(monkeypatch):
    import curl_cffi.requests as cffi_requests
    def _boom(url, **kwargs):
        raise ConnectionError("simulated network failure")
    monkeypatch.setattr(cffi_requests, "get", _boom)
    assert nk.fetch_player_page(PLAYER_ID) is None


def test_fetch_empty_player_id_returns_none(monkeypatch):
    import curl_cffi.requests as cffi_requests
    monkeypatch.setattr(cffi_requests, "get", _fake_cffi_get("x", 200))
    assert nk.fetch_player_page("") is None


def test_fetch_cache_first_no_refetch_on_hit(monkeypatch, tmp_path):
    """cache-first 路由: 首次未命中→走网络并落盘; 二次命中→直接返回缓存, 不重抓。

    这是「gamelog 爬行顺手铺缓存 → nickname/bio_ext 离线抽」链路的核心保证:
    同一球员第二次 fetch 绝不再撞 BR。
    """
    import common.player_page_cache as ppc
    import curl_cffi.requests as cffi_requests

    monkeypatch.setattr(ppc, "CACHE_ROOT", tmp_path / "br_players")
    network_hits = {"n": 0}

    def _counting_get(url, **kwargs):
        network_hits["n"] += 1
        return types.SimpleNamespace(status_code=200, text=HTML_FAQ)
    monkeypatch.setattr(cffi_requests, "get", _counting_get)

    # 首次: 未缓存 → 网络 + 落盘
    out1 = nk.fetch_player_page(PLAYER_ID)
    assert out1 == HTML_FAQ
    assert network_hits["n"] == 1
    assert ppc.is_cached(PLAYER_ID)

    # 二次: 命中缓存 → 不触发网络
    out2 = nk.fetch_player_page(PLAYER_ID)
    assert out2 == HTML_FAQ
    assert network_hits["n"] == 1  # 关键: 未再次请求 BR


def test_player_page_url_built_correctly():
    assert nk.player_page_url("antetgi01") == (
        "https://www.basketball-reference.com/players/a/antetgi01.html"
    )
