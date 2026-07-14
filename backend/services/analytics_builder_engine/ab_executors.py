"""NBACore v8.3.2 — Analytics Builder node executors (the 5 P0 node types).

Each executor is a pure-Python operation on an in-memory ``Table`` (except
``source`` which reads via ``ab_queries``). ``execute_node`` dispatches by node
type and returns either a ``Table`` (for the data nodes) or a ``VizResult`` dict
(for the ``visualize`` terminal node). All exceptions are expected to be caught
by the orchestrator (``ab_service.run_flow``) and turned into per-node errors.

No SQL here beyond ``ab_queries`` (which funnels through ``db.batch_query``);
no eval/exec — derived columns go through ``ab_utils.safe_arithmetic_eval``.
"""
from __future__ import annotations

from typing import Any

from backend.core import db
from backend.services.analytics_builder_engine import ab_constants as C
from backend.services.analytics_builder_engine import ab_queries as Q
from backend.services.analytics_builder_engine.ab_utils import (
    build_table,
    infer_type,
    safe_arithmetic_eval,
    truncate,
)


# ── helpers ──
def _to_number(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _compare(op: str, cell: Any, value: Any) -> bool:
    if op == "=":
        return cell == value
    if op == "!=":
        return cell != value
    if op == "in":
        seq = value if isinstance(value, (list, tuple, set)) else [value]
        return cell in seq
    if op == "like":
        return str(value).lower() in str(cell).lower()
    c = _to_number(cell)
    v = _to_number(value)
    if c is None or v is None:
        return False
    if op == ">":
        return c > v
    if op == "<":
        return c < v
    if op == ">=":
        return c >= v
    if op == "<=":
        return c <= v
    return False


# ── source ──
def execute_source(params: dict, ctx: dict) -> dict:
    """Read one whitelisted table; return a Table (columns + rows)."""
    mode = params.get("source_mode", C.SOURCE_MODE_TABLE)
    if mode == C.SOURCE_MODE_DATASET:
        raise ValueError(C.ERROR_DATASET_MODE_UNSUPPORTED)
    table = params.get("table")
    if not table:
        raise ValueError("未选择表 (table)")
    if table not in Q.get_allowed_tables():
        raise ValueError(f"表 {table!r} 不在允许的分析表白名单内")

    cols = Q.get_table_columns(table)
    col_names = {c["name"] for c in cols}
    has_season = "season" in col_names

    sql, sql_params = Q.build_source_sql(
        table=table,
        season_from=params.get("season_from"),
        season_to=params.get("season_to"),
        limit=int(params.get("limit", C.ROW_LIMIT)),
        has_season_col=has_season,
    )
    rows = db.batch_query(sql, sql_params)
    out = build_table(cols, [dict(r) for r in rows])
    return truncate(out)


# ── filter ──
def execute_filter(table: dict, params: dict) -> dict:
    logic = params.get("logic", "AND")
    conditions = params.get("conditions", [])
    col_names = {c["name"] for c in table.get("columns", [])}

    for i, c in enumerate(conditions):
        if c.get("field") not in col_names:
            raise ValueError(f"过滤条件[{i}] 未知字段 {c.get('field')!r}")

    def match_row(row: dict) -> bool:
        results = [_compare(c["op"], row.get(c["field"]), c.get("value"))
                   for c in conditions]
        if not results:
            return True
        return all(results) if logic == "AND" else any(results)

    kept = [r for r in table.get("rows", []) if match_row(r)]
    out = build_table(table.get("columns", []), kept)
    return truncate(out)


# ── aggregate ──
def execute_aggregate(table: dict, params: dict) -> dict:
    group_by = params.get("group_by", [])
    measures = params.get("measures", [])
    col_types = {c["name"]: c["type"] for c in table.get("columns", [])}
    col_names = set(col_types)

    for g in group_by:
        if g not in col_names:
            raise ValueError(f"group_by 未知字段 {g!r}")
    for m in measures:
        if m["agg"] != C.AGG_COUNT and m["field"] not in col_names:
            raise ValueError(f"聚合字段 {m['field']!r} 不存在于上游表")

    groups: dict[tuple, list[dict]] = {}
    for row in table.get("rows", []):
        key = tuple(row.get(g) for g in group_by)
        groups.setdefault(key, []).append(row)

    out_rows: list[dict] = []
    for key, grp in groups.items():
        out = {g: key[i] for i, g in enumerate(group_by)}
        for m in measures:
            agg = m["agg"]
            alias = m["alias"]
            if agg == "count":
                out[alias] = len(grp)
            else:
                vals = [_to_number(r.get(m["field"]))
                        for r in grp]
                vals = [v for v in vals if v is not None]
                if agg == "sum":
                    out[alias] = sum(vals) if vals else 0.0
                elif agg == "avg":
                    out[alias] = (sum(vals) / len(vals)) if vals else 0.0
                elif agg == "max":
                    out[alias] = max(vals) if vals else None
                elif agg == "min":
                    out[alias] = min(vals) if vals else None
        out_rows.append(out)

    out_cols = [{"name": g, "type": col_types[g]} for g in group_by]
    for m in measures:
        out_cols.append({"name": m["alias"], "type": _measure_type(out_rows, m["alias"])})
    out = build_table(out_cols, out_rows)
    return truncate(out)


def _measure_type(rows: list[dict], alias: str) -> str:
    for r in rows:
        v = r.get(alias)
        if v is not None:
            return infer_type(v)
    return "float"


# ── transform ──
def execute_transform(table: dict, params: dict) -> dict:
    rows = list(table.get("rows", []))
    col_names = {c["name"] for c in table.get("columns", [])}

    sort = params.get("sort")
    if sort:
        field = sort.get("field")
        if field not in col_names:
            raise ValueError(f"排序字段 {field!r} 不存在于上游表")
        order = sort.get("order", "asc")
        rows.sort(key=lambda r: (_to_number(r.get(field)) is None,
                                 _to_number(r.get(field))),
                  reverse=(order == "desc"))

    top_n = params.get("top_n")
    truncated_by_topn = False
    if top_n and isinstance(top_n, int) and top_n > 0 and len(rows) > top_n:
        rows = rows[:top_n]
        truncated_by_topn = True

    derived = params.get("derived", [])
    for d in derived:
        name = d["name"]
        expr = d["expr"]
        for row in rows:
            row[name] = safe_arithmetic_eval(expr, row)

    columns = list(table.get("columns", []))
    for d in derived:
        columns.append({"name": d["name"], "type": _measure_type(rows, d["name"])})

    out = build_table(columns, rows)
    if truncated_by_topn:
        out["truncated"] = True
    return truncate(out)


# ── visualize ──
def execute_visualize(node_id: str, table: dict, params: dict) -> dict:
    """Terminal node: consume the input Table, return a VizResult (not a Table)."""
    return {
        "node_id": node_id,
        "viz_type": params.get("viz_type"),
        "title": params.get("title", ""),
        "x_field": params.get("x_field"),
        "y_fields": params.get("y_fields", []),
        "columns": table.get("columns", []),
        "rows": table.get("rows", []),
        "row_count": table.get("row_count", len(table.get("rows", []))),
    }


# ── registry / dispatch ──
REGISTRY = {
    "source": execute_source,
    "filter": execute_filter,
    "aggregate": execute_aggregate,
    "transform": execute_transform,
}


def execute_node(node: dict, input_table: dict | None, ctx: dict) -> tuple[dict | None, dict | None]:
    """Execute one node. Returns ``(table, viz_result)`` — exactly one is non-None.

    ``table`` is set for data nodes (source/filter/aggregate/transform); ``viz``
    is set for the terminal ``visualize`` node.
    """
    node_type = node["type"]
    params = node.get("params", {}) or {}
    if node_type == "source":
        out = execute_source(params, ctx)
        return out, None
    if node_type == "visualize":
        if input_table is None:
            raise ValueError("可视化节点缺少上游输入")
        viz = execute_visualize(node["id"], input_table, params)
        return None, viz
    if input_table is None:
        raise ValueError(f"{node_type} 节点缺少上游输入")
    out = REGISTRY[node_type](input_table, params)
    return out, None
