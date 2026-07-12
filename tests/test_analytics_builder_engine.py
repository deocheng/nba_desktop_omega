"""NBACore v8.3.2 — Analytics Builder engine unit + integration tests.

Covers:
  - safe_arithmetic_eval (no eval/exec; precedence; error paths)
  - FlowGraph parse / topo-sort / cycle detection
  - per-node param validators
  - run_flow pre-validation (cycle, dangling visualize, missing upstream)
  - executor behaviour on in-memory Tables (filter/aggregate/transform)
  - end-to-end run_flow against live data (skipped if no PostgreSQL)

v8 §6: DB-dependent tests use a live connection (skipped if unavailable).
"""
from __future__ import annotations

import pytest

try:
    from backend.core.db import ping as _db_ping
    _DB_AVAILABLE = bool(_db_ping())
except Exception:
    _DB_AVAILABLE = False

needs_db = pytest.mark.skipif(not _DB_AVAILABLE, reason="needs live PostgreSQL")

from backend.services.analytics_builder_engine import ab_utils as U
from backend.services.analytics_builder_engine import ab_graph as G
from backend.services.analytics_builder_engine import ab_validation as V
from backend.services.analytics_builder_engine import ab_service
from backend.services.analytics_builder_engine.ab_executors import (
    execute_aggregate,
    execute_filter,
    execute_transform,
)
from backend.services.analytics_builder_engine.models import validate_node_params


# ── safe_arithmetic_eval ──
class TestSafeArithmetic:
    def test_add_mul_precedence(self):
        assert U.safe_arithmetic_eval("2 + 3 * 4", {"a": 0}) == 14

    def test_parens(self):
        assert U.safe_arithmetic_eval("(2 + 3) * 4", {"a": 0}) == 20

    def test_unary_minus(self):
        assert U.safe_arithmetic_eval("-5 + 2", {"a": 0}) == -3

    def test_column_lookup(self):
        assert U.safe_arithmetic_eval("a + b", {"a": 10, "b": 5}) == 15

    def test_div_zero_raises(self):
        with pytest.raises(ZeroDivisionError):
            U.safe_arithmetic_eval("a / 0", {"a": 1})

    def test_unknown_column_raises(self):
        with pytest.raises(ValueError):
            U.safe_arithmetic_eval("a + z", {"a": 1})

    def test_forbidden_token_rejected(self):
        with pytest.raises(ValueError):
            U.safe_arithmetic_eval("a ** 2", {"a": 1})

    def test_no_function_calls(self):
        with pytest.raises(ValueError):
            U.safe_arithmetic_eval("abs(a)", {"a": 1})


# ── FlowGraph ──
class TestFlowGraph:
    def test_valid_parse(self):
        g = G.FlowGraph.from_dict({
            "nodes": [
                {"id": "s", "type": "source", "params": {}},
                {"id": "v", "type": "visualize", "params": {}},
            ],
            "edges": [{"from": "s", "to": "v"}],
        })
        assert g.topo_sort() == ["s", "v"]

    def test_duplicate_id_rejected(self):
        with pytest.raises(ValueError):
            G.FlowGraph.from_dict({
                "nodes": [
                    {"id": "s", "type": "source", "params": {}},
                    {"id": "s", "type": "source", "params": {}},
                ],
                "edges": [],
            })

    def test_unknown_type_rejected(self):
        with pytest.raises(ValueError):
            G.FlowGraph.from_dict({"nodes": [{"id": "x", "type": "bogus", "params": {}}], "edges": []})

    def test_edge_to_missing_node_rejected(self):
        with pytest.raises(ValueError):
            G.FlowGraph.from_dict({
                "nodes": [{"id": "s", "type": "source", "params": {}}],
                "edges": [{"from": "s", "to": "ghost"}],
            })

    def test_cycle_detection(self):
        g = G.FlowGraph.from_dict({
            "nodes": [
                {"id": "a", "type": "transform", "params": {}},
                {"id": "b", "type": "transform", "params": {}},
            ],
            "edges": [{"from": "a", "to": "b"}, {"from": "b", "to": "a"}],
        })
        assert g.detect_cycle() is True

    def test_dag_no_cycle(self):
        g = G.FlowGraph.from_dict({
            "nodes": [
                {"id": "s", "type": "source", "params": {}},
                {"id": "a", "type": "aggregate", "params": {}},
                {"id": "v", "type": "visualize", "params": {}},
            ],
            "edges": [{"from": "s", "to": "a"}, {"from": "a", "to": "v"}],
        })
        assert g.detect_cycle() is False


# ── param validators ──
class TestParamValidators:
    def test_source_ok(self):
        validate_node_params("s", "source", {"source_mode": "table", "table": "fact_x"})

    def test_source_missing_table(self):
        with pytest.raises(ValueError):
            validate_node_params("s", "source", {"source_mode": "table"})

    def test_aggregate_requires_group_and_measures(self):
        with pytest.raises(ValueError):
            validate_node_params("a", "aggregate", {"group_by": [], "measures": []})

    def test_aggregate_ok(self):
        validate_node_params("a", "aggregate", {
            "group_by": ["team"], "measures": [{"agg": "sum", "field": "pts", "alias": "t"}]
        })

    def test_transform_derived_requires_name_expr(self):
        with pytest.raises(ValueError):
            validate_node_params("t", "transform", {"derived": [{"name": "x"}]})

    def test_visualize_requires_y_fields(self):
        with pytest.raises(ValueError):
            validate_node_params("v", "visualize", {"viz_type": "bar"})


# ── run_flow pre-validation ──
class TestRunFlowValidation:
    def test_cycle_raises(self):
        with pytest.raises(V.FlowValidationError):
            ab_service.run_flow({
                "nodes": [
                    {"id": "a", "type": "transform", "params": {}},
                    {"id": "b", "type": "transform", "params": {}},
                ],
                "edges": [{"from": "a", "to": "b"}, {"from": "b", "to": "a"}],
            })

    def test_visualize_without_upstream_raises(self):
        with pytest.raises(V.FlowValidationError):
            ab_service.run_flow({
                "nodes": [{"id": "v", "type": "visualize", "params": {"viz_type": "table", "y_fields": ["x"]}}],
                "edges": [],
            })

    def test_non_source_without_upstream_raises(self):
        with pytest.raises(V.FlowValidationError):
            ab_service.run_flow({
                "nodes": [{"id": "f", "type": "filter", "params": {"logic": "AND", "conditions": []}}],
                "edges": [],
            })


# ── executors on in-memory tables ──
def _mk_table(columns, rows):
    return U.build_table([{"name": c, "type": "text"} for c in columns], rows)


class TestExecutors:
    def test_filter_numeric(self):
        t = _mk_table(["pts", "team"], [{"pts": 30, "team": "A"}, {"pts": 10, "team": "B"}])
        out = execute_filter(t, {"logic": "AND", "conditions": [{"field": "pts", "op": ">", "value": 20}]})
        assert len(out["rows"]) == 1
        assert out["rows"][0]["team"] == "A"

    def test_filter_like(self):
        t = _mk_table(["team"], [{"team": "Lakers"}, {"team": "Celtics"}])
        out = execute_filter(t, {"logic": "AND", "conditions": [{"field": "team", "op": "like", "value": "ake"}]})
        assert len(out["rows"]) == 1

    def test_aggregate_sum_count(self):
        t = _mk_table(["team", "pts"], [
            {"team": "A", "pts": 10}, {"team": "A", "pts": 20}, {"team": "B", "pts": 5}])
        out = execute_aggregate(t, {"group_by": ["team"], "measures": [
            {"agg": "sum", "field": "pts", "alias": "tot"},
            {"agg": "count", "field": None, "alias": "n"},
        ]})
        by_team = {r["team"]: r for r in out["rows"]}
        assert by_team["A"]["tot"] == 30
        assert by_team["A"]["n"] == 2

    def test_transform_derived_and_sort(self):
        t = _mk_table(["a", "b"], [{"a": 1, "b": 2}, {"a": 3, "b": 4}])
        out = execute_transform(t, {
            "sort": {"field": "a", "order": "desc"},
            "top_n": None,
            "derived": [{"name": "c", "expr": "a + b"}],
        })
        assert out["rows"][0]["a"] == 3
        assert out["rows"][0]["c"] == 7
        assert "c" in [c["name"] for c in out["columns"]]


# ── end-to-end against live data ──
@needs_db
class TestRunFlowLive:
    def test_source_to_visualize(self):
        from backend.services.analytics_builder_engine import ab_queries as Q
        tables = [t["name"] for t in Q.introspect_tables()]
        assert tables, "no analytic tables exposed to source node"
        table = tables[0]
        cols = Q.get_table_columns(table)
        numeric = [c["name"] for c in cols if c["type"] in ("int", "float")]

        flow = {
            "nodes": [
                {"id": "s", "type": "source", "params": {"source_mode": "table", "table": table, "limit": 50}},
            ],
            "edges": [],
        }
        if len(numeric) >= 2:
            flow["nodes"].append({
                "id": "t", "type": "transform",
                "params": {"sort": None, "top_n": None,
                           "derived": [{"name": "ab_derived", "expr": f"{numeric[0]} + {numeric[1]}"}]},
            })
            flow["nodes"].append({
                "id": "v", "type": "visualize",
                "params": {"viz_type": "table", "title": "test", "x_field": "", "y_fields": ["ab_derived"]},
            })
            flow["edges"] = [{"from": "s", "to": "t"}, {"from": "t", "to": "v"}]
        else:
            flow["nodes"].append({
                "id": "v", "type": "visualize",
                "params": {"viz_type": "table", "title": "test", "x_field": "", "y_fields": []},
            })
            flow["edges"] = [{"from": "s", "to": "v"}]

        result = ab_service.run_flow(flow, workspace_id=None)
        assert result["node_status"].get("s") == "ok"
        assert result["node_status"].get("v") == "ok"
        assert any(v["node_id"] == "v" for v in result["viz_results"])
        assert result["table_count"] >= 1

    def test_dataset_mode_unsupported_error(self):
        result = ab_service.run_flow({
            "nodes": [{"id": "s", "type": "source", "params": {"source_mode": "workspace_dataset", "dataset_id": 1}}],
            "edges": [],
        }, workspace_id=1)
        # source has no upstream, runs directly and should error (deferred feature)
        assert result["node_status"].get("s") == "error"
        assert any("P1" in e["message"] for e in result["errors"])
