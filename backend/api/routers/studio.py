"""NBACore Studio — /studio router（Layer 3，纯编排）。

战术视频分析流水线的**编排层**入口。与 /tactics（战术板 + PBP 回放）是不同子系统，
命名空间刻意分开。本路由不含计算，只调 studio_engine 并向前端返回
``{code, data, message}`` 信封。

接口：
    GET  /studio/capabilities    外部资产探测（缺项供前端置灰）
    GET  /studio/manifest        能力目录（顺序与参数的唯一来源）
    POST /studio/plan            只生成命令，不执行
    POST /studio/jobs            创建任务（execute=true 且通过放行规则才真跑）
    GET  /studio/jobs            任务列表
    GET  /studio/jobs/{id}       任务状态 + 日志
    GET  /studio/artifacts       Studio 日志产物（白名单目录，不接受任意路径）

设计见 docs/unified-desktop-app-architecture.md §3。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from backend.services.studio_engine import capabilities
from backend.services.studio_engine import manifest as mf
from backend.services.studio_engine import runner as rn
from common.nba_paths import tactics_data_file

router = APIRouter(prefix="/studio", tags=["studio"])

# 懒加载：Manifest 缺失时不能让 router 模块在 import 期就抛错（打包一致性测试会 import 全部 router）。
_STATE: dict[str, rn.Runner] = {}


def get_runner() -> rn.Runner:
    if "runner" not in _STATE:
        _STATE["runner"] = rn.Runner()
    return _STATE["runner"]


def _ok(data: Any) -> dict:
    return {"code": 0, "data": data, "message": "ok"}


def _bad(code: int, message: str) -> dict:
    return {"code": code, "data": None, "message": message}


class PlanRequest(BaseModel):
    step_id: str
    params: dict[str, Any] = Field(default_factory=dict)


class JobRequest(PlanRequest):
    execute: bool = False


@router.get("/capabilities")
def get_capabilities():
    try:
        return _ok(capabilities.detect())
    except Exception as exc:  # noqa: BLE001
        return _bad(50000, f"capabilities 探测失败: {exc}")


@router.get("/manifest")
def get_manifest():
    try:
        return _ok(get_runner().manifest)
    except mf.ManifestError as exc:
        return _bad(50001, str(exc))
    except Exception as exc:  # noqa: BLE001
        return _bad(50000, f"能力目录加载失败: {exc}")


@router.post("/plan")
def post_plan(req: PlanRequest):
    try:
        return _ok(get_runner().plan(req.step_id, req.params))
    except KeyError:
        return _bad(40001, f"未知步骤: {req.step_id}")
    except mf.ManifestError as exc:
        return _bad(40002, str(exc))
    except Exception as exc:  # noqa: BLE001
        return _bad(50000, f"生成计划失败: {exc}")


@router.post("/jobs")
def post_job(req: JobRequest):
    try:
        job = get_runner().submit(req.step_id, req.params, req.execute)
        return _ok(job.to_dict())
    except KeyError:
        return _bad(40001, f"未知步骤: {req.step_id}")
    except mf.ManifestError as exc:
        return _bad(40002, str(exc))
    except Exception as exc:  # noqa: BLE001
        return _bad(50000, f"创建任务失败: {exc}")


@router.get("/jobs")
def list_jobs():
    return _ok(get_runner().list())


@router.get("/jobs/{job_id}")
def get_job(job_id: str):
    job = get_runner().get(job_id)
    if job is None:
        return _bad(40004, f"任务不存在: {job_id}")
    return _ok(job)


@router.get("/artifacts")
def list_artifacts():
    """只列 Studio 自己的日志目录，不接受用户传入路径（最强目录穿越防御）。"""
    folder = tactics_data_file("studio", "jobs").resolve()
    if not folder.is_dir():
        return _ok({"root": str(folder), "items": []})
    items = []
    for path in sorted(folder.iterdir()):
        if not path.is_file():
            continue
        try:
            path.resolve().relative_to(folder)
        except ValueError:
            continue
        stat = path.stat()
        items.append({"name": path.name, "bytes": stat.st_size, "mtime": stat.st_mtime})
    return _ok({"root": str(folder), "items": items})
