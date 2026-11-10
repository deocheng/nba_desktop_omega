"""NBACore v8.3.2 — §6 four-layer isolation compliance (static checks).

These tests enforce the hard architectural constraint from the v8.3.2 spec:

  Layer 3 (router /api/analytics-builder):
    - MUST contain ZERO raw SQL substrings (SELECT/INSERT/UPDATE/DELETE/CREATE)
    - MUST NOT import pandas / numpy
    - MUST stay <= 200 lines
    - Imports restricted to fastapi + schema/service/validation modules
  Read SQL  -> ONLY analytics_builder_engine/ab_queries.py (via db.batch_query)
  Flow DML  -> ONLY workspace_engine/workspace_db.py (the psycopg2 write layer)
  Frontend  -> ZERO computation (no eval/exec/SQL, no aggregation)

No DB required — pure source inspection.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENGINE = ROOT / "backend" / "services" / "analytics_builder_engine"
ROUTER = ROOT / "backend" / "api" / "routers" / "analytics_builder.py"
WORKSPACE_DB = ROOT / "backend" / "services" / "workspace_engine" / "workspace_db.py"
FRONTEND = ROOT / "frontend" / "js" / "components"

# Uppercase SQL keyword matcher (our backend always writes SQL in UPPER CASE;
# this avoids false positives on identifiers like "onselect" / "create:").
SQL_RE = re.compile(r"\b(SELECT|INSERT|UPDATE|DELETE|CREATE)\b")

# 前端专用：只匹配「真正的 SQL 语句形态」——关键字后必须跟空白 + SQL 语法
# （FROM / INTO / TABLE / 等），从而放过 AB_deleteFlow / AB_clearCanvas 这类
# 纯 JS 函数名（deleteFlow 是前端业务 API，不是 SQL）。
FRONTEND_SQL_RE = re.compile(
    r"(?<![<\w])(?:SELECT\s+(?:\*|DISTINCT\b|[\w.]+\s+FROM\b)|INSERT\s+INTO\b|UPDATE\s+[\w.]+\s+SET\b|"
    r"DELETE\s+FROM\b|CREATE\s+(TABLE|INDEX|VIEW)\b)",
    re.IGNORECASE,
)

ALLOWED_ROUTER_IMPORTS = {
    "fastapi",
    "__future__",
    "backend.api.routers.ab_schemas",
    "backend.services.analytics_builder_engine.ab_service",
    "backend.services.analytics_builder_engine.ab_validation",
    "typing",
}

# 允许的前缀规则（表达 §6 的架构意图，避免枚举具体模块名导致断言随代码演进过时）：
#   Layer 3 允许依赖同层的「契约模块」（*_schemas）与「引擎层」模块，
#   但不得直接依赖 pandas / numpy / 任何写库层。
ALLOWED_ROUTER_PREFIXES = (
    "backend.api.routers.analytics_builder_schemas",
    "backend.services.analytics_builder_engine",
)


def _router_import_allowed(mod: str) -> bool:
    if mod in ALLOWED_ROUTER_IMPORTS:
        return True
    return any(mod == p or mod.startswith(p + ".") for p in ALLOWED_ROUTER_PREFIXES)


def _src(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_router_has_no_sql_substrings():
    src = _src(ROUTER)
    assert not SQL_RE.search(src), f"router contains forbidden SQL keyword: {SQL_RE.search(src).group(0)!r}"


def test_router_under_200_lines():
    lines = _src(ROUTER).splitlines()
    assert len(lines) <= 200, f"router is {len(lines)} lines (>200): violates §6"


def test_router_no_pandas_numpy():
    src = _src(ROUTER)
    assert "import pandas" not in src
    assert "import numpy" not in src
    assert "from pandas" not in src
    assert "from numpy" not in src


def test_router_imports_restricted():
    tree = ast.parse(_src(ROUTER))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for n in node.names:
                assert _router_import_allowed(n.name) or n.name.split(".")[0] in ("fastapi", "typing"), \
                    f"router imports non-allowed module: {n.name}"
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            assert _router_import_allowed(mod), f"router imports non-allowed module: {mod}"


def test_router_no_eval_exec():
    src = _src(ROUTER)
    assert "eval(" not in src
    assert "exec(" not in src


def test_ab_queries_is_read_only():
    src = _src(ENGINE / "ab_queries.py")
    for kw in ("INSERT ", "UPDATE ", "DELETE ", "CREATE "):
        assert kw not in src, f"ab_queries.py must be read-only but contains {kw!r}"
    # SELECT must flow only through db.batch_query
    assert "db.batch_query" in src
    assert "def build_source_sql" in src


def test_workspace_db_is_the_write_layer():
    src = _src(WORKSPACE_DB)
    assert "psycopg2" in src, "workspace_db.py must be the psycopg2 write layer"
    # the designated write layer legitimately performs flow DML
    assert "INSERT INTO analysis_flows" in src
    assert "UPDATE analysis_flows" in src
    assert "DELETE FROM analysis_flows" in src


def test_frontend_no_eval_exec_sql():
    files = [
        "ab_nodes.js", "ab_canvas.js", "ab_properties.js",
        "ab_runner.js", "analytics_builder.js",
    ]
    for fn in files:
        p = FRONTEND / fn
        src = _src(p)
        assert "eval(" not in src, f"{fn} contains eval() — frontend must not compute"
        assert "exec(" not in src, f"{fn} contains exec() — frontend must not compute"
        # 用「SQL 语句形态」正则，而非裸关键字 —— 否则 AB_deleteFlow 等
        # 纯 JS 业务函数名会被误判成 SQL（2026-11-10 实测误报）。
        m = FRONTEND_SQL_RE.search(src)
        assert m is None, f"{fn} contains SQL statement {m.group(0)!r}"


def test_frontend_no_aggregation_loops():
    """Best-effort guard: the frontend must not implement aggregation math.

    We forbid patterns that would indicate local numeric aggregation over rows.
    """
    forbidden = ("reduce(", "Math.sum", ".reduce(")
    files = ["ab_nodes.js", "ab_canvas.js", "ab_properties.js", "ab_runner.js", "analytics_builder.js"]
    for fn in files:
        src = _src(FRONTEND / fn)
        for pat in forbidden:
            assert pat not in src, f"{fn} contains {pat!r} — aggregation belongs in the backend"
