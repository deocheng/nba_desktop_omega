"""NBACore v8.3.2 — Analytics Builder engine facade.

``run_flow`` is the single entry point used by the router:
    validate -> topo-sort -> execute node-by-node -> collect results.

Per-node execution errors are caught and surfaced as ``node_status`` /
``errors`` rather than aborting the whole graph; downstream nodes that depend
on a failed upstream are marked ``skipped``.
"""
from __future__ import annotations

from typing import Any

from backend.services.analytics_builder_engine import ab_constants as C
from backend.services.analytics_builder_engine import ab_graph as G
from backend.services.analytics_builder_engine import ab_queries as Q
from backend.services.analytics_builder_engine.ab_executors import execute_node
from backend.services.analytics_builder_engine.ab_validation import validate_flow


def run_flow(flow: dict, workspace_id: int | None = None) -> dict:
    """Execute a FlowGraph dict. Returns a result dict (never raises for
    execution errors; raises ``ValueError`` only for pre-run validation)."""
    graph = G.FlowGraph.from_dict(flow)
    validate_flow(graph)  # raises on structural problems

    ctx: dict[str, Any] = {"workspace_id": workspace_id}
    order = graph.topo_sort()

    tables: dict[str, dict] = {}          # node_id -> Table
    viz_results: list[dict] = []
    node_status: dict[str, str] = {}
    errors: list[dict] = []

    for nid in order:
        node = graph.get_node(nid)
        upstream_ids = graph.incoming(nid)
        upstream_id = upstream_ids[0] if upstream_ids else None
        upstream_table = tables.get(upstream_id) if upstream_id else None

        # a node whose only upstream failed/skipped cannot run
        if upstream_id is not None and node_status.get(upstream_id) != "ok":
            node_status[nid] = "skipped"
            errors.append({
                "node_id": nid,
                "message": f"节点 {nid}：上游节点 {upstream_id} 未成功执行，已跳过",
            })
            continue

        try:
            table, viz = execute_node(node, upstream_table, ctx)
            if viz is not None:
                viz_results.append(viz)
            else:
                tables[nid] = table
            node_status[nid] = "ok"
        except Exception as exc:  # noqa: BLE001 — per-node isolation
            node_status[nid] = "error"
            errors.append({"node_id": nid, "message": f"节点 {nid}：{exc}"})

    return {
        "viz_results": viz_results,
        "node_status": node_status,
        "errors": errors,
        "table_count": len(tables),
    }


def get_meta(workspace_id: int | None = None) -> dict:
    """Enumerate metadata for the builder UI (tables, functions, viz types)."""
    return {
        "node_types": list(C.NODE_TYPES),
        "tables": Q.introspect_tables(),
        "agg_functions": list(C.AGG_FUNCTIONS),
        "viz_types": list(C.VIZ_TYPES),
        "filter_ops": [
            {"op": op, "label": C.FILTER_OP_LABELS.get(op, op)}
            for op in C.FILTER_OPS
        ],
        "source_modes": [C.SOURCE_MODE_TABLE, C.SOURCE_MODE_DATASET],
        "row_limit": C.ROW_LIMIT,
        "workspace_datasets": Q.get_workspace_datasets(workspace_id or 0),
    }
