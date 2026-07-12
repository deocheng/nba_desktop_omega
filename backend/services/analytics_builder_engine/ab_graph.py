"""NBACore v8.3.2 — Flow graph model + Kahn topological sort + cycle detection.

Pure data-structure logic (no DB, no SQL). ``FlowGraph.from_dict`` validates the
shape of the incoming JSON; ``topo_sort`` returns a node ordering (Kahn's
algorithm) and ``detect_cycle`` is the engine-side backstop for the
frontend's real-time cycle guard (v8 §6: every boundary is defended twice).
"""
from __future__ import annotations

from typing import Any

from backend.services.analytics_builder_engine import ab_constants as C


class FlowGraph:
    """Parsed representation of a node/edge analysis graph."""

    def __init__(
        self,
        nodes: list[dict],
        edges: list[dict],
        version: str = "1",
        workspace_id: int | None = None,
    ) -> None:
        self.version = version
        self.workspace_id = workspace_id
        self.nodes: list[dict] = nodes
        self.edges: list[dict] = edges
        self._node_by_id: dict[str, dict] = {n["id"]: n for n in nodes}

    # ── Construction ──
    @classmethod
    def from_dict(cls, data: dict) -> "FlowGraph":
        """Build a FlowGraph from the API JSON dict, with structural checks."""
        if not isinstance(data, dict):
            raise ValueError("flow 必须是对象")
        nodes = data.get("nodes")
        edges = data.get("edges")
        if not isinstance(nodes, list) or not nodes:
            raise ValueError("flow.nodes 必须是非空数组")
        if not isinstance(edges, list):
            raise ValueError("flow.edges 必须是数组")

        seen: set[str] = set()
        for n in nodes:
            if not isinstance(n, dict):
                raise ValueError("节点必须是对象")
            nid = n.get("id")
            if not nid:
                raise ValueError("节点缺少 id")
            if nid in seen:
                raise ValueError(f"节点 id 重复: {nid}")
            seen.add(nid)
            ntype = n.get("type")
            if ntype not in C.NODE_TYPES:
                raise ValueError(
                    f"节点 {nid}: 未知类型 {ntype!r}（允许: {', '.join(C.NODE_TYPES)}）"
                )
            if "params" not in n or not isinstance(n["params"], dict):
                n["params"] = n.get("params") or {}

        for e in edges:
            if not isinstance(e, dict):
                raise ValueError("边必须是对象")
            frm = e.get("from")
            to = e.get("to")
            if not frm or not to:
                raise ValueError("边缺少 from/to")
            if frm not in seen:
                raise ValueError(f"边引用了不存在的源节点: {frm}")
            if to not in seen:
                raise ValueError(f"边引用了不存在的目标节点: {to}")

        return cls(
            nodes=list(nodes),
            edges=list(edges),
            version=str(data.get("version", "1")),
            workspace_id=data.get("workspace_id"),
        )

    # ── Topology ──
    def incoming(self, node_id: str) -> list[str]:
        """Source node ids feeding into ``node_id`` (its single upstream)."""
        return [e["from"] for e in self.edges if e["to"] == node_id]

    def outgoing(self, node_id: str) -> list[str]:
        return [e["to"] for e in self.edges if e["from"] == node_id]

    def topo_sort(self) -> list[str]:
        """Kahn topological sort. Returns ordered node ids.

        Raises ``ValueError`` if a cycle is present (engine backstop).
        """
        indeg = {n["id"]: 0 for n in self.nodes}
        for e in self.edges:
            indeg[e["to"]] = indeg.get(e["to"], 0) + 1

        from collections import deque

        queue = deque([nid for nid, d in indeg.items() if d == 0])
        order: list[str] = []
        while queue:
            nid = queue.popleft()
            order.append(nid)
            for down in self.outgoing(nid):
                indeg[down] -= 1
                if indeg[down] == 0:
                    queue.append(down)

        if len(order) != len(self.nodes):
            remaining = [n["id"] for n in self.nodes if n["id"] not in order]
            raise ValueError(f"检测到环(cycle)，无法拓扑排序，涉及节点: {remaining}")
        return order

    def detect_cycle(self) -> bool:
        """Return True if the graph contains a cycle (lightweight probe)."""
        try:
            self.topo_sort()
            return False
        except ValueError:
            return True

    def get_node(self, node_id: str) -> dict | None:
        return self._node_by_id.get(node_id)
