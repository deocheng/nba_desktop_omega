"""真实脚本解析级回归测试（real-parse regression test）。

目的：捕捉「反斜杠换行续行（line-continuation）」这类只在真实 bash 解析阶段
才暴露、而桩函数单测抓不到的 bug。典型历史问题：run_gamelog_all.sh 的 gamelog
循环与接力块被 `\\` 续行拆成多物理行，bash 在 done 边界把双引号解析搞崩，抛出
`ason: command not found`，脚本在抵达自动接力块之前就中断 —— 接力因此永不触发。

本测试**真正拷一份脚本到临时目录**，放桩爬虫，真实 `bash` 跑一次，断言：
  1) 进程 exit 0，且日志里没有 `command not found` / 断裂的 `ason:` token；
  2) gamelog_crawl.log 含 `[relay] gamelog 抓取完成` 与 `[relay] headshots 接力成功完成`；
  3) headshots_relay.log 已生成且含 `STUB_HEADSHOTS`（证明 crawl_br_headshots.py --resume 被真实调用）；
  4) 6 个季的 `STUB_GAMEL0G season=...` 都出现在 gamelog_crawl.log（证明循环完整）。

不触碰任何真实爬虫 / 日志 / Chrome / 数据库。
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "run_gamelog_all.sh"
SEASONS = ["1997", "1998", "1999", "2000", "2024", "2026"]

GAMELOG_STUB = """#!/usr/bin/env python3
import sys
import time
season = sys.argv[sys.argv.index('--season') + 1]
print("STUB_GAMEL0G season=" + season)
time.sleep(0.05)
sys.exit(0)
"""

HEADSHOTS_STUB = """#!/usr/bin/env python3
import sys
print("STUB_HEADSHOTS args=" + str(sys.argv[1:]))
sys.exit(0)
"""


def _write(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")


def _build_sandbox(root: Path) -> Path:
    """拷脚本到临时目录并放入桩爬虫，返回脚本路径。

    ⚠️ 不做**文本改写**（旧实现靠 str(REPO_ROOT) 字面量替换脚本里的硬编码路径）：
       脚本里的路径是本机生产路径 <数据盘根>/...，在 CI（checkout 到别处）
       替换**不会命中** → 脚本仍会 cd 回真实仓库并跑**真爬虫**（实测：真爬虫
       被启动、日志被追加到真实仓库）。现改为脚本自身支持环境变量
       （REPO_ROOT / LOG / HEADSHOT_LOG / PY / GUARD_PATTERN），测试只注入 env，
       天然与路径无关。
    """
    assert SCRIPT.exists(), f"missing {SCRIPT}"
    crawler_dir = root / "external_crawler" / "crawler"
    crawler_dir.mkdir(parents=True, exist_ok=True)

    # 桩爬虫（可独立执行）
    gamelog = crawler_dir / "crawl_br_gamelog.py"
    headshots = crawler_dir / "crawl_br_headshots.py"
    _write(gamelog, GAMELOG_STUB)
    _write(headshots, HEADSHOTS_STUB)
    os.chmod(gamelog, 0o755)
    os.chmod(headshots, 0o755)

    # 假 .env（桩爬虫不真连库）
    _write(root / ".env", "DB_PASSWORD=dummy\n")

    script = root / "run_gamelog_all.sh"
    shutil.copy(SCRIPT, script)
    return script


def _sandbox_env(root: Path) -> dict:
    """把脚本的路径/解释器全部指向沙箱，使其**绝无可能**触碰真实仓库。"""
    env = dict(os.environ)
    env.update({
        "REPO_ROOT": str(root),
        "LOG": str(root / "gamelog_crawl.log"),
        "HEADSHOT_LOG": str(root / "headshots_relay.log"),
        "PY": sys.executable,
        # 并行守卫：沙箱里永远不该命中（真实爬虫在跑也不该让本用例失败）
        "GUARD_PATTERN": "relay_sandbox_guard_never_matches_9f3a",
    })
    return env


def _assert_clean(log_text: str) -> None:
    """断言日志里没有续行崩坏导致的报错。"""
    assert "command not found" not in log_text, "发现 command not found（续行崩坏）"
    # 断裂 token 形如 `ason: command not found`，需排除正常单词 season
    broken = [ln for ln in log_text.splitlines() if ": ason:" in ln or " ason:" in ln]
    assert not broken, f"发现断裂 ason token: {broken}"


def test_real_script_relay_fires(tmp_path: Path) -> None:
    """真实 bash 跑脚本，验证自动接力被触发。"""
    if shutil.which("bash") is None:
        pytest.skip("bash 不可用")
    root = tmp_path / "relaytest"
    root.mkdir()
    script = _build_sandbox(root)

    proc = subprocess.run(
        ["bash", str(script)],
        cwd=str(root),
        env=_sandbox_env(root),
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, f"脚本非零退出: {proc.returncode}\n{proc.stderr}"

    gamelog_log = root / "gamelog_crawl.log"
    headshots_log = root / "headshots_relay.log"
    assert gamelog_log.exists(), "gamelog_crawl.log 未生成"
    _assert_clean(gamelog_log.read_text(encoding="utf-8"))

    body = gamelog_log.read_text(encoding="utf-8")
    assert "[relay] gamelog 抓取完成" in body, "接力开始 echo 缺失（接力块未执行）"
    assert "[relay] headshots 接力成功完成" in body, "headshots 接力成功 echo 缺失"

    assert headshots_log.exists(), "headshots_relay.log 未生成（接力未调用 headshots）"
    hbody = headshots_log.read_text(encoding="utf-8")
    assert "STUB_HEADSHOTS" in hbody, "headshots 桩未被真实调用"

    for s in SEASONS:
        assert f"STUB_GAMEL0G season={s}" in body, f"缺失季 {s}（循环不完整）"


def test_script_has_no_line_continuations() -> None:
    """静态守卫：脚本本身不应再出现行尾反斜杠续行。"""
    text = SCRIPT.read_text(encoding="utf-8")
    cont = [i + 1 for i, ln in enumerate(text.splitlines()) if ln.endswith("\\")]
    assert not cont, f"脚本仍存在续行符（行号）: {cont}"
