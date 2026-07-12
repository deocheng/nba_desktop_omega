"""NBACore v8.3.2 — Analytics Builder engine unit tests (offline).

These tests exercise pure engine logic and never touch a live database:
the only DB-touching executor (``source``) is exercised through monkeypatched
``ab_queries`` / ``core.db`` seams, so the suite runs with ``pytest`` offline.
"""
from __future__ import annotations

import pytest

from backend.core import db
from backend.services.analytics_builder_engine import ab_constants as C
from backend.services.analytics_builder_engine import ab_graph as G
from backend.services.analytics_builder_engine import ab_queries as Q
from backend.services.analytics_builder_engine import ab_utils as U
from backend.services.analytics_builder_engine.ab_executors import (
    execute_aggregate,
    execute_filter,
    execute_source,
    execute_transform,
    execute_visualize,
)
from backend.services.analytics_builder_engine.ab_service import get_meta, run_flow


# ── helpers ──
def _table():
    cols = [{"name": "team", "type": "text"}, {"name": "pts", "type": "int"}]
    rows = [{"team": "A", "pts": 20}, {"team": "A", "pts": 5}, {"team": "B", "pts": 10}]
    return U.build_table(cols, rows)


def _mock_source(monkeypatch, rows, cols=None):
    cols = cols or [{"name": "pts", "type": "int"}]
    monkeypatch.setattr(Q, "get_allowed_tables", lambda: {"fact_pss"})
    monkeypatch.setattr(Q, "get_table_columns", lambda t: cols)
    monkeypatch.setattr(db, "batch_query", lambda sql, params=None: rows)


# ── topology ──
def test_topo_sort_order():
    g = G.FlowGraph.from_dict({
        "nodes": [
            {"id": "n1", "type": "source", "params": {}},
            {"id": "n2", "type": "filter", "params": {}},
            {"id": "n3", "type": "visualize", "params": {}},
        ],
        "edges": [
            {"id": "e1", "from": "n1", "to": "n2"},
            {"id": "e2", "from": "n2", "to": "n3"},
        ],
    })
    order = g.topo_sort()
    assert order.index("n1") < order.index("n2") < order.index("n3")


def test_detect_cycle():
    g = G.FlowGraph.from_dict({
        "nodes": [
            {"id": "n1", "type": "source", "params": {}},
            {"id": "n2", "type": "filter", "params": {}},
        ],
        "edges": [
            {"id": "e1", "from": "n1", "to": "n2"},
            {"id": "e2", "from": "n2", "to": "n1"},
        ],
    })
    assert g.detect_cycle() is True


def test_no_false_cycle():
    g = G.FlowGraph.from_dict({
        "nodes": [{"id": "n1", "type": "source", "params": {}}],
        "edges": [],
    })
    assert g.detect_cycle() is False


# ── executors (in-memory) ──
def test_execute_filter():
    out = execute_filter(
        _table(),
        {"logic": "AND", "conditions": [{"field": "pts", "op": ">", "value": 10}]},
    )
    assert [r["team"] for r in out["rows"]] == ["A"]  # only pts=20


def test_execute_filter_unknown_field():
    with pytest.raises(ValueError):
        execute_filter(
            _table(),
            {"logic": "AND", "conditions": [{"field": "bogus", "op": ">", "value": 1}]},
        )


def test_execute_aggregate():
    out = execute_aggregate(_table(), {
        "group_by": ["team"],
        "measures": [
            {"field": "pts", "agg": "sum", "alias": "pts_sum"},
            {"field": "pts", "agg": "count", "alias": "n"},
        ],
    })
    by_team = {r["team"]: r for r in out["rows"]}
    assert by_team["A"]["pts_sum"] == 25 and by_team["A"]["n"] == 2
    assert by_team["B"]["pts_sum"] == 10 and by_team["B"]["n"] == 1


def test_execute_aggregate_unknown_group_by():
    with pytest.raises(ValueError):
        execute_aggregate(
            _table(),
            {"group_by": ["nope"], "measures": [{"field": "pts", "agg": "sum", "alias": "s"}]},
        )


def test_execute_transform_sort_topn_derived():
    out = execute_transform(_table(), {
        "sort": {"field": "pts", "order": "desc"},
        "top_n": 2,
        "derived": [{"name": "dbl", "expr": "pts * 2"}],
    })
    assert [r["pts"] for r in out["rows"]] == [20, 10]
    assert out["rows"][0]["dbl"] == 40.0
    assert any(c["name"] == "dbl" for c in out["columns"])


def test_execute_visualize():
    viz = execute_visualize("n9", _table(), {
        "viz_type": "bar", "x_field": "team", "y_fields": ["pts"], "title": "t",
    })
    assert viz["node_id"] == "n9"
    assert viz["viz_type"] == "bar"
    assert viz["row_count"] == 3


# ── source (mocked) ──
def test_execute_source(monkeypatch):
    _mock_source(monkeypatch, [{"pts": 1}, {"pts": 2}])
    out = execute_source({"source_mode": "table", "table": "fact_pss", "limit": 10}, {})
    assert out["row_count"] == 2


# ── row truncation ──
def test_truncate_over_limit():
    big = U.build_table(
        [{"name": "x", "type": "int"}], [{"x": i} for i in range(6000)]
    )
    U.truncate(big)
    assert big["truncated"] is True
    assert big["row_count"] == C.ROW_LIMIT
    assert len(big["rows"]) == C.ROW_LIMIT


def test_truncate_under_limit():
    small = U.build_table([{"name": "x", "type": "int"}], [{"x": 1}])
    U.truncate(small)
    assert small["truncated"] is False


# ── safe arithmetic ──
def test_safe_arithmetic_valid():
    assert U.safe_arithmetic_eval("a + b * 2", {"a": 1.0, "b": 3.0}) == 7.0


def test_safe_arithmetic_div_by_zero():
    with pytest.raises(ZeroDivisionError):
        U.safe_arithmetic_eval("a / 0", {"a": 5.0})


def test_safe_arithmetic_unknown_column():
    with pytest.raises(ValueError):
        U.safe_arithmetic_eval("a + unknowncol", {"a": 1.0})


# ── run_flow orchestration (mocked source) ──
def test_run_flow_success(monkeypatch):
    _mock_source(monkeypatch, [{"pts": 20}, {"pts": 5}])
    res = run_flow({
        "nodes": [
            {"id": "n1", "type": "source",
             "params": {"source_mode": "table", "table": "fact_pss", "limit": 50}},
            {"id": "n2", "type": "filter",
             "params": {"logic": "AND", "conditions": [{"field": "pts", "op": ">", "value": 0}]}},
            {"id": "n3", "type": "transform",
             "params": {"derived": [{"name": "dbl", "expr": "pts * 2"}]}},
            {"id": "n4", "type": "visualize",
             "params": {"viz_type": "table", "x_field": "pts", "y_fields": ["pts"]}},
        ],
        "edges": [
            {"id": "e1", "from": "n1", "to": "n2"},
            {"id": "e2", "from": "n2", "to": "n3"},
            {"id": "e3", "from": "n3", "to": "n4"},
        ],
    }, 1)
    assert res["node_status"] == {"n1": "ok", "n2": "ok", "n3": "ok", "n4": "ok"}
    assert len(res["viz_results"]) == 1


def test_run_flow_node_error_and_skip(monkeypatch):
    _mock_source(monkeypatch, [{"pts": 20}, {"pts": 5}])
    res = run_flow({
        "nodes": [
            {"id": "n1", "type": "source",
             "params": {"source_mode": "table", "table": "fact_pss", "limit": 50}},
            {"id": "n2", "type": "filter",
             "params": {"logic": "AND", "conditions": [{"field": "bogus", "op": ">", "value": 0}]}},
            {"id": "n3", "type": "visualize",
             "params": {"viz_type": "table", "x_field": "pts", "y_fields": ["pts"]}},
        ],
        "edges": [
            {"id": "e1", "from": "n1", "to": "n2"},
            {"id": "e2", "from": "n2", "to": "n3"},
        ],
    }, 1)
    assert res["node_status"]["n2"] == "error"
    assert res["node_status"]["n3"] == "skipped"
    assert any(e["node_id"] == "n2" for e in res["errors"])


def test_run_flow_cycle_raises(monkeypatch):
    _mock_source(monkeypatch, [{"pts": 1}])
    with pytest.raises(Exception):
        run_flow({
            "nodes": [
                {"id": "n1", "type": "source",
                 "params": {"source_mode": "table", "table": "fact_pss", "limit": 50}},
                {"id": "n2", "type": "filter",
                 "params": {"logic": "AND", "conditions": [{"field": "pts", "op": ">", "value": 0}]}},
            ],
            "edges": [
                {"id": "e1", "from": "n1", "to": "n2"},
                {"id": "e2", "from": "n2", "to": "n1"},
            ],
        }, 1)


# ── get_meta (mocked introspection, offline) ──
def test_get_meta_offline(monkeypatch):
    monkeypatch.setattr(Q, "introspect_tables", lambda: [])
    monkeypatch.setattr(Q, "get_workspace_datasets", lambda ws: [])
    meta = get_meta(1)
    assert meta["agg_functions"] == list(C.AGG_FUNCTIONS)
    assert meta["viz_types"] == list(C.VIZ_TYPES)
    assert meta["node_types"] == list(C.NODE_TYPES)
    assert meta["row_limit"] == C.ROW_LIMIT
