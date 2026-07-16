"""run_headshots_all.sh 双锁 guard 离线测试（绝不启动真实爬虫 / 绝不碰 9222）。

策略：
  * ``bash -n`` 语法检查。
  * env 导出：静态断言脚本 export 了 BROWSER_BACKEND / CHROME_CDP_URL / BR_COOKIE_FILE
    并 source .env；再跑一段复制了脚本 env 段的脚本在运行时确认变量确实导出。
  * 双锁逻辑：
      - REAL dummy 模拟「gamelog 在跑」/「自身在跑」→ 运行整个脚本 → 立即 exit 1
        且不启动 crawl_br_headshots.py 爬虫（真 pgrep，faithful）。
      - fake pgrep 隔离测试：gamelog 锁 / 自身锁 各自触发 exit 1；双空闲 → 放行（用
        抽出的 guard 段验证，避免真的去拉起爬虫）。
  * dummy 清理：只 kill 自己 spawn 的 sleep dummy 进程，**绝不**误杀真实 gamelog（PID 23091）。

注意：当前确有真实 crawl_br_gamelog.py 在跑，本测试以「受控方式 + 双保险」验证双锁，
不会绕过、也不会干扰它。live 端到端（真实 CDP 取字节 + 12TB 写盘）不在本次范围。
"""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "run_headshots_all.sh"
PY = ROOT / ".venv" / "bin" / "python"

# 真实 gamelog PID（不得误杀）
REAL_GAMELOG_PIDS = set()
try:
    out = subprocess.run(["pgrep", "-f", "crawl_br_gamelog.py"],
                         capture_output=True, text=True).stdout.split()
    REAL_GAMELOG_PIDS = {int(p) for p in out if p.strip().isdigit()}
except Exception:
    pass

# 本测试自己 spawn 的 dummy 进程 PID（仅这些会被清理）
_DUMMY_PIDS: list[int] = []


def _spawn_dummy(name: str) -> int:
    """用 exec -a 把 argv[0] 伪装成 name，跑 sleep 30（确定性、可 kill）。"""
    proc = subprocess.Popen(
        ["bash", "-c", f"exec -a {name} sleep 30"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    _DUMMY_PIDS.append(proc.pid)
    time.sleep(0.4)  # 等待进程起来，保证 pgrep 能命中
    return proc.pid


def _kill_dummy(pid: int):
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    # 确认已退出
    for _ in range(10):
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return
        time.sleep(0.1)
    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


@pytest.fixture(scope="module", autouse=True)
def _cleanup_dummies():
    yield
    for pid in list(_DUMMY_PIDS):
        _kill_dummy(pid)
    _DUMMY_PIDS.clear()
    # 断言：真实 gamelog 仍然存活（我们没碰它）
    if REAL_GAMELOG_PIDS:
        still = [p for p in REAL_GAMELOG_PIDS if _pid_alive(p)]
        assert still, f"真实 gamelog PID {REAL_GAMELOG_PIDS} 被误杀！"


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except Exception:
        return True


def _no_headshots_crawler_running() -> bool:
    """确认没有真实 crawl_br_headshots.py 爬虫进程被拉起（脚本自身 cmdline 不含该串）。"""
    try:
        out = subprocess.run(
            ["pgrep", "-fl", "crawl_br_headshots.py"],
            capture_output=True, text=True,
        ).stdout
    except Exception:
        return True
    for line in out.splitlines():
        pid_s, _, cmd = line.partition(" ")
        if not cmd:
            continue
        # 只统计真正的 python 爬虫进程（排除我们自己的 sleep dummy 若名含该串）
        if "sleep" in cmd:
            continue
        if "crawl_br_headshots.py" in cmd:
            return False
    return True


# ── 1) 语法 ───────────────────────────────────────────────────────────────
def test_syntax_ok():
    proc = subprocess.run(["bash", "-n", str(SCRIPT)], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr


# ── 2) env 导出 ───────────────────────────────────────────────────────────
def test_script_exports_required_env_and_sources_dotenv():
    content = SCRIPT.read_text(encoding="utf-8")
    assert "export BROWSER_BACKEND=cdp" in content
    assert "export CHROME_CDP_URL=http://127.0.0.1:9222" in content
    assert "export BR_COOKIE_FILE=/tmp/br_cf_cookies.json" in content
    # source .env（兼容 . /path/.env 与 source /path/.env）
    assert (".env" in content) and ("set -a" in content)


def test_env_block_actually_exports(tmp_path):
    """复制脚本 env 段到独立脚本并在运行时确认变量确实导出。"""
    src = SCRIPT.read_text(encoding="utf-8")
    # 截取 source .env 到三个 export 之间的 env 设置段
    start = src.index("set -a")
    end_marker = "export CHROME_CDP_URL=http://127.0.0.1:9222"
    end = src.index(end_marker) + len(end_marker)
    env_block = src[start:end]
    checker = tmp_path / "env_check.sh"
    checker.write_text(
        textwrap.dedent(f"""\
        #!/usr/bin/env bash
        {env_block}
        echo "BROWSER_BACKEND=$BROWSER_BACKEND"
        echo "CHROME_CDP_URL=$CHROME_CDP_URL"
        echo "BR_COOKIE_FILE=$BR_COOKIE_FILE"
        echo "DBP=${{DB_PASSWORD:+set}}"
        """),
        encoding="utf-8",
    )
    checker.chmod(0o755)
    proc = subprocess.run(["bash", str(checker)], cwd=str(ROOT),
                          capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    assert "BROWSER_BACKEND=cdp" in proc.stdout
    assert "CHROME_CDP_URL=http://127.0.0.1:9222" in proc.stdout
    assert "BR_COOKIE_FILE=/tmp/br_cf_cookies.json" in proc.stdout
    # .env 里的 DB_PASSWORD 应被 source 进来
    assert "DBP=set" in proc.stdout


# ── 3) 双锁：REAL dummy 模拟在跑 → 立即 exit 1 且不启动爬虫 ────────────────
def test_guard_gamelog_running_blocks_launch():
    """模拟 gamelog 在跑 → 运行整个脚本 → exit 1 且不拉起 headshots 爬虫。"""
    pid = _spawn_dummy("crawl_br_gamelog.py")
    proc = subprocess.run(["bash", str(SCRIPT)], cwd=str(ROOT),
                          capture_output=True, text=True, timeout=60)
    _kill_dummy(pid)
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert _no_headshots_crawler_running(), "双锁失效：gamelog 在跑时仍拉起了爬虫！"


def test_guard_self_running_blocks_launch():
    """模拟自身已在跑 → 运行整个脚本 → exit 1 且不拉起第二个爬虫。"""
    pid = _spawn_dummy("crawl_br_headshots.py")
    proc = subprocess.run(["bash", str(SCRIPT)], cwd=str(ROOT),
                          capture_output=True, text=True, timeout=60)
    _kill_dummy(pid)
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert _no_headshots_crawler_running(), "双锁失效：自身已在跑时仍拉起了爬虫！"


# ── 4) fake pgrep 隔离测试：两锁各自触发 / 双空闲放行 ─────────────────────
def _write_fake_pgrep(tmp_path, running_patterns: str) -> Path:
    """写一个受控的假 pgrep：FAKE_RUNNING 中列出的模式才返回 0（命中）。"""
    fake = tmp_path / "pgrep"
    fake.write_text(
        textwrap.dedent(f"""\
        #!/usr/bin/env bash
        pattern=""
        for a in "$@"; do
          case "$a" in
            -*) ;;
            *) pattern="$a" ;;
          esac
        done
        for p in {running_patterns}; do
          [ "$pattern" = "$p" ] && exit 0
        done
        exit 1
        """),
        encoding="utf-8",
    )
    fake.chmod(0o755)
    return fake


def _extract_guard_block() -> str:
    """抽取脚本里两段双锁 if 块，拼成独立可测脚本（末尾用标记代替真实爬虫启动）。"""
    src = SCRIPT.read_text(encoding="utf-8")
    i1 = src.index('if pgrep -f "crawl_br_headshots.py"')
    i2 = src.index('if pgrep -f "crawl_br_gamelog.py"')
    # 两段都从 if 开始到各自的 fi 结束
    seg1 = src[i1:src.index("fi", i1) + 2]
    seg2 = src[i2:src.index("fi", i2) + 2]
    return seg1 + "\n" + seg2 + "\necho GUARD_PASSED\n"


def test_isolated_guard_gamelog_lock_fires(tmp_path):
    """隔离：gamelog 锁命中 → exit 1 且 GUARD_PASSED 不打印。"""
    fake = _write_fake_pgrep(tmp_path, "crawl_br_gamelog.py")
    guard = tmp_path / "guard_test.sh"
    guard.write_text(_extract_guard_block(), encoding="utf-8")
    guard.chmod(0o755)
    env = dict(os.environ, PATH=f"{tmp_path}:{os.environ.get('PATH','')}")
    proc = subprocess.run(["bash", str(guard)], env=env,
                          capture_output=True, text=True, timeout=30)
    assert proc.returncode == 1
    assert "GUARD_PASSED" not in proc.stdout


def test_isolated_guard_self_lock_fires(tmp_path):
    """隔离：自身锁命中 → exit 1 且 GUARD_PASSED 不打印。"""
    fake = _write_fake_pgrep(tmp_path, "crawl_br_headshots.py")
    guard = tmp_path / "guard_test.sh"
    guard.write_text(_extract_guard_block(), encoding="utf-8")
    guard.chmod(0o755)
    env = dict(os.environ, PATH=f"{tmp_path}:{os.environ.get('PATH','')}")
    proc = subprocess.run(["bash", str(guard)], env=env,
                          capture_output=True, text=True, timeout=30)
    assert proc.returncode == 1
    assert "GUARD_PASSED" not in proc.stdout


def test_isolated_guard_both_idle_passes(tmp_path):
    """隔离：双空闲 → 两锁都不触发 → GUARD_PASSED（证明 guard 不会永远 exit 1）。"""
    fake = _write_fake_pgrep(tmp_path, "")
    guard = tmp_path / "guard_test.sh"
    guard.write_text(_extract_guard_block(), encoding="utf-8")
    guard.chmod(0o755)
    env = dict(os.environ, PATH=f"{tmp_path}:{os.environ.get('PATH','')}")
    proc = subprocess.run(["bash", str(guard)], env=env,
                          capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0
    assert "GUARD_PASSED" in proc.stdout


def test_guard_code_present_in_source():
    """静态确认脚本确实含双锁两段（与隔离测试形成闭环，证明测的是真实代码）。"""
    content = SCRIPT.read_text(encoding="utf-8")
    assert 'pgrep -f "crawl_br_headshots.py"' in content
    assert 'pgrep -f "crawl_br_gamelog.py"' in content
    assert content.count("exit 1") >= 2
