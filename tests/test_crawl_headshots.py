"""external_crawler/crawler/crawl_br_headshots.py 控制流测试（dry-run，不联网不写库）。

覆盖：
  * CLI ``--help`` 暴露 --limit / --dry-run / --resume
  * ``get_players``：resume=True 仅查 (status IS NULL OR status='failed')；False 全量
  * ``upsert_path``：UPDATE 四列 + now()，参数顺序正确
  * ``run_pipeline(dry_run=True)``：mock psycopg2，断言 不下载 / 不写库 / rollback / 打印计划
  * ``scrape_player``：ok（Tier-1 失败→Tier-2 兜底）/ missing / failed 三态与 Tier-1→Tier-2 回退

全部使用 mock，绝不连接真实 DB、绝不触碰 9222 CDP、绝不写 12TB 盘（HEADSHOT_ROOT→tmp）。
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parents[1]
CRAWLER_DIR = ROOT / "external_crawler" / "crawler"
for _p in (str(ROOT), str(CRAWLER_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import crawl_br_headshots as crawler

# 测试样本字节：合法 JPEG 魔法头（FFD8FF），供 Tier-2 兜底落盘与 _resolve_stored_path 用。
# 注：JPG_BYTES 由 headshot_store 单测定义于测试侧，本文件本地定义以解耦。
JPG_BYTES = b"\xff\xd8\xff" + b"JFIF fake jpeg payload\x00\x01\x02"

PLAYER_ID = "jamesle01"
IMG_URL = "https://www.basketball-reference.com/req/202605210/images/headshots/jamesle01.jpg"
PLAYER_PAGE_HTML = f"""<html><body><div id="info"><div class="media-item">
<img src="{IMG_URL}" alt="Photo"></div></div></body></html>"""
NO_IMG_HTML = """<html><body><div id="info"><div class="media-item"></div></div></body></html>"""


# ── DB 替身 ──────────────────────────────────────────────────────────────
class FakeCursor:
    def __init__(self, rows=None):
        self.queries = []  # 存 (sql, params)
        self.rows = rows if rows is not None else [
            ("jamesle01", "LeBron James"),
            ("davisan01", "Anthony Davis"),
            ("curryan01", "Stephen Curry"),
        ]

    def execute(self, q, params=None):
        self.queries.append((q, params))

    def fetchall(self):
        return self.rows

    def fetchone(self):
        return (0,)

    def close(self):
        pass


class FakeConn:
    def __init__(self):
        self._cur = FakeCursor()
        self.commit_calls = 0
        self.rollback_calls = 0
        self.closed = False

    def cursor(self):
        return self._cur

    def commit(self):
        self.commit_calls += 1

    def rollback(self):
        self.rollback_calls += 1

    def close(self):
        self.closed = True


# ── CLI --help ────────────────────────────────────────────────────────────
def test_cli_help_exposes_required_flags():
    """argparse 必须暴露 --limit/--dry-run/--resume（验收 HS-01）。"""
    py = str(ROOT / ".venv" / "bin" / "python")
    script = str(ROOT / "external_crawler" / "crawler" / "crawl_br_headshots.py")
    proc = subprocess.run([py, script, "--help"], cwd=str(ROOT),
                          capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr
    for flag in ("--limit", "--dry-run", "--resume"):
        assert flag in proc.stdout, f"{flag} 未在 --help 中暴露"


# ── get_players resume 跳过逻辑 ────────────────────────────────────────────
def test_get_players_resume_skips_ok_and_missing():
    """resume=True → 只查 (status IS NULL OR status='failed')（OQ-1 / HS-05）。"""
    conn = FakeConn()
    crawler.get_players(conn, limit=10, resume=True)
    sql = conn._cur.queries[-1][0]
    assert "headshot_status IS NULL OR headshot_status = 'failed'" in sql
    assert "LIMIT 10" in sql


def test_get_players_full_no_resume_filter():
    """resume=False → 全量查询，不带 status 过滤。"""
    conn = FakeConn()
    crawler.get_players(conn, limit=5, resume=False)
    sql = conn._cur.queries[-1][0]
    assert "headshot_status IS NULL OR headshot_status = 'failed'" not in sql
    assert "LIMIT 5" in sql


# ── upsert_path ────────────────────────────────────────────────────────────
def test_upsert_path_writes_four_columns_with_now():
    """upsert_path 必须写 headshot_path/url/status/scraped_at=now()，参数顺序正确。"""
    conn = FakeConn()
    crawler.upsert_path(conn, PLAYER_ID, "/tmp/x.jpg", IMG_URL, "ok")
    sql, params = conn._cur.queries[-1]
    assert "UPDATE dim_players" in sql
    for col in ("headshot_path", "headshot_url", "headshot_status", "headshot_scraped_at"):
        assert col in sql
    assert "now()" in sql
    # 参数顺序：path, url, status, player_id
    assert params == ("/tmp/x.jpg", IMG_URL, "ok", PLAYER_ID)


# ── run_pipeline dry-run 控制流 ────────────────────────────────────────────
def test_run_pipeline_dry_run_control_flow(monkeypatch, caplog):
    """dry-run：连接（mock）、读取 player_id、打印计划、不下载、不写库、rollback。"""
    import logging
    caplog.set_level(logging.INFO, logger="crawl_br_headshots")

    fake_conn = FakeConn()
    monkeypatch.setattr(crawler.psycopg2, "connect", lambda **k: fake_conn)
    # dry-run 不会触达 download_image / fetch_image_via_cdp / get_driver，
    # 但保险起见仍拦掉（download_image/fetch_image_via_cdp 是模块级导入，可 patch；
    # get_driver 是 run_pipeline 内局部 import，非模块属性，不宜 patch）。
    monkeypatch.setattr(crawler, "download_image", lambda *a, **k: None)
    monkeypatch.setattr(crawler, "fetch_image_via_cdp", lambda *a, **k: None)

    crawler.run_pipeline(limit=3, dry_run=True, resume=False)

    # 读到了 3 个 player 并准备处理
    assert "待处理 3 行" in caplog.text
    assert "[dry-run] 计划处理" in caplog.text
    # 不写库（dry-run 跳过 upsert 分支），仅在结尾 rollback
    assert fake_conn.commit_calls == 0
    assert fake_conn.rollback_calls == 1
    assert fake_conn.closed is True


# ── scrape_player 三态 + Tier-1→Tier-2 回退 ───────────────────────────────
@pytest.fixture
def patch_root(tmp_path, monkeypatch):
    monkeypatch.setattr(crawler, "HEADSHOT_ROOT", tmp_path)
    return tmp_path


def _driver_with(html: str) -> MagicMock:
    d = MagicMock()
    d.page_source = html
    return d


def test_scrape_player_ok_via_tier2_fallback(patch_root, monkeypatch):
    """Tier-1 失败 → Tier-2 兜底成功 → 落盘 + 返回 ('ok', url)（两级下载回退）。"""
    monkeypatch.setattr(crawler, "download_image", lambda *a, **k: None)  # Tier-1 失败
    monkeypatch.setattr(crawler, "fetch_image_via_cdp", lambda *a, **k: JPG_BYTES)  # Tier-2 成功

    status, url = crawler.scrape_player(PLAYER_ID, "LeBron James", _driver_with(PLAYER_PAGE_HTML))

    assert status == "ok"
    assert url == IMG_URL
    written = patch_root / f"{PLAYER_ID}.jpg"
    assert written.exists() and written.read_bytes() == JPG_BYTES


def test_scrape_player_missing_when_no_img(patch_root, monkeypatch):
    """球员页无 headshot（BR 本身缺图）→ ('missing', None)，不下载不写盘。"""
    dl = MagicMock(return_value=None)
    cdp = MagicMock(return_value=None)
    monkeypatch.setattr(crawler, "download_image", dl)
    monkeypatch.setattr(crawler, "fetch_image_via_cdp", cdp)

    status, url = crawler.scrape_player(PLAYER_ID, "Some Historic", _driver_with(NO_IMG_HTML))

    assert status == "missing"
    assert url is None
    dl.assert_not_called()
    cdp.assert_not_called()
    assert not list(patch_root.glob(f"{PLAYER_ID}.*"))


def test_scrape_player_failed_when_both_tiers_fail(patch_root, monkeypatch):
    """Tier-1 与 Tier-2 均失败 → ('failed', url)，记录 URL 便于排查。"""
    monkeypatch.setattr(crawler, "download_image", lambda *a, **k: None)
    monkeypatch.setattr(crawler, "fetch_image_via_cdp", lambda *a, **k: None)

    status, url = crawler.scrape_player(PLAYER_ID, "LeBron James", _driver_with(PLAYER_PAGE_HTML))

    assert status == "failed"
    assert url == IMG_URL
    assert not list(patch_root.glob(f"{PLAYER_ID}.*"))


def test_scrape_player_failed_when_nav_raises(patch_root, monkeypatch):
    """driver.get 抛异常（网络/CF）→ 单人失败不中断整体，返回 ('failed', None)。"""
    d = MagicMock()
    d.get.side_effect = RuntimeError("navigation boom")
    monkeypatch.setattr(crawler, "download_image", lambda *a, **k: None)
    monkeypatch.setattr(crawler, "fetch_image_via_cdp", lambda *a, **k: None)

    status, url = crawler.scrape_player(PLAYER_ID, "LeBron James", d)
    assert status == "failed"
    assert url is None


# ── _resolve_stored_path ──────────────────────────────────────────────────
def test_resolve_stored_path_hits_existing_file(patch_root):
    (patch_root / f"{PLAYER_ID}.jpg").write_bytes(JPG_BYTES)
    assert crawler._resolve_stored_path(PLAYER_ID) == str(patch_root / f"{PLAYER_ID}.jpg")


def test_resolve_stored_path_png_variant(patch_root):
    (patch_root / f"{PLAYER_ID}.png").write_bytes(JPG_BYTES)
    assert crawler._resolve_stored_path(PLAYER_ID) == str(patch_root / f"{PLAYER_ID}.png")


def test_resolve_stored_path_empty_file_is_none(patch_root):
    (patch_root / f"{PLAYER_ID}.jpg").write_bytes(b"")  # 0 字节 → 视为不存在
    assert crawler._resolve_stored_path(PLAYER_ID) is None


def test_resolve_stored_path_missing_is_none(patch_root):
    assert crawler._resolve_stored_path("nobody") is None
