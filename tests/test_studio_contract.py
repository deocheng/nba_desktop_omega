"""Studio 编排层契约回归测试（P0）。

锁死四类不变量：
  1. 能力目录结构合法、脚本不逃出代码根、active 只能是只读 probe；
  2. plan 只生成命令、**绝不执行**；planned / 写盘步骤一律 blocked 且不触发子进程；
  3. Runner 只走 subprocess CLI，不做任何动态模块加载（tactics/ 探测禁令）；
  4. 路由、前端导航、打包 datas 与新增源码都不失修（门禁 11a 零绝对路径字面量）。

🔴 本测试全程不 import 任何 tactics/ 脚本；唯一实跑的子进程是 `--help` 只读探测。
"""
from __future__ import annotations

import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app import create_app
from backend.services.studio_engine import manifest as mf
from backend.services.studio_engine import runner as rn
from common.nba_paths import TACTICS_CODE_ROOT

PROJ = Path(__file__).resolve().parent.parent
PROBE_ID = "probe.cli_help"
PLANNED_ID = "pipeline.corpus_cba"
# 拼接构造：避免测试源码自身出现完整绝对路径字面量（门禁 11a 扫全文，注释也算）
FORBIDDEN = ("/Volumes" + "/12T", "/Users" + "/deocheng")


def test_manifest_loads_and_validates():
    data = mf.load_manifest()
    assert data["schema_version"] == 1
    assert data["steps"]
    assert any(s["id"] == PROBE_ID for s in data["steps"])
    assert any(s["id"] == PLANNED_ID and s["status"] == "planned" for s in data["steps"])


def test_active_step_is_readonly_probe_and_exists():
    active = [s for s in mf.load_manifest()["steps"] if s["status"] == "active"]
    assert len(active) == 1, "P0 只允许一个 active 的只读探测步骤"
    step = active[0]
    assert step["kind"] == "probe"
    assert step["writes_data"] is False
    assert mf.script_path(step).is_file()


def test_manifest_scripts_stay_inside_code_root():
    root = TACTICS_CODE_ROOT.resolve()
    for step in mf.load_manifest()["steps"]:
        if step["script"] is None:
            continue
        assert not Path(step["script"]).is_absolute()
        assert ".." not in Path(step["script"]).parts
        mf.script_path(step).resolve().relative_to(root)


def test_validate_rejects_path_escape_and_unsigned_active_step():
    data = mf.load_manifest()
    data["steps"][0]["script"] = "../outside.py"
    with pytest.raises(mf.ManifestError):
        mf.validate(data)

    data = mf.load_manifest()
    data["steps"][1]["status"] = "active"
    with pytest.raises(mf.ManifestError):
        mf.validate(data)


def test_plan_never_executes(monkeypatch):
    calls = []
    monkeypatch.setattr(rn.subprocess, "run", lambda *a, **k: calls.append(1))
    plan = rn.Runner(mf.load_manifest()).plan(PROBE_ID, {})
    assert plan["blocked_reason"] is None
    assert len(plan["cmd"]) >= 2
    assert plan["cmd"][1].endswith("_diag_ballfp.py")
    assert plan["cmd"][-1] == "--help"
    assert plan["env_delta"]["PYTHONPATH"] == "cleared"
    assert calls == [], "plan 绝对不能启动子进程"


def test_planned_step_is_blocked_without_subprocess(monkeypatch):
    calls = []
    monkeypatch.setattr(rn.subprocess, "run", lambda *a, **k: calls.append(1))
    job = rn.Runner(mf.load_manifest()).submit(PLANNED_ID, {}, execute=True)
    assert job.status == "blocked"
    assert "签核" in (job.blocked_reason or "")
    assert calls == []


def test_preview_job_does_not_execute():
    job = rn.Runner(mf.load_manifest()).submit(PROBE_ID, {}, execute=False)
    assert job.status == "preview"
    assert "未执行" in job.logs[0]


def test_probe_job_runs_readonly():
    engine = rn.Runner(mf.load_manifest())
    job = engine.submit(PROBE_ID, {}, execute=True)
    snap = engine.get(job.id)
    for _ in range(60):
        snap = engine.get(job.id)
        if snap["status"] not in ("pending", "running"):
            break
        time.sleep(0.1)
    assert snap["status"] == "ok", snap
    assert snap["rc"] == 0
    assert any("usage:" in line for line in snap["logs"])


def test_runner_never_dynamically_imports_tactics():
    src = (PROJ / "backend" / "services" / "studio_engine" / "runner.py").read_text(encoding="utf-8")
    for forbidden in ("importlib", "runpy", "__import__"):
        assert forbidden not in src, f"Runner 不得动态加载 tactics 脚本: {forbidden}"


def test_studio_endpoints():
    client = TestClient(create_app())
    for path in ("/studio/capabilities", "/studio/manifest", "/studio/jobs", "/studio/artifacts"):
        res = client.get(path)
        assert res.status_code == 200, (path, res.text)
        assert res.json()["code"] == 0

    caps = client.get("/studio/capabilities").json()["data"]
    assert "capabilities" in caps and "ready_for_run" in caps
    assert "python" in caps["capabilities"]

    plan = client.post("/studio/plan", json={"step_id": PROBE_ID, "params": {}})
    assert plan.json()["code"] == 0
    assert plan.json()["data"]["cmd"]

    unknown = client.post("/studio/plan", json={"step_id": "nope", "params": {}})
    assert unknown.json()["code"] == 40001


def test_frontend_and_packaging_wiring():
    idx = (PROJ / "frontend" / "index.html").read_text(encoding="utf-8")
    app_js = (PROJ / "frontend" / "js" / "app.js").read_text(encoding="utf-8")
    spec = (PROJ / "nbacore.spec").read_text(encoding="utf-8")
    assert 'data-page="studio"' in idx
    assert 'id="page-studio"' in idx
    assert "components/studio.js" in idx
    assert "loadStudioPage()" in app_js
    assert 'project_root / "studio" / "manifest.json"' in spec


def test_studio_sources_have_no_hardcoded_absolute_paths():
    files = (
        "backend/services/studio_engine/__init__.py",
        "backend/services/studio_engine/manifest.py",
        "backend/services/studio_engine/capabilities.py",
        "backend/services/studio_engine/runner.py",
        "backend/api/routers/studio.py",
        "tests/test_studio_contract.py",
    )
    for rel in files:
        src = (PROJ / rel).read_text(encoding="utf-8")
        for token in FORBIDDEN:
            assert token not in src, f"{rel} 含硬编码绝对路径字面量"
