"""能力目录（Manifest）加载与校验。

Manifest 是编排顺序与参数的**唯一来源**；加载器把「相对路径 / 参数 schema /
状态 / 写盘权限 / 产物声明」变成可执行断言，避免未经签核的步骤被误跑，
也避免 script 逃出代码根、产物逃出 job 隔离目录。

P1 新增：``script_root``（tactics_code | studio_fixtures）、``kind=task``、
参数类型 / choices 校验、``outputs`` 相对 job 目录的 glob 校验。

设计见 docs/unified-desktop-app-architecture.md §3.1。
"""
from __future__ import annotations

import json
from pathlib import Path, PurePosixPath

from common.nba_paths import TACTICS_CODE_ROOT, repo_file

KINDS = frozenset({"probe", "task", "pipeline"})
RUNNABLE_KINDS = frozenset({"probe", "task"})
STATUSES = frozenset({"active", "planned"})
SCRIPT_ROOTS = frozenset({"tactics_code", "studio_fixtures"})
PARAM_TYPES = frozenset({"str", "int", "float", "bool"})
STEP_FIELDS = (
    "id", "kind", "status", "title", "description", "script", "args",
    "params", "inputs", "outputs", "requires", "writes_data", "timeout_sec",
)


class ManifestError(ValueError):
    """Manifest 结构或安全约束不合法。"""


def manifest_path() -> Path:
    """Manifest 在仓库内的位置；frozen 下由 spec datas 放到同一相对位置。"""
    return repo_file("studio", "manifest.json")


def script_root_path(step: dict | None = None) -> Path:
    """按 step.script_root 返回允许放脚本的根（默认战术代码根）。"""
    key = (step or {}).get("script_root", "tactics_code")
    if key not in SCRIPT_ROOTS:
        raise ManifestError(f"未知 script_root: {key}")
    if key == "studio_fixtures":
        return repo_file("studio", "fixtures")
    return TACTICS_CODE_ROOT


def _check_script(step: dict) -> None:
    sid = step["id"]
    script = step["script"]
    if script is None:
        if step["status"] == "active":
            raise ManifestError(f"{sid}: active 步骤必须有 script")
        return
    if not isinstance(script, str) or not script.strip():
        raise ManifestError(f"{sid}: script 必须是非空字符串或 null")
    parts = PurePosixPath(script).parts
    if PurePosixPath(script).is_absolute() or ".." in parts:
        raise ManifestError(f"{sid}: script 必须是根内的相对路径")
    if not script.endswith(".py"):
        raise ManifestError(f"{sid}: script 必须是 .py 文件")
    root = script_root_path(step).resolve()
    try:
        root.joinpath(*parts).resolve().relative_to(root)
    except ValueError as exc:
        raise ManifestError(f"{sid}: script 逃出 {step.get('script_root', 'tactics_code')} 根") from exc


def _check_params(step: dict) -> None:
    sid = step["id"]
    names: set[str] = set()
    for spec in step["params"]:
        if not isinstance(spec, dict):
            raise ManifestError(f"{sid}: params 每项必须是对象")
        name = spec.get("name")
        if not isinstance(name, str) or not name:
            raise ManifestError(f"{sid}: 参数缺 name")
        if name in names:
            raise ManifestError(f"{sid}: 参数名重复: {name}")
        names.add(name)
        if spec.get("type", "str") not in PARAM_TYPES:
            raise ManifestError(f"{sid}/{name}: type 必须是 {sorted(PARAM_TYPES)}")
        if "required" in spec and not isinstance(spec["required"], bool):
            raise ManifestError(f"{sid}/{name}: required 必须是布尔")
        if "choices" in spec:
            choices = spec["choices"]
            if not isinstance(choices, list) or not all(isinstance(c, str) for c in choices):
                raise ManifestError(f"{sid}/{name}: choices 必须是字符串数组")


def _check_outputs(step: dict) -> None:
    sid = step["id"]
    for pattern in step["outputs"]:
        if not isinstance(pattern, str) or not pattern:
            raise ManifestError(f"{sid}: outputs 必须是非空字符串数组")
        parts = PurePosixPath(pattern).parts
        if PurePosixPath(pattern).is_absolute() or ".." in parts:
            raise ManifestError(f"{sid}: outputs 必须是 job 目录内的相对路径")


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
        if step.get("script_root", "tactics_code") not in SCRIPT_ROOTS:
            raise ManifestError(f"{sid}: 未知 script_root")
        if not isinstance(step["args"], list) or not all(isinstance(a, str) for a in step["args"]):
            raise ManifestError(f"{sid}: args 必须是字符串数组")
        for key in ("params", "inputs", "outputs", "requires"):
            if not isinstance(step[key], list):
                raise ManifestError(f"{sid}: {key} 必须是数组")
        if not isinstance(step["writes_data"], bool):
            raise ManifestError(f"{sid}: writes_data 必须是布尔")
        if not isinstance(step["timeout_sec"], int) or step["timeout_sec"] <= 0:
            raise ManifestError(f"{sid}: timeout_sec 必须是正整数")
        _check_script(step)
        _check_params(step)
        _check_outputs(step)
        # 不变量：真正能跑的步骤只能是只读 probe / task，写数据盘的一律 planned。
        if step["status"] == "active":
            if step["kind"] not in RUNNABLE_KINDS or step["writes_data"]:
                raise ManifestError(f"{sid}: active 步骤只允许只读 probe/task（禁止写数据盘）")

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
    """把 step.script 解析为对应 script_root 内的绝对路径。"""
    _check_script(step)
    return script_root_path(step).joinpath(*PurePosixPath(step["script"]).parts)
