#!/usr/bin/env python3
"""
job_manager.py -- Append-only work log + subprocess job control for the
daily metrics snapshot control panel.

Design rules inherited from the crawler-control-panel pattern:
  * worklog.json is the source of truth, append-only.
  * Every job dict stores ALL of its parameters -- resume() replays them
    verbatim. Losing a parameter on resume silently turns a filtered crawl
    into a full one (a real bug this design exists to prevent).
  * Each job is an isolated subprocess so the server never blocks and any
    single job can be stopped on its own.
"""
import io
import os
import json
import time
import signal
import threading
import subprocess
from datetime import datetime
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
ROOT = APP_DIR.parent
LOGS_DIR = APP_DIR / "logs"
WORKLOG = APP_DIR / "worklog.json"
VENV_PY = str(ROOT / ".venv" / "bin" / "python")

SNAPSHOT_SCRIPT = "scripts/daily_metrics_snapshot.py"
ENRICH_SCRIPT = "scripts/enrich_metrics_team_abbr.py"

METRICS = ("dpm", "rapm", "lebron")

_lock = threading.Lock()


def _now():
    return datetime.now().isoformat(timespec="seconds")


def _read_log():
    if not WORKLOG.exists():
        return []
    try:
        with io.open(WORKLOG, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (json.JSONDecodeError, OSError):
        return []


def _write_log(jobs):
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    tmp = WORKLOG.with_suffix(".json.tmp")
    with io.open(tmp, "w", encoding="utf-8") as fh:
        json.dump(jobs, fh, indent=2, ensure_ascii=False)
    os.replace(tmp, WORKLOG)


def _update_job(job_id, **fields):
    with _lock:
        jobs = _read_log()
        for j in jobs:
            if j["id"] == job_id:
                j.update(fields)
                break
        _write_log(jobs)


class JobManager:
    def __init__(self):
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        self._procs = {}          # job_id -> Popen

    # ---------------------------------------------------------------- jobs
    def list_jobs(self, limit=200):
        jobs = _read_log()
        return list(reversed(jobs[-limit:]))

    def get_job(self, job_id):
        for j in _read_log():
            if j["id"] == job_id:
                return j
        return None

    def get_log(self, job_id, max_lines=800):
        job = self.get_job(job_id)
        if not job:
            return None
        path = Path(job.get("log_file", ""))
        if not path.exists():
            return ""
        try:
            with io.open(path, "r", encoding="utf-8", errors="replace") as fh:
                lines = fh.readlines()
        except OSError:
            return ""
        return "".join(lines[-max_lines:])

    # ------------------------------------------------------------- submit
    def submit(self, kind, params):
        """kind: 'snapshot' | 'enrich'."""
        if kind == "snapshot":
            cmd = self._build_snapshot_cmd(params)
        elif kind == "enrich":
            cmd = self._build_enrich_cmd(params)
        else:
            raise ValueError(f"unknown job kind: {kind}")

        job_id = f"{kind}-{int(time.time()*1000)}"
        log_file = LOGS_DIR / f"{job_id}.log"

        job = {
            "id": job_id,
            "kind": kind,
            # ALL parameters stored verbatim -> resume() can replay exactly.
            "metrics": params.get("metrics") or list(METRICS),
            "date": params.get("date"),
            "dry_run": bool(params.get("dry_run")),
            "no_fetch": bool(params.get("no_fetch")),
            "limit": int(params.get("limit") or 0),
            "lebron_season": params.get("lebron_season") or "2025-26",
            "status": "running",
            "pid": None,
            "cmd": " ".join(str(c) for c in cmd),
            "log_file": str(log_file),
            "started_at": _now(),
            "finished_at": None,
            "exit_code": None,
            "summary": "",
        }

        with _lock:
            jobs = _read_log()
            jobs.append(job)
            _write_log(jobs)

        # Popen stdout MUST be an open file object, not a path string.
        try:
            lf = io.open(log_file, "w", encoding="utf-8")
            proc = subprocess.Popen(
                [str(c) for c in cmd],
                cwd=str(ROOT),
                stdout=lf,
                stderr=subprocess.STDOUT,
                text=True,
                env=self._env(),
            )
        except Exception as exc:  # noqa: BLE001
            lf.close()
            _update_job(job_id, status="failed", finished_at=_now(),
                        exit_code=-1, summary=f"failed to start: {exc}")
            return self.get_job(job_id)

        self._procs[job_id] = (proc, lf)
        _update_job(job_id, pid=proc.pid)
        threading.Thread(target=self._waiter, args=(job_id, proc, lf),
                         daemon=True).start()
        return self.get_job(job_id)

    def _env(self):
        env = os.environ.copy()
        # The shell environment injects an HTTP proxy that breaks local
        # requests; the scrapers strip it themselves, but keep it clean here too.
        for k in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY",
                  "all_proxy", "ALL_PROXY"):
            env.pop(k, None)
        return env

    def _build_snapshot_cmd(self, p):
        metrics = p.get("metrics") or list(METRICS)
        unknown = [m for m in metrics if m not in METRICS]
        if unknown:
            raise ValueError(f"unknown metric(s): {unknown}")
        cmd = [VENV_PY, SNAPSHOT_SCRIPT, "--metrics", ",".join(metrics)]
        if p.get("date"):
            cmd += ["--date", str(p["date"])]
        if p.get("dry_run"):
            cmd.append("--dry-run")
        if p.get("no_fetch"):
            cmd.append("--no-fetch")
        if int(p.get("limit") or 0) > 0:
            cmd += ["--limit", str(int(p["limit"]))]
        if p.get("lebron_season"):
            cmd += ["--lebron-season", str(p["lebron_season"])]
        return cmd

    def _build_enrich_cmd(self, p):
        cmd = [VENV_PY, ENRICH_SCRIPT, "--date", str(p.get("date") or "")]
        if p.get("dry_run"):
            cmd.append("--dry-run")
        return cmd

    # -------------------------------------------------------------- waiter
    def _waiter(self, job_id, proc, lf):
        try:
            code = proc.wait()
        finally:
            try:
                lf.flush()
                lf.close()
            except Exception:  # noqa: BLE001
                pass
            self._procs.pop(job_id, None)
        job = self.get_job(job_id) or {}
        # A job stopped via stop() already has its terminal status written.
        if job.get("status") == "running":
            summary = self._tail_summary(job.get("log_file"))
            _update_job(job_id,
                        status="done" if code == 0 else "failed",
                        finished_at=_now(),
                        exit_code=code,
                        summary=summary)

    @staticmethod
    def _tail_summary(log_path, n=6):
        if not log_path or not Path(log_path).exists():
            return ""
        try:
            with io.open(log_path, "r", encoding="utf-8", errors="replace") as fh:
                lines = [l.rstrip() for l in fh.readlines() if l.strip()]
            return " | ".join(lines[-n:])[:600]
        except OSError:
            return ""

    # ---------------------------------------------------------------- stop
    def stop(self, job_id):
        entry = self._procs.get(job_id)
        job = self.get_job(job_id)
        if not job:
            return {"ok": False, "error": "unknown job id"}
        if entry:
            proc, _lf = entry
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            except (ProcessLookupError, PermissionError, OSError):
                try:
                    proc.terminate()
                except Exception:  # noqa: BLE001
                    pass
        elif job.get("pid"):
            try:
                os.kill(job["pid"], signal.SIGTERM)
            except (ProcessLookupError, PermissionError, OSError):
                pass
        _update_job(job_id, status="stopped", finished_at=_now(),
                    exit_code=None, summary="stopped by user")
        return {"ok": True, "job_id": job_id}

    # -------------------------------------------------------------- resume
    def resume(self):
        """Re-submit every job that did not finish, replaying its parameters."""
        new_ids = []
        for j in _read_log():
            if j.get("status") == "done":
                continue
            if j.get("status") in ("running", "superseded"):
                continue
            _update_job(j["id"], status="superseded")
            params = {
                "metrics": j.get("metrics") or list(METRICS),
                "date": j.get("date"),
                "dry_run": j.get("dry_run", False),
                "no_fetch": j.get("no_fetch", False),
                "limit": j.get("limit", 0),
                "lebron_season": j.get("lebron_season") or "2025-26",
            }
            try:
                if j.get("kind") == "enrich":
                    nj = self.submit("enrich", {"date": params["date"],
                                                "dry_run": params["dry_run"]})
                else:
                    nj = self.submit(j.get("kind", "snapshot"), params)
                new_ids.append(nj["id"])
            except Exception as exc:  # noqa: BLE001 - one bad job must not stop the rest
                print(f"[resume] could not re-submit {j['id']}: {exc}")
        return new_ids
