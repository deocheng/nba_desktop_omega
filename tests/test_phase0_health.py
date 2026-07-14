"""Phase 0 — Environment Bootstrap verification tests.

Covers v8 §4 Phase 0 acceptance:
    - /health returns 200 + DB connectivity + server starts
    - config management (port 5433 inherited from v7)
    - logging with query_id traceability
    - runtime_guard startup checks
    - SQL validation (only SELECT allowed)

NO mocks for Metric Engine (v8 §6). DB-dependent paths skip if DB down.
"""
from __future__ import annotations

import pytest

from backend.core import config
from backend.core.db import validate_batch_sql
from backend.core.logging import new_query_id, query_id_var, setup_logging


# ── §4 Phase 0: config management ──

class TestConfig:

    def test_db_port_is_5433_from_v7(self):
        """v7 used port 5433 (non-default). v8 must inherit."""
        assert config.DB_PORT == 5433, "DB_PORT must be 5433 (v7 convention)"

    def test_db_name_is_nba(self):
        assert config.DB_NAME == "nba"

    def test_app_version_is_v8(self):
        assert config.APP_VERSION == "8.0.0"

    def test_current_season_returns_int(self):
        s = config.current_season()
        assert isinstance(s, int)
        assert 2020 <= s <= 2030

    def test_db_dsn_format(self):
        dsn = config.db_dsn()
        assert dsn.startswith("postgresql://")
        assert f":{config.DB_PORT}/" in dsn


# ── §5.2: SQL trace & batch check ──

class TestSqlValidation:

    def test_select_allowed(self):
        # Should NOT raise
        validate_batch_sql("SELECT 1")
        validate_batch_sql("  SELECT * FROM player_gamelog WHERE season = 2025  ")
        validate_batch_sql("(SELECT 1)")

    @pytest.mark.parametrize("bad_sql", [
        "INSERT INTO t VALUES (1)",
        "UPDATE t SET x = 1",
        "DELETE FROM t",
        "DROP TABLE t",
        "ALTER TABLE t ADD COLUMN x int",
        "CREATE TABLE t (x int)",
        "TRUNCATE t",
        "GRANT SELECT ON t TO u",
    ])
    def test_forbidden_dml_ddl_rejected(self, bad_sql: str):
        with pytest.raises(ValueError, match="Forbidden SQL"):
            validate_batch_sql(bad_sql)

    def test_empty_sql_rejected(self):
        with pytest.raises(ValueError, match="Empty SQL"):
            validate_batch_sql("")


# ── §5.1: layer leakage check (Phase 0 skeleton) ──

class TestLayerIsolation:

    def test_app_does_not_import_psycopg2_directly(self):
        """v8 §2: API layer must not touch DB driver directly."""
        import backend.app as app_mod
        src = open(app_mod.__file__, encoding="utf-8").read()
        assert "import psycopg2" not in src, \
            "app.py must not import psycopg2 (use backend.core.db only)"
        assert "from psycopg2" not in src

    def test_app_has_no_select_statement(self):
        """v8 §2: API layer (app.py) must not contain SQL keywords."""
        import backend.app as app_mod
        src = open(app_mod.__file__, encoding="utf-8").read()
        # Skip docstring/comment lines, then assert no SQL SELECT keyword
        in_docstring = False
        for line in src.splitlines():
            stripped = line.strip()
            if stripped.startswith('"""'):
                in_docstring = not in_docstring
                continue
            if in_docstring or stripped.startswith("#"):
                continue
            assert "SELECT" not in stripped.upper(), \
                f"app.py must not contain SQL keyword: {line!r}"


# ── §5.5: runtime guard ──

class TestRuntimeGuard:

    def test_guard_returns_all_checks(self):
        from backend.core.runtime_guard import run_startup_checks
        results = run_startup_checks()
        assert isinstance(results, dict)
        assert "config_loaded" in results
        assert "metric_engine_exists" in results
        assert "no_forbidden_patterns" in results

    def test_config_check_passes(self):
        from backend.core.runtime_guard import run_startup_checks
        r = run_startup_checks()["config_loaded"]
        assert r["ok"] is True
        assert r["detail"]["db_port"] == 5433

    def test_metric_engine_exists_check_passes(self):
        """v8 §2: metric_engine must be importable as sole compute layer."""
        from backend.core.runtime_guard import run_startup_checks
        r = run_startup_checks()["metric_engine_exists"]
        assert r["ok"] is True, r.get("error")

    def test_no_forbidden_patterns_check_passes(self):
        from backend.core.runtime_guard import run_startup_checks
        r = run_startup_checks()["no_forbidden_patterns"]
        assert r["ok"] is True, r.get("error")


# ── §5.3: determinism (query_id generation) ──

class TestLoggingTraceability:

    def test_new_query_id_is_unique_12char(self):
        id1 = new_query_id()
        id2 = new_query_id()
        assert id1 != id2
        assert len(id1) == 12
        assert len(id2) == 12

    def test_query_id_bound_to_context(self):
        qid = new_query_id()
        assert query_id_var.get() == qid

    def test_setup_logging_idempotent(self):
        # Calling twice must not duplicate handlers
        setup_logging("INFO")
        h1 = len(__import__("logging").getLogger().handlers)
        setup_logging("INFO")
        h2 = len(__import__("logging").getLogger().handlers)
        assert h1 == h2


# ── §4 Phase 0: /health endpoint (end-to-end) ──

class TestHealthEndpoint:

    def test_health_returns_200(self, app_client):
        resp = app_client.get("/health")
        assert resp.status_code == 200

    def test_health_has_required_fields(self, app_client):
        body = app_client.get("/health").json()
        assert "status" in body
        assert "version" in body
        assert "database_connected" in body
        assert "runtime_guard" in body

    def test_health_status_is_ok_or_degraded(self, app_client):
        body = app_client.get("/health").json()
        assert body["status"] in ("ok", "degraded")

    def test_health_version_matches_config(self, app_client):
        body = app_client.get("/health").json()
        assert body["version"] == config.APP_VERSION

    def test_health_database_connected_is_bool(self, app_client):
        body = app_client.get("/health").json()
        assert isinstance(body["database_connected"], bool)

    def test_root_endpoint(self, app_client):
        body = app_client.get("/").json()
        assert body["name"] == config.APP_NAME
        # Phase reflects current project stage (Phase 10 — v7 feature migration).
        # Updated from "7-testing-monitoring" after the Phase 10 feature merge.
        assert body["phase"] == "10-v7-feature-migration"


# ── §4 Phase 0: DB connectivity (skipped if DB down) ──

class TestDbConnectivity:

    def test_ping_returns_bool(self, db_available):
        if not db_available:
            pytest.skip("PostgreSQL not available")
        from backend.core.db import ping
        assert isinstance(ping(), bool)

    def test_batch_query_select_one(self, db_available):
        if not db_available:
            pytest.skip("PostgreSQL not available")
        from backend.core.db import batch_query
        rows = batch_query("SELECT 1 AS ok")
        assert len(rows) == 1
        assert rows[0]["ok"] == 1
