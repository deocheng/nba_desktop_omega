#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
job_manager.py — BR 爬虫套装独立 App 的任务调度 + 工作日志。

设计原则（严守用户铁律）：
  - 每个爬取任务以**独立子进程**运行（不阻塞 server、可续爬、可单独 stop）。
  - 工作日志 worklog.json（append-only，记录每个 job 的 type/season/status/起止/计数/错误），
    落盘即真相，支撑"根据日志续爬"。
  - 复用既有 v2 适配器 / daemon.runner / fusion_report，不重写爬取逻辑。
  - 零第三方依赖（stdlib subprocess + json + threading），离线可跑。

任务类型：
  crawl   单数据项爬取（gamelog/pbp/espn/nba_api）
  fuse    融合数据报告（fusion_report.py，只读汇总）
  season  赛季全量爬取（daemon.runner，自带 STATE 续爬）
  resume  根据 worklog 续爬（重派未成功 job）
"""
import os
import sys
import json
import time
import signal
import threading
import subprocess
from pathlib import Path
from typing import Dict, List, Optional

# ---- 路径（从本文件推导，避免硬编码 ROOT）----
HERE = Path(__file__).resolve().parent            # crawler_v2/app
CRAWLER_V2 = HERE.parent                          # crawler_v2
EXTERNAL = CRAWLER_V2.parent                      # external_crawler
ROOT = EXTERNAL.parent                            # nba_desktop_omega_mac_migrate_2026-07-13
CRAWLER = EXTERNAL / "crawler"
GAMELOG_CACHE = CRAWLER / "gamelog_cache"

WORKLOG_PATH = HERE / "worklog.json"
LOGS_DIR = HERE / "logs"
LOGS_DIR.mkdir(parents=True, exist_ok=True)

# 子进程运行时需保证可 import 的目录（v2 适配器会自行补 ROOT，这里兜底加全）
SUBPROC_PYTHONPATH = [str(CRAWLER_V2), str(ROOT), str(CRAWLER)]

_lock = threading.Lock()


# ============================ worklog 读写 ============================
def _read_log() -> List[Dict]:
    if not WORKLOG_PATH.exists():
        return []
    try:
        return json.loads(WORKLOG_PATH.read_text(encoding="utf-8"))
    except Exception:
        return []


def _write_log(jobs: List[Dict]) -> None:
    WORKLOG_PATH.write_text(json.dumps(jobs, ensure_ascii=False, indent=2), encoding="utf-8")


def _append_job(job: Dict) -> None:
    with _lock:
        jobs = _read_log()
        jobs.append(job)
        _write_log(jobs)


def _update_job(job_id: str, **fields) -> None:
    with _lock:
        jobs = _read_log()
        for j in jobs:
            if j["id"] == job_id:
                j.update(fields)
                break
        _write_log(jobs)


def _gen_id(kind: str) -> str:
    return f"{kind}_{time.strftime('%Y%m%d_%H%M%S')}_{os.urandom(2).hex()}"


def _tail(path: Path, n: int = 60) -> str:
    if not path.exists():
        return ""
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        return "\n".join(lines[-n:])
    except Exception:
        return ""


# ============================ 子进程命令构造 ============================
def build_cmd(kind: str, data_item: str, season: Optional[int],
              dry_run: bool, only_br_ids: Optional[str] = None) -> List[str]:
    py = sys.executable
    dr = ["--dry-run"] if dry_run else []
    if kind == "crawl":
        if data_item == "gamelog":
            cmd = [py, "-m", "adapters.br_gamelog_adapter", "--season", str(season),
                   "--cache-dir", str(GAMELOG_CACHE)]
            if only_br_ids and Path(only_br_ids).exists():
                cmd += ["--only-br-ids", only_br_ids]
            cmd += dr
        elif data_item == "pbp":
            cmd = [py, "-m", "adapters.br_pbp_adapter"]
            if season:
                cmd += ["--seasons", str(season)]
            cmd += dr
        elif data_item in ("espn", "nba_api"):
            cmd = [py, "-m", f"adapters.{data_item}_adapter", "--season", str(season)] + dr
        else:
            raise ValueError(f"未知数据项: {data_item}")
    elif kind == "fuse":
        cmd = [py, str(HERE / "fusion_report.py")]
        if season:
            cmd += ["--season", str(season)]
    elif kind == "season":
        cmd = [py, "-m", "daemon.runner"]
        if season:
            cmd += ["--seasons-override", str(season)]
        cmd += dr
    else:
        raise ValueError(f"未知任务类型: {kind}")
    return cmd


# ============================ 任务执行 ============================
class JobManager:
    def __init__(self):
        self._procs: Dict[str, subprocess.Popen] = {}

    def submit(self, kind: str, data_item: str, season: Optional[int],
               dry_run: bool, only_br_ids: Optional[str] = None) -> Dict:
        job_id = _gen_id(kind)
        log_file = LOGS_DIR / f"{job_id}.log"
        cmd = build_cmd(kind, data_item, season, dry_run, only_br_ids)
        job = {
            "id": job_id,
            "kind": kind,
            "data_item": data_item,
            "season": season,
            "dry_run": dry_run,
            "only_br_ids": only_br_ids,
            "status": "running",
            "pid": None,
            "cmd": " ".join(str(c) for c in cmd),
            "log_file": str(log_file),
            "started_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "finished_at": None,
            "exit_code": None,
            "summary": "",
        }
        _append_job(job)

        env = dict(os.environ)
        pp = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = os.pathsep.join(SUBPROC_PYTHONPATH + ([pp] if pp else []))
        # 清出站代理（BR 直连纪律，复用 core.config 语义）
        for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
            env.pop(k, None)
        env["NO_PROXY"] = "*"

        try:
            # Popen 的 stdout 需文件对象/ fd，不接受字符串路径
            with open(log_file, "w", encoding="utf-8") as lf:
                proc = subprocess.Popen(
                    cmd, cwd=str(CRAWLER_V2), env=env,
                    stdout=lf, stderr=subprocess.STDOUT,
                    text=True,
                )
        except Exception as e:
            _update_job(job_id, status="failed", finished_at=time.strftime("%Y-%m-%d %H:%M:%S"),
                        summary=f"启动失败: {e}")
            return job

        self._procs[job_id] = proc
        _update_job(job_id, pid=proc.pid)
        t = threading.Thread(target=self._watch, args=(job_id, proc, log_file), daemon=True)
        t.start()
        return job

    def _watch(self, job_id: str, proc: subprocess.Popen, log_file: Path):
        try:
            rc = proc.wait()
        except Exception:
            rc = -1
        self._procs.pop(job_id, None)
        tail = _tail(log_file, n=8)
        # 从日志尾部提取摘要
        summary = ""
        for line in tail.splitlines():
            if "[done]" in line or "VERIFIED" in line or "SCAFFOLD" in line or "Error" in line or "error" in line:
                summary = line.strip()[:200]
                break
        if not summary:
            summary = (tail.splitlines()[-1].strip()[:200] if tail.strip() else "")
        status = "done" if rc == 0 else ("scaffold" if "SCAFFOLD" in (summary or "") else "failed")
        _update_job(job_id, status=status, exit_code=rc,
                    finished_at=time.strftime("%Y-%m-%d %H:%M:%S"), summary=summary)

    def stop(self, job_id: str) -> bool:
        proc = self._procs.get(job_id)
        if proc and proc.poll() is None:
            try:
                proc.send_signal(signal.SIGTERM)
            except Exception:
                pass
            _update_job(job_id, status="killed", finished_at=time.strftime("%Y-%m-%d %H:%M:%S"),
                        summary="用户手动停止")
            return True
        return False

    def list_jobs(self) -> List[Dict]:
        return _read_log()

    def job_log(self, job_id: str, n: int = 80) -> str:
        with _lock:
            jobs = _read_log()
        for j in jobs:
            if j["id"] == job_id:
                return _tail(Path(j["log_file"]), n=n)
        return ""

    def resume(self) -> List[str]:
        """根据 worklog 续爬：重派所有未成功(job status != done)的任务。
        原 job 标记 superseded，新 job 沿用相同参数。返回新 job id 列表。"""
        with _lock:
            jobs = _read_log()
        new_ids: List[str] = []
        for j in jobs:
            if j.get("status") == "done":
                continue
            # 跳过仍在运行中的（避免重复派发），以及 scaffold（实现缺失，重跑无意义）
            if j.get("status") in ("running", "scaffold"):
                continue
            _update_job(j["id"], status="superseded")
            nj = self.submit(j["kind"], j["data_item"], j.get("season"),
                             j.get("dry_run", True), j.get("only_br_ids"))
            new_ids.append(nj["id"])
        return new_ids


# 单例
_manager = JobManager()


def manager() -> JobManager:
    return _manager
