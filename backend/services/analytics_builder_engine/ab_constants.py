"""NBACore v8.3.2 — Analytics Builder engine constants (single source of truth).

This module is the ONE place node type enums, aggregation/visualization
whitelists, filter operators, and the row limit are defined. The frontend
consumes these values via the ``/meta`` endpoint (or copies them from here) so
there is never a second copy of the magic strings (v8 §7 shared-knowledge #3).

No SQL, no computation, no DB access here.
"""
from __future__ import annotations

# ── Node types (the ONLY truth for "what kinds of nodes exist") ──
# P0 = exactly these five. Derived-metric (P1) is intentionally absent.
NODE_TYPES: tuple[str, ...] = ("source", "filter", "aggregate", "transform", "visualize")

# Port model: P0 is strictly single-input / single-output.
PORT_IN = "in"
PORT_OUT = "out"

# Per-type accent color (mirrors the CSS data-type rules on the frontend).
# Purely cosmetic, but defined here so the frontend can pull a single source.
NODE_COLORS: dict[str, str] = {
    "source": "#3b82f6",      # blue
    "filter": "#94a3b8",       # gray
    "aggregate": "#10b981",    # green
    "transform": "#8b5cf6",    # purple
    "visualize": "#f97316",    # orange
}

# ── Aggregation functions (white-list only) ──
AGG_FUNCTIONS: tuple[str, ...] = ("sum", "avg", "count", "max", "min")

# count ignores the source field value (uses *); exposed for the frontend
# so it can grey-out the field picker when agg == "count".
AGG_COUNT = "count"

# ── Visualization types (P0: table / line / bar; radar is P1) ──
VIZ_TYPES: tuple[str, ...] = ("table", "line", "bar")

# ── Filter operators (white-list) ──
FILTER_OPS: tuple[str, ...] = ("=", "!=", ">", "<", ">=", "<=", "in", "like")

# Mapping of filter op -> human label (frontend dropdowns).
FILTER_OP_LABELS: dict[str, str] = {
    "=": "等于",
    "!=": "不等于",
    ">": "大于",
    "<": "小于",
    ">=": "大于等于",
    "<=": "小于等于",
    "in": "属于(多选)",
    "like": "包含(模糊)",
}

# ── Row limit (single definition, v8 §7 #7) ──
ROW_LIMIT: int = 5000

# ── Table introspection white-list (v8 §8 O2) ──
# Only analytic fact_/dim_ tables are exposed to the source node. Backup / audit
# tables (suffix ``_bak``) are excluded.
INTROSPECTION_PREFIXES: tuple[str, ...] = ("fact_", "dim_")
INTROSPECTION_EXCLUDE_SUBSTR: tuple[str, ...] = ("_bak",)

# Logical source modes (P0 only supports "table"; workspace_dataset is P1).
SOURCE_MODE_TABLE = "table"
SOURCE_MODE_DATASET = "workspace_dataset"

# Error message returned when a stored flow uses the unsupported dataset mode.
ERROR_DATASET_MODE_UNSUPPORTED = "workspace 数据集模式 P1 未支持"
