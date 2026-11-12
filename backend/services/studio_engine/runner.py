"""Studio Runner — plan / job 状态机 / 唯一执行通道。

🔴 执行 tactics/ 脚本**只能走子进程 CLI**：约 17% 的脚本没有 __main__ 守卫，
import 即执行（tactics/README.md 探测禁令）。本模块不做任何动态模块加载。

P1 能力：参数类型校验、流式日志落盘、超时 kill、用户取消、失败归因
（spawn_error / timeout / cancelled / nonzero_exit / missing_outputs）、产物校验。

放行规则：只有 status=active、kind ∈ {probe, task}、writes_data=false 且依赖齐备
的步骤可以真执行；其余一律 blocked，不写盘、不报错。设计见
docs/unified-desktop-app-architecture.md §3.3。
"""
from __future__ import annotations

import os
import subprocess
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from common.nba_paths import DATA_ROOT, REPO_ROOT, tactics_data_file

from . import capabilities
from . import manifest as mf


@dataclass
class Job:
    """一次任务的内存态。日志与产物落在 job 专属隔离目录。"""

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
    error_kind: str | None = None
    hint: str | None = None
    blocked_reason: str | None = None
    job_dir: str = ""
    log_path: str = ""
    outputs_found: list[str] = field(default_factory=list)
    proc: Any = None

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
            "error_kind": self.error_kind,
            "hint": self.hint,
            "blocked_reason": self.blocked_reason,
            "job_dir": self.job_dir,
            "outputs_found": list(self.outputs_found),
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
    def _coerce(name: str, value: Any, spec: dict) -> str:
        """按 schema 做类型校验与归一化；值作为独立 argv 传入，不拼 shell。"""
        typ = spec.get("type", "str")
        if typ == "int":
            if isinstance(value, bool):
                raise mf.ManifestError(f"参数 {name} 需要 int，不能是布尔")
            try:
                return str(int(value))
            except (TypeError, ValueError) as exc:
                raise mf.ManifestError(f"参数 {name} 需要 int: {value!r}") from exc
        if typ == "float":
            try:
                return str(float(value))
            except (TypeError, ValueError) as exc:
                raise mf.ManifestError(f"参数 {name} 需要 float: {value!r}") from exc
        if typ == "bool":
            return "true" if str(value).strip().lower() in ("1", "true", "yes", "on") else "false"
        text = str(value)
        choices = spec.get("choices")
        if choices and text not in [str(c) for c in choices]:
            raise mf.ManifestError(f"参数 {name} 取值不在 choices: {choices}")
        return text

    @classmethod
    def _render_args(cls, step: dict, params: dict[str, Any]) -> list[str]:
        """参数渲染：白名单占位符替换 + schema 校验，不拼 shell（shell=False）。"""
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
            if value is None:
                if spec.get("required"):
                    raise mf.ManifestError(f"缺少必填参数: {name}")
                values[name] = ""
            else:
                values[name] = cls._coerce(name, value, spec)
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
    def _child_env(job: Job) -> dict[str, str]:
        env = os.environ.copy()
        # WorkBuddy 注入的 sitecustomize broker 会拦截子进程里的 open()，长跑脚本必清。
        env.pop("PYTHONPATH", None)
        env["NBA_REPO_ROOT"] = str(REPO_ROOT)
        env["NBA_DATA_ROOT"] = str(DATA_ROOT)
        env["STUDIO_JOB_DIR"] = job.job_dir
        return env

    @staticmethod
    def _block_reason(step: dict, caps: dict) -> str | None:
        if step["status"] == "planned":
            return "该步骤尚未签核（planned），不允许执行"
        if step["kind"] not in mf.RUNNABLE_KINDS:
            return "仅放行只读 probe / task 步骤"
        if step["writes_data"]:
            return "不执行写数据盘的步骤"
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
                          "STUDIO_JOB_DIR": "每个 job 独立隔离目录", "PYTHONPATH": "cleared"},
        }
        if reason is None:
            result["cmd"], result["cwd"] = self._command(step, params)
        return result

    @staticmethod
    def _prepare_job_dir(job: Job) -> None:
        """为每个 job 建隔离目录；数据根不可写时退回系统临时目录。

        没有外置数据盘的机器（如 CI / 首次启动的打包版）也要能跑只读步骤与
        fixture，否则 outputs 校验必然失败、程序等于不可用。
        """
        try:
            folder = tactics_data_file("studio", "jobs", job.id)
            if not folder.exists():
                folder.mkdir(parents=True, exist_ok=True)
            job.job_dir = str(folder)
        except OSError:
            try:
                job.job_dir = tempfile.mkdtemp(prefix="studio_job_")
                job.logs.append("[warn] 数据根不可写，job 产物落在系统临时目录")
            except OSError:
                job.logs.append("[warn] job 目录不可写，日志与产物仅保留内存状态")
        if job.job_dir:
            job.log_path = str(Path(job.job_dir) / "log.txt")

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
                self._prepare_job_dir(job)
                job.status = "pending"
                with self._lock:
                    self._jobs[job.id] = job
                threading.Thread(target=self._execute, args=(job, step), daemon=True).start()
                return job

        with self._lock:
            self._jobs[job.id] = job
        return job

    @staticmethod
    def _pump(proc: subprocess.Popen, job: Job, log_path: str) -> None:
        """流式读取 stdout+stderr：边跑边写日志，取消/崩溃后日志也不丢。"""
        stream = None
        try:
            if log_path:
                stream = open(log_path, "a", encoding="utf-8")
            for line in proc.stdout or []:
                text = line.rstrip("\n")
                job.logs.append(text)
                if stream is not None:
                    stream.write(text + "\n")
                    stream.flush()
        except OSError:
            job.logs.append("[warn] 日志落盘失败，仅保留内存日志")
        finally:
            if stream is not None:
                try:
                    stream.close()
                except OSError:
                    pass

    @staticmethod
    def _glob_outputs(job: Job, step: dict) -> list[str]:
        if not job.job_dir:
            return []
        root = Path(job.job_dir)
        found: list[str] = []
        for pattern in step.get("outputs") or []:
            found.extend(str(p.relative_to(root)) for p in sorted(root.glob(pattern)))
        return found

    def _missing_outputs(self, job: Job, step: dict) -> list[str]:
        declared = step.get("outputs") or []
        if not declared:
            return []
        if not job.job_dir:
            return list(declared)
        root = Path(job.job_dir)
        return [pat for pat in declared if not list(root.glob(pat))]

    def _execute(self, job: Job, step: dict) -> None:
        if job.error_kind == "cancelled":
            job.status = "cancelled"
            job.finished_at = time.time()
            return
        job.status = "running"
        job.started_at = time.time()
        try:
            proc = subprocess.Popen(
                job.cmd,
                cwd=job.cwd,
                env=self._child_env(job),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
            job.proc = proc
            pump = threading.Thread(
                target=self._pump, args=(proc, job, job.log_path), daemon=True,
            )
            pump.start()
            try:
                rc = proc.wait(timeout=step["timeout_sec"])
            except subprocess.TimeoutExpired:
                proc.kill()
                rc = proc.wait()
                job.error_kind = "timeout"
                job.error = f"超时（{step['timeout_sec']}s）"
                job.hint = "调大 timeout_sec，或减少输入规模"
                job.logs.append(f"[timeout] {job.error}")
            pump.join(timeout=3)
            job.rc = rc

            if job.error_kind == "cancelled":
                job.logs.append("[cancelled] 用户取消任务")
            elif job.error_kind == "timeout":
                job.status = "failed"
            elif rc != 0:
                job.status = "failed"
                job.error_kind = "nonzero_exit"
                job.error = f"子进程退出码 {rc}"
                job.hint = "查看日志尾部；常见原因是输入产物缺失或参数不合法"
            else:
                missing = self._missing_outputs(job, step)
                if missing:
                    job.status = "failed"
                    job.error_kind = "missing_outputs"
                    job.error = f"声明的产物未生成: {missing}"
                    job.hint = "确认脚本输出路径与 step.outputs 声明一致"
                else:
                    job.status = "ok"
                    job.outputs_found = self._glob_outputs(job, step)
        except OSError as exc:
            job.status = "failed"
            job.error_kind = "spawn_error"
            job.error = str(exc)
            job.hint = "检查 STUDIO_PYTHON 与 script 路径是否存在"
            job.logs.append(f"[error] {exc}")
        finally:
            job.finished_at = time.time()
            if job.status not in ("ok", "failed", "cancelled"):
                job.status = "failed"

    def cancel(self, job_id: str) -> dict | None:
        """取消运行中的任务；已结束的任务原样返回。"""
        with self._lock:
            job = self._jobs.get(job_id)
        if job is None:
            return None
        if job.status not in ("pending", "running"):
            return job.to_dict()
        job.error_kind = "cancelled"
        job.status = "cancelled"
        job.error = "用户取消"
        job.hint = "任务已被主动终止，已产生的日志保留"
        job.finished_at = time.time()
        proc = job.proc
        if proc is not None and proc.poll() is None:
            try:
                proc.terminate()
            except OSError:
                try:
                    proc.kill()
                except OSError:
                    pass
        return job.to_dict()

    def get(self, job_id: str) -> dict | None:
        with self._lock:
            job = self._jobs.get(job_id)
            return job.to_dict() if job is not None else None

    def list(self) -> list[dict]:
        with self._lock:
            jobs = sorted(self._jobs.values(), key=lambda j: j.created_at, reverse=True)
            return [j.to_dict() for j in jobs]
