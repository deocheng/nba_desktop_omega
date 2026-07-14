"""NBACore v8.3.2 — Analytics Builder node param validators.

Declarative per-node-type param schema + ``validate_node_params``. This is the
single place that knows "what a valid source/filter/aggregate/transform/visualize
param block looks like". Field-vs-upstream-column checks are deferred to the
executors (the upstream columns are only known at run time), so here we only
validate *static* shape + enum whitelists (v8 §6 + architecture T6).
"""
from __future__ import annotations

from typing import Any

from backend.services.analytics_builder_engine import ab_constants as C


class ParamValidationError(ValueError):
    """Raised when a node's params block fails static validation."""


def _require(node_id: str, cond: bool, msg: str) -> None:
    if not cond:
        raise ParamValidationError(f"节点 {node_id}：{msg}")


def validate_source(node_id: str, params: dict) -> None:
    mode = params.get("source_mode", C.SOURCE_MODE_TABLE)
    _require(node_id, mode in (C.SOURCE_MODE_TABLE, C.SOURCE_MODE_DATASET),
             f"未知 source_mode {mode!r}（允许: table / workspace_dataset）")
    if mode == C.SOURCE_MODE_TABLE:
        _require(node_id, bool(params.get("table")),
                 "source_mode=table 时必须选择 table")
    else:
        _require(node_id, params.get("dataset_id") is not None,
                 "source_mode=workspace_dataset 时必须提供 dataset_id")


def validate_filter(node_id: str, params: dict) -> None:
    logic = params.get("logic", "AND")
    _require(node_id, logic in ("AND", "OR"), f"logic 必须是 AND/OR，得到 {logic!r}")
    conditions = params.get("conditions")
    _require(node_id, isinstance(conditions, list), "conditions 必须是数组")
    for i, c in enumerate(conditions):
        _require(node_id, isinstance(c, dict), f"conditions[{i}] 必须是对象")
        field = c.get("field")
        op = c.get("op")
        _require(node_id, bool(field), f"conditions[{i}] 缺少 field")
        _require(node_id, op in C.FILTER_OPS,
                 f"conditions[{i}] 未知操作符 {op!r}（允许: {', '.join(C.FILTER_OPS)}）")
        if op == "in":
            _require(node_id, isinstance(c.get("value"), (list, tuple)),
                     f"conditions[{i}] op=in 时 value 必须是数组")
        else:
            _require(node_id, "value" in c, f"conditions[{i}] 缺少 value")


def validate_aggregate(node_id: str, params: dict) -> None:
    group_by = params.get("group_by")
    _require(node_id, isinstance(group_by, list) and len(group_by) > 0,
             "aggregate 的 group_by 必须是非空数组")
    measures = params.get("measures")
    _require(node_id, isinstance(measures, list) and len(measures) > 0,
             "aggregate 的 measures 必须是非空数组")
    aliases: set[str] = set()
    for i, m in enumerate(measures):
        _require(node_id, isinstance(m, dict), f"measures[{i}] 必须是对象")
        agg = m.get("agg")
        _require(node_id, agg in C.AGG_FUNCTIONS,
                 f"measures[{i}] 未知聚合 {agg!r}（允许: {', '.join(C.AGG_FUNCTIONS)}）")
        alias = m.get("alias")
        _require(node_id, bool(alias), f"measures[{i}] 缺少 alias")
        _require(node_id, alias not in aliases, f"measures[{i}] alias 重复: {alias}")
        aliases.add(alias)
        if agg != C.AGG_COUNT:
            _require(node_id, bool(m.get("field")),
                     f"measures[{i}] agg={agg} 需要提供 field")


def validate_transform(node_id: str, params: dict) -> None:
    sort = params.get("sort")
    if sort is not None:
        _require(node_id, isinstance(sort, dict), "sort 必须是对象")
        _require(node_id, bool(sort.get("field")), "sort 缺少 field")
        _require(node_id, sort.get("order") in ("asc", "desc"),
                 f"sort.order 必须是 asc/desc，得到 {sort.get('order')!r}")
    top_n = params.get("top_n")
    if top_n is not None:
        _require(node_id, isinstance(top_n, int) and top_n > 0,
                 f"top_n 必须是正整数，得到 {top_n!r}")
    derived = params.get("derived")
    _require(node_id, isinstance(derived, list), "derived 必须是数组")
    names: set[str] = set()
    for i, d in enumerate(derived):
        _require(node_id, isinstance(d, dict), f"derived[{i}] 必须是对象")
        _require(node_id, bool(d.get("name")), f"derived[{i}] 缺少 name")
        _require(node_id, bool(d.get("expr")), f"derived[{i}] 缺少 expr")
        _require(node_id, d["name"] not in names, f"derived[{i}] name 重复: {d['name']}")
        names.add(d["name"])


def validate_visualize(node_id: str, params: dict) -> None:
    viz = params.get("viz_type")
    _require(node_id, viz in C.VIZ_TYPES,
             f"未知 viz_type {viz!r}（允许: {', '.join(C.VIZ_TYPES)}）")
    y_fields = params.get("y_fields")
    _require(node_id, isinstance(y_fields, list) and len(y_fields) > 0,
             "visualize 的 y_fields 必须是非空数组")


_VALIDATORS = {
    "source": validate_source,
    "filter": validate_filter,
    "aggregate": validate_aggregate,
    "transform": validate_transform,
    "visualize": validate_visualize,
}


def validate_node_params(node_id: str, node_type: str, params: dict) -> None:
    """Validate a node's params block statically. Raises ``ParamValidationError``."""
    validator = _VALIDATORS.get(node_type)
    if validator is None:
        raise ParamValidationError(f"节点 {node_id}：未知类型 {node_type!r}")
    validator(node_id, params or {})


def get_param_validators() -> dict[str, Any]:
    """Expose the validator registry (used by unit tests)."""
    return dict(_VALIDATORS)
