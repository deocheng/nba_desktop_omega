"""NBACore v8.3.2 — Pre-run flow validation (engine backstop).

Called by ``ab_service.run_flow`` *before* topology + execution. Raises
``ValueError`` with a Chinese, node-located message on any structural problem:
cycle, a ``visualize`` node without an upstream, or invalid per-node params.

Field-vs-upstream-column checks are intentionally NOT done here (the upstream
columns are only known at execution time) — those are enforced inside the
executors. This keeps pre-run validation cheap and deterministic.
"""
from __future__ import annotations

from backend.services.analytics_builder_engine import ab_graph as G
from backend.services.analytics_builder_engine.models import validate_node_params


class FlowValidationError(ValueError):
    """Raised when a FlowGraph fails pre-run validation."""


def validate_flow(graph: "G.FlowGraph") -> None:
    """Validate a parsed FlowGraph. Raises ``FlowValidationError`` on failure."""
    if graph.detect_cycle():
        raise FlowValidationError("存在环(cycle)，分析流必须是 DAG")

    for node in graph.nodes:
        nid = node.get("id")
        ntype = node.get("type")
        # static param shape + enum whitelist
        validate_node_params(nid, ntype, node.get("params", {}))

        # visualize must have an upstream
        if ntype == "visualize":
            if not graph.incoming(nid):
                raise FlowValidationError(f"节点 {nid}：可视化节点必须有上游输入")

        # non-source nodes must have exactly one upstream (P0 single-in)
        if ntype != "source":
            if len(graph.incoming(nid)) == 0:
                raise FlowValidationError(f"节点 {nid}：{ntype} 节点缺少上游输入")
