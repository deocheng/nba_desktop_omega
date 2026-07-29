"""common/player_page_cache.py 单元测试（不联网、零干扰 5433 PG / 9222 Chrome）。

覆盖:
  * cache miss → save_html → get_cached_html 命中（内容往返一致）
  * is_cached: 0 字节文件 / 不存在 → False
  * save_html 原子写:
      - 正常: 落盘成功且无 .tmp 残留
      - 改名失败(os.replace 抛错): 旧文件完好 + 无 .tmp 残留 + 返回 False
  * fetch_player_page（mock 网络, 绝不发生真实请求）:
      - 未命中且网络不可达 → None, 不抛, 不落盘
      - 200 → 返回文本并落盘, 二次调用走缓存不重抓

所有缓存 I/O 隔离到 tmp_path, 不污染真实 raw_archive/br_players。
"""
from __future__ import annotations

import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in __import__("sys").path:
    __import__("sys").path.insert(0, str(ROOT))

import common.player_page_cache as ppc


@pytest.fixture(autouse=True)
def _isolate_cache(monkeypatch, tmp_path):
    """所有缓存 I/O 隔离到临时目录。"""
    monkeypatch.setattr(ppc, "CACHE_ROOT", tmp_path / "br_players")


PID = "antetgi01"
SAMPLE_HTML = "<html><body><h1>Giannis</h1></body></html>"


# ── 命中 / 未命中 ──────────────────────────────────────────────────────────
def test_cache_miss_then_save_then_hit():
    assert ppc.is_cached(PID) is False
    assert ppc.get_cached_html(PID) is None

    assert ppc.save_html(PID, SAMPLE_HTML) is True
    assert ppc.is_cached(PID) is True

    got = ppc.get_cached_html(PID)
    assert got == SAMPLE_HTML
    # 路径严格按 {首字母}/{pid}.html
    assert ppc.cache_path(PID).name == f"{PID}.html"
    assert ppc.cache_path(PID).parent.name == PID[0].lower()


def test_is_cached_false_for_empty_and_missing(tmp_path):
    # 不存在
    assert ppc.is_cached("missing99") is False
    # 0 字节文件视为未命中
    p = ppc.cache_path("zerobyte")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("")
    assert p.exists()
    assert ppc.is_cached("zerobyte") is False
    assert ppc.get_cached_html("zerobyte") is None


# ── 原子写 ────────────────────────────────────────────────────────────────
def test_save_html_happy_path_no_tmp_leftover():
    assert ppc.save_html(PID, SAMPLE_HTML) is True
    dest = ppc.cache_path(PID)
    assert dest.read_text() == SAMPLE_HTML
    assert list(dest.parent.glob("*.tmp")) == []


def test_save_html_atomic_failure_keeps_old_and_no_tmp(monkeypatch):
    # 预置一个有效缓存文件
    assert ppc.save_html(PID, "<html>old</html>") is True
    old_path = ppc.cache_path(PID)
    old_content = old_path.read_text()

    # 让 os.replace 抛错(模拟跨文件系统改名失败 / 磁盘满)
    def _boom_replace(src, dst):
        raise OSError("simulated rename failure")
    monkeypatch.setattr(ppc.os, "replace", _boom_replace)

    # 新内容落盘应失败, 绝不污染旧文件
    assert ppc.save_html(PID, "<html>NEW</html>") is False
    # 旧文件内容不变
    assert old_path.read_text() == old_content
    # 无残留 .tmp(tmp 由 finally 清理)
    assert list(old_path.parent.glob("*.tmp")) == []


# ── fetch_player_page（mock 网络）────────────────────────────────────────────
def _fake_get(text: str, status: int = 200):
    def _get(url, **kwargs):
        return types.SimpleNamespace(status_code=status, text=text)
    return _get


def test_fetch_network_unreachable_returns_none_no_cache(monkeypatch):
    import curl_cffi.requests as cffi_requests

    def _boom(url, **kwargs):
        raise ConnectionError("simulated network failure")
    monkeypatch.setattr(cffi_requests, "get", _boom)

    assert ppc.fetch_player_page(PID) is None
    # 失败不应落盘
    assert ppc.is_cached(PID) is False


def test_fetch_success_then_cache_serves_second_call(monkeypatch):
    import curl_cffi.requests as cffi_requests

    hits = {"n": 0}

    def _counting_get(url, **kwargs):
        hits["n"] += 1
        return types.SimpleNamespace(status_code=200, text=SAMPLE_HTML)
    monkeypatch.setattr(cffi_requests, "get", _counting_get)

    # 首次: 未缓存 → 网络 + 落盘
    assert ppc.fetch_player_page(PID) == SAMPLE_HTML
    assert hits["n"] == 1
    assert ppc.is_cached(PID) is True

    # 二次: 命中缓存 → 不重抓
    assert ppc.fetch_player_page(PID) == SAMPLE_HTML
    assert hits["n"] == 1


def test_fetch_cf_challenge_returns_none(monkeypatch):
    import curl_cffi.requests as cffi_requests

    cf = (
        "<!DOCTYPE html><html><head><title>Just a moment...</title></head>"
        "<body><p>Checking your browser before accessing Basketball-Reference.</p>"
        "</body></html>"
    )
    monkeypatch.setattr(cffi_requests, "get", _fake_get(cf, 200))
    assert ppc.fetch_player_page(PID) is None
    assert ppc.is_cached(PID) is False


def test_player_page_url_built_correctly():
    assert ppc.player_page_url("antetgi01") == (
        "https://www.basketball-reference.com/players/a/antetgi01.html"
    )
