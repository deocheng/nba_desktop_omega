"""能力目录（Manifest）加载与校验。

Manifest 是编排顺序与参数的**唯一来源**；加载器把「相对路径 / 状态 / 写盘权限」
变成可执行断言，避免未经签核的步骤被误跑，也避免 script 逃出代码根。

设计见 docs/unified-desktop-app-architecture.md §3.1。
"""
from __future__ import annotations

import json
from pathlib import Path, PurePosixPath

from common.nba_paths import TACTICS_CODE_ROOT, repo_file, tactics_code_file

KINDS = frozenset({"probe", "pipeline"})
STATUSES = frozenset({"active", "planned"})
STEP_FIELDS = (
    "id", "kind", "status", "title", "description", "script", "args",
    "params", "inputs", "outputs", "requires", "writes_data", "timeout_sec",
)


class ManifestError(ValueError):
    """Manifest 结构或安全约束不合法。"""


def manifest_path() -> Path:
    """Manifest 在仓库内的位置；frozen 下由 spec datas 放到同一相对位置。"""
    return repo_file("studio", "manifest.json")


def _check_script(script: object, step_id: str, status: str) -> None:
    if script is None:
        if status == "active":
            raise ManifestError(f"{step_id}: active 步骤必须有 script")
        return
    if not isinstance(script, str) or not script.strip():
        raise ManifestError(f"{step_id}: script 必须是非空字符串或 null")
    parts = PurePosixPath(script).parts
    if PurePosixPath(script).is_absolute() or ".." in parts:
        raise ManifestError(f"{step_id}: script 必须是代码根内的相对路径")
    if not script.endswith(".py"):
        raise ManifestError(f"{step_id}: script 必须是 .py 文件")
    resolved = tactics_code_file(*parts).resolve()
    root = TACTICS_CODE_ROOT.resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ManifestError(f"{step_id}: script 逃出代码根") from exc


def validate(data: object) -> dict:
    """校验整份 Manifest，返回原对象；任何不合法都抛 ManifestError。"""
    if not isinstance(data, dict):
        raise ManifestError("Manifest 顶层必须是对象")
    if data.get("schema_version") != 1:
        raise ManifestError("不支持的 schema_version（当前仅 1）")

    steps = data.get("steps")
    if not isinstance(steps, list) or not steps:
        raise ManifestError("steps 必须是非空数组")

    seen: set[str] = set()
    for step in steps:
        if not isinstance(step, dict):
            raise ManifestError("每个 step 必须是对象")
        missing = [k for k in STEP_FIELDS if k not in step]
        if missing:
            raise ManifestError(f"step 缺字段: {missing}")
        sid = step["id"]
        if not isinstance(sid, str) or not sid:
            raise ManifestError("step.id 必须是非空字符串")
        if sid in seen:
            raise ManifestError(f"step.id 重复: {sid}")
        seen.add(sid)
        if step["kind"] not in KINDS:
            raise ManifestError(f"{sid}: kind 必须是 {sorted(KINDS)}")
        if step["status"] not in STATUSES:
            raise ManifestError(f"{sid}: status 必须是 {sorted(STATUSES)}")
        if not isinstance(step["args"], list) or not all(isinstance(a, str) for a in step["args"]):
            raise ManifestError(f"{sid}: args 必须是字符串数组")
        for key in ("params", "inputs", "outputs", "requires"):
            if not isinstance(step[key], list):
                raise ManifestError(f"{sid}: {key} 必须是数组")
        if not isinstance(step["writes_data"], bool):
            raise ManifestError(f"{sid}: writes_data 必须是布尔")
        if not isinstance(step["timeout_sec"], int) or step["timeout_sec"] <= 0:
            raise ManifestError(f"{sid}: timeout_sec 必须是正整数")
        _check_script(step["script"], sid, step["status"])
        # P0 不变量：真正能跑的步骤只能是只读 probe。
        if step["status"] == "active":
            if step["kind"] != "probe" or step["writes_data"]:
                raise ManifestError(f"{sid}: P0 只允许 active 的只读 probe 步骤")

    pipelines = data.get("pipelines", [])
    if not isinstance(pipelines, list):
        raise ManifestError("pipelines 必须是数组")
    pipe_ids: set[str] = set()
    for pipe in pipelines:
        if not isinstance(pipe, dict):
            raise ManifestError("每个 pipeline 必须是对象")
        pid = pipe.get("id")
        if not isinstance(pid, str) or not pid:
            raise ManifestError("pipeline.id 必须是非空字符串")
        if pid in pipe_ids:
            raise ManifestError(f"pipeline.id 重复: {pid}")
        pipe_ids.add(pid)
        if pipe.get("status") not in STATUSES:
            raise ManifestError(f"{pid}: status 必须是 {sorted(STATUSES)}")
        chain = pipe.get("steps")
        if not isinstance(chain, list) or not all(isinstance(s, str) for s in chain):
            raise ManifestError(f"{pid}: steps 必须是 step id 数组")
        unknown = [s for s in chain if s not in seen]
        if unknown:
            raise ManifestError(f"{pid}: 引用了不存在的 step: {unknown}")
        if len(chain) != len(set(chain)):
            raise ManifestError(f"{pid}: steps 重复（DAG 不允许重复节点）")
    return data


def load_manifest(path: Path | str | None = None) -> dict:
    """读取并校验 Manifest。frozen 下走 repo_file() 指向解包目录。"""
    p = Path(path) if path is not None else manifest_path()
    if not p.is_file():
        raise ManifestError(f"能力目录不存在: {p}")
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ManifestError(f"能力目录读取失败: {exc}") from exc
    return validate(data)


def step_by_id(data: dict, step_id: str) -> dict | None:
    """按 id 查 step；找不到返回 None（由路由层转 404 语义）。"""
    return next((s for s in data["steps"] if s["id"] == step_id), None)


def script_path(step: dict) -> Path:
    """把 step.script 解析为代码根内的绝对路径。"""
    _check_script(step["script"], step["id"], step["status"])
    return tactics_code_file(*PurePosixPath(step["script"]).parts)
