"""Studio Runner — plan / job 状态机 / 唯一执行通道。

🔴 执行 tactics/ 脚本**只能走子进程 CLI**：约 17% 的脚本没有 __main__ 守卫，
import 即执行（tactics/README.md 探测禁令）。本模块不做任何动态模块加载。

P0 放行规则：只有 status=active、kind=probe、writes_data=false 且依赖齐备的步骤
可以真执行；其余一律返回 blocked，不写盘、不报错。设计见
docs/unified-desktop-app-architecture.md §3.3。
"""
from __future__ import annotations

import os
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from common.nba_paths import DATA_ROOT, REPO_ROOT, tactics_data_file

from . import capabilities
from . import manifest as mf


@dataclass
class Job:
    """一次任务的内存态。日志同时落数据盘（不可写时降级为仅内存）。"""

    id: str
    step_id: str
    status: str = "preview"
    cmd: list[str] = field(default_factory=list)
    cwd: str = ""
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    finished_at: float | None = None
    rc: int | None = None
    logs: list[str] = field(default_factory=list)
    error: str | None = None
    blocked_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "step_id": self.step_id,
            "status": self.status,
            "cmd": list(self.cmd),
            "cwd": self.cwd,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "rc": self.rc,
            "logs": list(self.logs),
            "error": self.error,
            "blocked_reason": self.blocked_reason,
        }


class Runner:
    """线程安全的最小 JobStore + 子进程执行器。"""

    def __init__(self, data: dict | None = None):
        self._manifest = data if data is not None else mf.load_manifest()
        self._lock = threading.Lock()
        self._jobs: dict[str, Job] = {}

    @property
    def manifest(self) -> dict:
        return self._manifest

    def _step(self, step_id: str) -> dict:
        step = mf.step_by_id(self._manifest, step_id)
        if step is None:
            raise KeyError(step_id)
        return step

    @staticmethod
    def _render_args(step: dict, params: dict[str, Any]) -> list[str]:
        """参数渲染：白名单占位符替换，不拼 shell（shell=False）。"""
        schema = {
            p["name"]: p
            for p in step["params"]
            if isinstance(p, dict) and isinstance(p.get("name"), str)
        }
        unknown = sorted(set(params) - set(schema))
        if unknown:
            raise mf.ManifestError(f"未知参数: {unknown}")
        values: dict[str, str] = {}
        for name, spec in schema.items():
            value = params.get(name, spec.get("default"))
            if value is None and spec.get("required"):
                raise mf.ManifestError(f"缺少必填参数: {name}")
            values[name] = "" if value is None else str(value)
        out: list[str] = []
        for arg in step["args"]:
            for name, value in values.items():
                arg = arg.replace("{" + name + "}", value)
            if "{" in arg and "}" in arg:
                raise mf.ManifestError(f"存在未解析的占位符: {arg}")
            out.append(arg)
        return out

    def _command(self, step: dict, params: dict[str, Any]) -> tuple[list[str], str]:
        if step["script"] is None:
            raise mf.ManifestError("未签核步骤尚无脚本，无法生成命令")
        py, why = capabilities.interpreter()
        if not py:
            raise mf.ManifestError(f"无可用 Python 解释器：{why}")
        cmd = [py, str(mf.script_path(step)), *self._render_args(step, params)]
        return cmd, str(REPO_ROOT)

    @staticmethod
    def _child_env() -> dict[str, str]:
        env = os.environ.copy()
        # WorkBuddy 注入的 sitecustomize broker 会拦截子进程里的 open()，长跑脚本必清。
        env.pop("PYTHONPATH", None)
        env["NBA_REPO_ROOT"] = str(REPO_ROOT)
        env["NBA_DATA_ROOT"] = str(DATA_ROOT)
        return env

    @staticmethod
    def _block_reason(step: dict, caps: dict) -> str | None:
        if step["status"] == "planned":
            return "该步骤尚未签核（planned），不允许执行"
        if step["kind"] != "probe":
            return "P0 阶段仅放行只读 probe 步骤"
        if step["writes_data"]:
            return "P0 阶段不执行写数据盘的步骤"
        for key in step["requires"]:
            item = caps["capabilities"].get(key)
            if item is None or not item["ok"]:
                return f"依赖未就绪：{key}"
        return None

    def plan(self, step_id: str, params: dict[str, Any] | None = None) -> dict:
        """只生成命令，**绝不执行任何子进程**。"""
        step = self._step(step_id)
        params = params or {}
        caps = capabilities.detect()
        reason = self._block_reason(step, caps)
        result: dict[str, Any] = {
            "step_id": step_id,
            "cmd": [],
            "cwd": str(REPO_ROOT),
            "blocked_reason": reason,
            "env_delta": {"NBA_REPO_ROOT": str(REPO_ROOT), "NBA_DATA_ROOT": str(DATA_ROOT),
                          "PYTHONPATH": "cleared"},
        }
        if reason is None:
            result["cmd"], result["cwd"] = self._command(step, params)
        return result

    def submit(self, step_id: str, params: dict[str, Any] | None = None,
               execute: bool = False) -> Job:
        """创建任务。execute=false 只留计划；被拒绝时 status=blocked 且不写盘。"""
        step = self._step(step_id)
        params = params or {}
        caps = capabilities.detect()
        reason = self._block_reason(step, caps)
        job = Job(id=uuid.uuid4().hex[:12], step_id=step_id)

        if reason is not None:
            job.status = "blocked"
            job.blocked_reason = reason
            job.finished_at = time.time()
            job.logs.append(f"[blocked] {reason}")
        elif not execute:
            job.status = "preview"
            job.cmd, job.cwd = self._command(step, params)
            job.logs.append("[preview] 仅生成计划，未执行任何子进程")
        else:
            try:
                job.cmd, job.cwd = self._command(step, params)
            except mf.ManifestError as exc:
                job.status = "blocked"
                job.blocked_reason = str(exc)
                job.finished_at = time.time()
                job.logs.append(f"[blocked] {exc}")
            else:
                job.status = "pending"
                with self._lock:
                    self._jobs[job.id] = job
                threading.Thread(target=self._execute, args=(job, step), daemon=True).start()
                return job

        with self._lock:
            self._jobs[job.id] = job
        return job

    def _execute(self, job: Job, step: dict) -> None:
        job.status = "running"
        job.started_at = time.time()
        try:
            proc = subprocess.run(
                job.cmd,
                cwd=job.cwd,
                env=self._child_env(),
                capture_output=True,
                text=True,
                timeout=step["timeout_sec"],
                check=False,
            )
            job.rc = proc.returncode
            if proc.stdout:
                job.logs.extend(proc.stdout.splitlines())
            if proc.stderr:
                job.logs.extend(proc.stderr.splitlines())
            job.status = "ok" if proc.returncode == 0 else "failed"
        except subprocess.TimeoutExpired as exc:
            job.status = "failed"
            job.error = f"超时（{step['timeout_sec']}s）"
            job.logs.append(f"[timeout] {job.error}: {exc}")
        except OSError as exc:
            job.status = "failed"
            job.error = str(exc)
            job.logs.append(f"[error] {exc}")
        finally:
            job.finished_at = time.time()
            self._write_log(job)

    @staticmethod
    def _write_log(job: Job) -> None:
        """日志落数据盘；数据根不可写时降级为仅内存，不影响任务结果。"""
        try:
            folder = tactics_data_file("studio", "jobs")
            if not folder.exists():
                folder.mkdir(parents=True, exist_ok=True)
            (folder / f"{job.id}.log").write_text("\n".join(job.logs), encoding="utf-8")
        except OSError:
            job.logs.append("[warn] 日志落盘失败（数据根不可写），仅保留内存日志")

    def get(self, job_id: str) -> dict | None:
        with self._lock:
            job = self._jobs.get(job_id)
            return job.to_dict() if job is not None else None

    def list(self) -> list[dict]:
        with self._lock:
            jobs = sorted(self._jobs.values(), key=lambda j: j.created_at, reverse=True)
            return [j.to_dict() for j in jobs]
