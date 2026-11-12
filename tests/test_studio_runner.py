"""Studio Runner P1 运行时契约测试。

覆盖：真实只读战术脚本、参数渲染与类型校验、流式日志落盘、产物校验、
非零退出归因、超时 kill、用户取消、取消端点与产物端点。

🔴 载体说明：fixture 只写 job 专属隔离目录，真实战术步骤只跑 AST 判定为零写盘的
`_rel_confound.py`；未签核的写盘流水线仍由 planned + blocked 规则挡住。
"""
from __future__ import annotations

import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app import create_app
from backend.services.studio_engine import manifest as mf
from backend.services.studio_engine import runner as rn
from common.nba_paths import tactics_data_file

ECHO = "task.echo_params"
SLOW = "task.slow_stream"
FAIL = "task.fail_demo"
REAL = "task.rel_confound"

_REAL_INPUT = tactics_data_file("action_work", "validate", "rel_handler_validate.json")


def _step(data: dict, step_id: str) -> dict:
    return next(s for s in data["steps"] if s["id"] == step_id)


def _wait(engine: rn.Runner, job_id: str, seconds: float = 20.0) -> dict:
    deadline = time.time() + seconds
    snap = {}
    while time.time() < deadline:
        snap = engine.get(job_id) or {}
        if snap.get("status") not in ("pending", "running"):
            return snap
        time.sleep(0.1)
    return snap


@pytest.mark.skipif(not _REAL_INPUT.is_file(), reason="缺外置数据盘的关系层验证产物")
def test_real_readonly_tactics_task_runs():
    """真实 tactics 脚本以子进程方式跑通，证明编排层不依赖 AI 也能调真脚本。"""
    engine = rn.Runner(mf.load_manifest())
    job = engine.submit(REAL, {}, execute=True)
    snap = _wait(engine, job.id, seconds=40)
    if snap.get("status") == "blocked":
        pytest.skip("真实只读脚本依赖未就绪")
    assert snap["status"] == "ok", snap
    assert snap["rc"] == 0
    assert any("判据" in line for line in snap["logs"])


def test_param_schema_renders_into_argv():
    plan = rn.Runner(mf.load_manifest()).plan(ECHO, {"tag": "alpha", "lines": 3})
    assert plan["blocked_reason"] is None
    assert "--tag" in plan["cmd"] and "alpha" in plan["cmd"]
    assert "--lines" in plan["cmd"] and "3" in plan["cmd"]


def test_param_type_and_unknown_validation():
    engine = rn.Runner(mf.load_manifest())
    with pytest.raises(mf.ManifestError):
        engine.plan(ECHO, {"lines": "not-an-int"})
    with pytest.raises(mf.ManifestError):
        engine.plan(ECHO, {"unknown_param": 1})


def test_echo_params_ok_with_output_and_streamed_log():
    engine = rn.Runner(mf.load_manifest())
    job = engine.submit(ECHO, {"tag": "demo", "lines": 4}, execute=True)
    snap = _wait(engine, job.id)
    assert snap["status"] == "ok", snap
    assert snap["rc"] == 0
    assert snap["outputs_found"] == ["result.json"]
    assert any("tag=demo lines=4" in line for line in snap["logs"])
    assert len(snap["logs"]) >= 6
    if snap["job_dir"]:
        log_file = Path(snap["job_dir"]) / "log.txt"
        assert log_file.is_file()
        assert len(log_file.read_text(encoding="utf-8").splitlines()) >= 6


def test_nonzero_exit_attribution():
    engine = rn.Runner(mf.load_manifest())
    job = engine.submit(FAIL, {"rc": 7}, execute=True)
    snap = _wait(engine, job.id)
    assert snap["status"] == "failed", snap
    assert snap["error_kind"] == "nonzero_exit"
    assert snap["rc"] == 7
    assert snap["hint"]
    assert any("intentional failure" in line for line in snap["logs"])


def test_timeout_attribution():
    data = mf.load_manifest()
    _step(data, SLOW)["timeout_sec"] = 1
    engine = rn.Runner(data)
    job = engine.submit(SLOW, {}, execute=True)
    snap = _wait(engine, job.id, seconds=15)
    assert snap["status"] == "failed", snap
    assert snap["error_kind"] == "timeout"
    assert any("timeout" in line for line in snap["logs"])


def test_missing_outputs_attribution():
    data = mf.load_manifest()
    _step(data, ECHO)["outputs"] = ["never_written.json"]
    engine = rn.Runner(data)
    job = engine.submit(ECHO, {}, execute=True)
    snap = _wait(engine, job.id)
    assert snap["status"] == "failed", snap
    assert snap["error_kind"] == "missing_outputs"
    assert "never_written.json" in snap["error"]


def test_cancel_running_job_is_not_overwritten_by_worker():
    engine = rn.Runner(mf.load_manifest())
    job = engine.submit(SLOW, {}, execute=True)
    snap = engine.get(job.id) or {}
    for _ in range(60):
        snap = engine.get(job.id) or {}
        if snap.get("status") == "running":
            break
        time.sleep(0.05)
    assert snap["status"] == "running", snap
    cancelled = engine.cancel(job.id)
    assert cancelled["status"] == "cancelled"
    assert cancelled["error_kind"] == "cancelled"
    time.sleep(0.5)
    final = engine.get(job.id)
    assert final["status"] == "cancelled", final


def test_cancel_and_artifacts_endpoints():
    client = TestClient(create_app())
    preview = client.post("/studio/jobs", json={"step_id": ECHO, "params": {}, "execute": False})
    assert preview.json()["code"] == 0
    jid = preview.json()["data"]["id"]
    cancelled = client.post(f"/studio/jobs/{jid}/cancel")
    assert cancelled.status_code == 200
    assert cancelled.json()["data"]["status"] == "preview"

    arts = client.get("/studio/artifacts")
    assert arts.json()["code"] == 0
    assert isinstance(arts.json()["data"]["items"], list)
