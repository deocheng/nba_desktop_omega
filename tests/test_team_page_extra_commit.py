"""Regression test: extra_extract() writes must be committed.

Bug being pinned
----------------
``BRTeamPageCrawler._crawl_team`` runs, per team-season:

    1. ``_crawl_one(...)``  → upsert the main table → ``conn.commit()``
    2. ``extra_extract(...)`` → upsert a *second* table (e.g. team_page_raw)

Step 2 happens **after** step 1's commit, and psycopg2 runs in
non-autocommit mode, so those rows sit in an open transaction.  If the
team-season just processed is the **last** one of the run, the process exits
and psycopg2 rolls the transaction back — the rows are silently lost.

Observed: a single-team/single-season run logged
``[page_raw] POR/2024/Regular/totals_stats 落 639 行`` (and 6 more tables)
while ``SELECT count(*) FROM team_page_raw WHERE team_abbr='POR' AND
season=2024`` returned **0**.  Multi-team runs had masked it, because the
*next* ``_crawl_one`` commit happened to flush the previous transaction.

Run from the repo root:
    python -m pytest tests/test_team_page_extra_commit.py -v
"""

from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from common.br_team_page import BRTeamPageCrawler  # noqa: E402


class FakeConn:
    """Records commit/rollback calls in order."""

    def __init__(self) -> None:
        self.events: list[str] = []

    def commit(self) -> None:
        self.events.append("commit")

    def rollback(self) -> None:
        self.events.append("rollback")

    def cursor(self):
        class _Cur:
            def execute(self, *a, **k):
                return None

            def fetchone(self):
                return None

            def close(self):
                return None

        return _Cur()


class _StubCrawler(BRTeamPageCrawler):
    """Minimal crawler that mimics the real _crawl_one/extra_extract order."""

    DOMAIN = "stub"
    TASK_TYPE = "stub"
    TABLE = "stub_table"
    TABLE_ID = "stub"
    CONFLICT_COLS = ("team_abbr", "season", "season_type")
    SEASON_TYPES = ("Regular",)
    MIN_SEASON = 1997

    def parse(self, html, season_type="Regular", team_abbr=None):
        return []

    def build_rows(self, conn, team_abbr, season, season_type, rec):
        return {}

    def upsert(self, conn, rows):
        return 0

    def _crawl_one(self, conn, driver, slug, season, season_type,
                   cache_dir, full, html=None):
        # The real _crawl_one commits after its own upsert.
        conn.commit()
        return 0

    def extra_extract(self, conn, driver, slug, season, html):
        conn.events.append("extra_extract")
        return 1

    def _nav_button(self, driver, which, current_season=None):
        return None

    def fetch_team_page(self, driver, url):
        return "<html></html>"

    def build_url(self, slug, season, page, season_type="Regular"):
        return f"https://example.invalid/{slug}/{season}.html"


def test_extra_extract_is_followed_by_commit():
    """The writes made by extra_extract must be committed before returning."""
    crawler = _StubCrawler()
    conn = FakeConn()

    crawler._crawl_team(conn, None, "POR", 2024, 2024, None, False, False)

    assert "extra_extract" in conn.events, "extra_extract did not run"
    idx = conn.events.index("extra_extract")
    # there must be a commit AFTER extra_extract
    assert "commit" in conn.events[idx + 1:], (
        f"extra_extract 的写入未被提交，末尾事件={conn.events[idx:]}"
    )
    assert conn.events[-1] == "commit", (
        f"最后一季的 extra_extract 必须以 commit 收尾，实际={conn.events}"
    )


def test_extra_extract_failure_rolls_back_and_does_not_raise():
    """A failing extra_extract must not poison the transaction."""
    class _Boom(_StubCrawler):
        def extra_extract(self, conn, driver, slug, season, html):
            conn.events.append("extra_extract")
            raise RuntimeError("boom")

    crawler = _Boom()
    conn = FakeConn()
    crawler._crawl_team(conn, None, "POR", 2024, 2024, None, False, False)
    assert "rollback" in conn.events
    assert conn.events[-1] == "rollback"


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
