"""test_br_player_404.py — 404 根因修复 QA（Fix 1–4）。

覆盖 team-lead 重定向的「报告真正根因是 404」四项修复：

  Fix 1 — 404 检测：fetch_team_page 命中 404 标记 → 返回 "" 并置
          ``_last_fetch_404=True``；真实球员页不误判。
  Fix 2 — 404 隔离：_crawl_player 命中 404 时隔离到 player_shooting_404
          （note='http_404'），**不**写 raw_archive、**不**解析、**不**登记
          crawl_failures；enumerate_players(priority_gap) 的 gap 查询排除已隔离 slug。
  Fix 3 — 损坏 slug 预过滤：_flag_corrupted_slugs 把赛季跨度异常 slug 标记为
          corrupted 并隔离；enumerate_players 不再枚举它们。
  Fix 4 — URL/页面格式校验：build_player_shooting_url / html_has_shooting_table /
          self_test_player_url 静态校验（**不抓 BR**，沙箱过不了 CF）。

夹具：
  * 404 页：raw_archive/br_players/alexaga01/shooting.html
    （<title>Page Not Found (404 error)</title> + canonical /404.html）
  * 真实页：raw_archive/br_players/brownja02/shooting.html（含 id="shooting"）

DB 相关用例使用 MockConn（不连真实库），全部在 sandbox 离线跑；
不含任何 BR 网络请求。若环境有 PGPASSWORD+集群 B，可用 --live 之外的方式跑，
但本文件刻意全部 mock，确保零外部依赖、零回归风险。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from common.br_player_page import (  # noqa: E402
    BRPlayerPageCrawler,
    build_player_shooting_url,
    html_has_shooting_table,
    self_test_player_url,
)
from external_crawler.crawler.crawl_br_player_shooting import (  # noqa: E402
    PlayerShootingCrawler,
)

FIXTURE_404 = ROOT / "raw_archive" / "br_players" / "alexaga01" / "shooting.html"
FIXTURE_REAL = ROOT / "raw_archive" / "br_players" / "brownja02" / "shooting.html"


def _load_404() -> str:
    assert FIXTURE_404.exists(), f"404 夹具缺失: {FIXTURE_404}"
    return FIXTURE_404.read_text(encoding="utf-8")


def _load_real() -> str:
    assert FIXTURE_REAL.exists(), f"真实页夹具缺失: {FIXTURE_REAL}"
    return FIXTURE_REAL.read_text(encoding="utf-8")


# ── 测试用 FakeDriver（贴合 common.browser 的 .get(url) / .page_source 接口）──
class FakeDriver:
    def __init__(self, html: str) -> None:
        self._html = html
        self.last_url: str = ""

    def get(self, url: str) -> None:
        self.last_url = url

    @property
    def page_source(self) -> str:
        return self._html


# ── 测试用 MockConn / MockCursor（离线，记录所有 INSERT 以便断言）────────────
class _MockCursor:
    def __init__(self, router, log):
        self._router = router
        self._log = log

    def execute(self, sql: str, params=None):
        self._log.append((sql, params))
        self._rows = self._router(sql, params or ())

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def close(self):
        pass


class _MockConn:
    def __init__(self, router):
        self._router = router
        self.log: list = []
        self.committed = 0

    def cursor(self):
        return _MockCursor(self._router, self.log)

    def commit(self):
        self.committed += 1


def _make_router(inserts: list):
    """SQL 路由：corrupted 查询返回 'xreuse01'，gap 查询返回两个好 slug，
    player_shooting_404 的 INSERT 记入 inserts，其余返回空。"""

    def router(sql: str, params):
        s = sql
        if s.strip().upper().startswith("INSERT"):
            m = re.search(r"INSERT INTO (\w+)", s)
            table = m.group(1) if m else "?"
            inserts.append((table, params))
            return []
        if "GROUP BY br_player_id" in s and "HAVING" in s:
            return [("xreuse01",)]
        if "player_shooting_404 q" in s:  # gap 查询（LEFT JOIN 别名 q）
            return [("goodslug01",), ("goodslug02",)]
        return []

    return router


# ═══════════════════════════════════════════════════════════════════════════
# Fix 1 — 404 检测（fetch_team_page）
# ═══════════════════════════════════════════════════════════════════════════
def test_fetch_team_page_detects_404_returns_empty_and_sets_flag():
    crawler = BRPlayerPageCrawler()
    out = crawler.fetch_team_page(FakeDriver(_load_404()), "http://x/shooting/")
    assert out == "", "404 页必须返回空串（与 CF/空页同处理）"
    assert crawler._last_fetch_404 is True, "必须置 _last_fetch_404=True"
    assert crawler._last_fetch_cf is False, "404 不应误置 CF 标志"


def test_fetch_team_page_real_page_not_flagged():
    crawler = BRPlayerPageCrawler()
    html = _load_real()
    out = crawler.fetch_team_page(FakeDriver(html), "http://x/shooting/")
    assert out == html, "真实页原样返回"
    assert crawler._last_fetch_404 is False, "真实页不得误判 404"
    assert crawler._last_fetch_cf is False, "真实页不得误判 CF"


# ═══════════════════════════════════════════════════════════════════════════
# Fix 2 — 404 隔离（_crawl_player）
# ═══════════════════════════════════════════════════════════════════════════
def test_crawl_player_quarantines_404_skips_save_and_parse():
    inserts: list = []
    conn = _MockConn(_make_router(inserts))
    crawler = PlayerShootingCrawler()
    # 若 404 路径错误地调用了 save_raw_html/_consume_html，直接炸，证明被跳过。
    crawler.save_raw_html = lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("404 不应写 raw_archive"))
    crawler._consume_html = lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("404 不应解析"))

    n = crawler._crawl_player(conn, FakeDriver(_load_404()), "alexaga01")

    assert n == 0, "404 页应返回 0 行"
    assert crawler._last_fetch_404 is True
    q = [p for (t, p) in inserts if t == "player_shooting_404"]
    assert q, "必须把 404 slug 隔离进 player_shooting_404"
    assert ("alexaga01", "http_404") in q, "隔离 note 应为 http_404"
    assert not any(t == "crawl_failures" for (t, _) in inserts), \
        "404 不应污染 crawl_failures"


def test_crawl_player_registers_failure_on_cf_not_quarantine():
    inserts: list = []
    conn = _MockConn(_make_router(inserts))
    crawler = PlayerShootingCrawler()
    cf_html = "<html><head><title>Just a moment</title></head><body>Checking your browser</body></html>"
    n = crawler._crawl_player(conn, FakeDriver(cf_html), "somecfslug")

    assert n == 0, "CF 挑战页应返回 0 行"
    assert crawler._last_fetch_cf is True
    assert crawler._last_fetch_404 is False
    assert any(t == "crawl_failures" for (t, _) in inserts), \
        "CF 页应有 crawl_failures 登记"
    assert not any(t == "player_shooting_404" for (t, _) in inserts), \
        "CF 页不应进 404 隔离表"


# ═══════════════════════════════════════════════════════════════════════════
# Fix 2/3 — enumerate_players 排除已隔离 / corrupted slug（mock DB）
# ═══════════════════════════════════════════════════════════════════════════
def test_enumerate_players_excludes_quarantined_and_corrupted():
    inserts: list = []
    conn = _MockConn(_make_router(inserts))
    crawler = PlayerShootingCrawler()

    slugs = crawler.enumerate_players(conn, priority_gap=True)

    # corrupted(xreuse01) 已被隔离、且 gap 查询排除 q.slug → 不应出现
    assert slugs == ["goodslug01", "goodslug02"], slugs
    assert "xreuse01" not in slugs, "corrupted slug 不应进入缺口枚举"
    # 确认 corrupted 隔离已写入（note='corrupted'）
    q = [p for (t, p) in inserts if t == "player_shooting_404"]
    assert ("xreuse01", "corrupted") in q, "corrupted slug 应写隔离表 note=corrupted"


def test_flag_corrupted_slugs_writes_quarantine():
    inserts: list = []
    conn = _MockConn(_make_router(inserts))
    crawler = PlayerShootingCrawler()

    n = crawler._flag_corrupted_slugs(conn)

    assert n == 1, "应隔离 1 个 corrupted slug"
    q = [p for (t, p) in inserts if t == "player_shooting_404"]
    assert ("xreuse01", "corrupted") in q


# ═══════════════════════════════════════════════════════════════════════════
# Fix 4 — URL / 页面格式校验（纯函数，不抓 BR）
# ═══════════════════════════════════════════════════════════════════════════
def test_build_url_format_known_good_slug():
    # LeBron James 必存在；URL 格式与实例 build_url 一致
    assert build_player_shooting_url("jamesle01") == (
        "https://www.basketball-reference.com/players/j/jamesle01/shooting/"
    )
    c = BRPlayerPageCrawler()
    assert c.build_url("jamesle01") == build_player_shooting_url("jamesle01")


def test_html_has_shooting_table_detects_valid_and_404():
    assert html_has_shooting_table(_load_real()) is True
    assert html_has_shooting_table(_load_404()) is False
    assert html_has_shooting_table("") is False


def test_self_test_player_url_format_and_contract():
    # 格式 + 契约静态校验（不抓 BR）
    assert self_test_player_url("jamesle01") == (
        "https://www.basketball-reference.com/players/j/jamesle01/shooting/"
    )
    # 空 slug → 格式异常被断言拦下
    with pytest.raises(AssertionError):
        self_test_player_url("")


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
