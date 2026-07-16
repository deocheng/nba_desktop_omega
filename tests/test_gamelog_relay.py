"""run_gamelog_all.sh 接力(relay)块离线测试 —— 绝不启动真实爬虫 / 绝不碰 9222 / 不连真实 DB。

策略（受控、faithful、不干扰正在跑的真实 gamelog PID）：
  * 语法/静态（离线）：
      - ``bash -n`` 检查 run_gamelog_all.sh 与 run_headshots_all.sh 均通过。
      - 静态断言接力块在 gamelog ``for...done`` 循环之后；含 ``crawl_br_headshots.py --resume``
        调用；env 导出（BR_COOKIE_FILE / BROWSER_BACKEND / CHROME_CDP_URL / source .env）在接力块
        之前声明；HEADSHOT_LOG 已定义；且接力块**直接调 python** 而非 run_headshots_all.sh。
  * 接力逻辑受控模拟（核心，不碰真实爬取）：
      把接力块（GAMELOG ALL DONE 之后那段）连同 gamelog 季节循环一起，抽出来在一个受控 harness
      里执行。harness 用 stub 覆盖 ``$PY``（记录「被调用」的临时脚本）、用 fake ``pgrep`` 覆盖真实
      进程探测、用真 ``tee``/``date``（不影响断言）。
        - 场景 A（正常接力）：pgrep 返回「无 headshots 在跑」→ 恰好调用一次
          ``crawl_br_headshots.py --resume``，且发生在 6 个 gamelog 季节全部跑完之后（顺序日志证明串行）。
        - 场景 B（self-guard 跳过）：pgrep 返回「有 headshots 在跑」→ 跳过调用（python 不被调用），
          并打印「跳过接力（避免并行）」。
        - 场景 C（失败兜底）：headshots stub 返回非 0 exit → 脚本不中断，继续到「全部流程结束」，
          并打印「接力失败」。
  * 独立脚本回归：run_headshots_all.sh 双锁（自身 pgrep + gamelog 互斥 pgrep）仍完好（隔离 fake
      pgrep 重跑，证明本次改动没动它；不 spawn 真实 dummy，避免干扰 live gamelog）。
  * 不并行铁证：综合场景 A/B 与静态分析 → 「接力 = 串行串联，gamelog 完全结束后才触发 headshots，
    self-guard 防极端并发」。

铁律：live 端到端（真实 CDP 取字节 + 12TB 写盘）不在本次范围，留待下一轮 gamelog 空闲后执行。
"""
from __future__ import annotations

import os
import subprocess
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "run_gamelog_all.sh"
HEADSHOTS_SCRIPT = ROOT / "run_headshots_all.sh"


# ── 抽取源码片段（faithful，不手抄） ───────────────────────────────────────
def _read_lines() -> list[str]:
    return SCRIPT.read_text(encoding="utf-8").splitlines()


def _gamelog_loop_block() -> str:
    """抽取 gamelog 季节循环 ``for S in ...; do ... done``。"""
    lines = _read_lines()
    for_i = next(i for i, l in enumerate(lines) if l.strip().startswith("for S in"))
    done_i = next(d for d in range(len(lines))
                  if lines[d].strip() == "done" and d > for_i)
    return "\n".join(lines[for_i:done_i + 1])


def _relay_block() -> str:
    """抽取接力块：从 ``GAMELOG ALL DONE`` 那一行之后到文件末尾。"""
    content = SCRIPT.read_text(encoding="utf-8")
    marker = 'echo "===== $(date) GAMELOG ALL DONE ====="'
    idx = content.index(marker)
    rest = content[idx:]
    newline = rest.index("\n")
    return rest[newline + 1:].strip("\n")


def _headshots_guard_block() -> str:
    """抽取 run_headshots_all.sh 的双锁 if 段（用于隔离回归）。"""
    src = HEADSHOTS_SCRIPT.read_text(encoding="utf-8")
    i1 = src.index('if pgrep -f "crawl_br_headshots.py"')
    i2 = src.index('if pgrep -f "crawl_br_gamelog.py"')
    seg1 = src[i1:src.index("fi", i1) + 2]
    seg2 = src[i2:src.index("fi", i2) + 2]
    return seg1 + "\n" + seg2 + "\necho GUARD_PASSED\n"


# ── 受控 harness 构建（不碰真实爬取） ───────────────────────────────────────
def _write_stub_recorder(tmp_path: Path) -> Path:
    """一个 stub ``python``：记录每次被调用（命令名 + 参数），按 env 决定退出码。"""
    rec = tmp_path / "stub_py.sh"
    rec.write_text(
        textwrap.dedent("""\
        #!/usr/bin/env bash
        # stub recorder：替代真实 .venv/bin/python
        ORDER_LOG="${ORDER_LOG:-/tmp/order.log}"
        SCRIPT_NAME="$(basename "$1")"
        echo "CALL ${SCRIPT_NAME} $*" >> "$ORDER_LOG"
        if [ "$SCRIPT_NAME" = "crawl_br_headshots.py" ]; then
          exit "${STUB_HEADSHOT_EXIT:-0}"
        fi
        exit "${STUB_EXIT:-0}"
        """),
        encoding="utf-8",
    )
    rec.chmod(0o755)
    return rec


def _write_fake_pgrep(tmp_path: Path) -> Path:
    """fake pgrep：仅当模式为 crawl_br_headshots.py 且 FAKE_HEADSHOTS_RUNNING=1 时返回 0。"""
    fake = tmp_path / "pgrep"
    fake.write_text(
        textwrap.dedent("""\
        #!/usr/bin/env bash
        # fake pgrep：受 FAKE_HEADSHOTS_RUNNING 控制，忽略真实进程
        pattern=""
        for a in "$@"; do
          case "$a" in
            -*) ;;
            *) pattern="$a" ;;
          esac
        done
        if [ "$pattern" = "crawl_br_headshots.py" ] && [ "${FAKE_HEADSHOTS_RUNNING:-0}" = "1" ]; then
          exit 0
        fi
        exit 1
        """),
        encoding="utf-8",
    )
    fake.chmod(0o755)
    return fake


def _write_fake_pgrep_headshots(tmp_path: Path, running_pattern: str) -> Path:
    """fake pgrep（headshots 回归用）：仅当模式 == running_pattern 时返回 0。"""
    fake = tmp_path / "pgrep"
    fake.write_text(
        textwrap.dedent("""\
        #!/usr/bin/env bash
        pattern=""
        for a in "$@"; do
          case "$a" in
            -*) ;;
            *) pattern="$a" ;;
          esac
        done
        if [ "$pattern" = "__RUNNING_PATTERN__" ]; then
          exit 0
        fi
        exit 1
        """).replace("__RUNNING_PATTERN__", running_pattern),
        encoding="utf-8",
    )
    fake.chmod(0o755)
    return fake


def _build_relay_harness(tmp_path: Path,
                          headshots_running: bool,
                          headshot_fail: bool) -> tuple[Path, dict]:
    """构建受控 harness：stub PY + fake pgrep + 抽取的真实 gamelog 循环 + 抽取的真实接力块。"""
    recorder = _write_stub_recorder(tmp_path)
    _write_fake_pgrep(tmp_path)

    order_log = tmp_path / "order.log"
    gamelog_log = tmp_path / "gamelog.log"
    headshot_log = tmp_path / "headshot_relay.log"

    lines: list[str] = []
    lines.append("#!/usr/bin/env bash")
    lines.append("set -a")
    lines.append('export ORDER_LOG="%s"' % order_log)
    lines.append('export LOG="%s"' % gamelog_log)
    lines.append('export HEADSHOT_LOG="%s"' % headshot_log)
    lines.append('export PY="%s"' % recorder)
    lines.append('export PATH="%s:${PATH}"' % tmp_path)
    lines.append("export FAKE_HEADSHOTS_RUNNING=%s" % ("1" if headshots_running else "0"))
    lines.append("export STUB_HEADSHOT_EXIT=%s" % ("3" if headshot_fail else "0"))
    lines.append("set +a")
    lines.append('cd "%s"' % ROOT)
    lines.append("# --- gamelog 季节循环（从源码抽取，stub PY 替代真实爬虫） ---")
    lines.append(_gamelog_loop_block())
    lines.append("# --- 接力块（从源码逐字抽取） ---")
    lines.append(_relay_block())
    harness = tmp_path / "relay_harness.sh"
    harness.write_text("\n".join(lines) + "\n", encoding="utf-8")
    harness.chmod(0o755)

    paths = {"order_log": order_log, "gamelog_log": gamelog_log,
             "headshot_log": headshot_log}
    return harness, paths


def _calls(order_log: Path) -> list[str]:
    if not order_log.exists():
        return []
    # errors="replace"：受控 harness 的 tee 日志里偶发多字节字符被截断（环境 artifact，
    # 不影响接力逻辑断言；order_log 本身为纯 ASCII 调用记录）。
    return [l for l in order_log.read_text(encoding="utf-8", errors="replace").splitlines()
            if l.strip()]


# ── 1) 语法 ───────────────────────────────────────────────────────────────
def test_syntax_gamelog_ok():
    proc = subprocess.run(["bash", "-n", str(SCRIPT)], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr


def test_syntax_headshots_ok():
    proc = subprocess.run(["bash", "-n", str(HEADSHOTS_SCRIPT)], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr


# ── 2) 静态断言 ───────────────────────────────────────────────────────────
def test_relay_block_after_gamelog_loop():
    """接力块（self-guard pgrep）必须位于 gamelog ``for...done`` 循环之后。"""
    lines = _read_lines()
    for_i = next(i for i, l in enumerate(lines) if l.strip().startswith("for S in"))
    done_i = next(d for d in range(len(lines))
                  if lines[d].strip() == "done" and d > for_i)
    relay_guard_i = next(i for i, l in enumerate(lines)
                         if 'pgrep -f "crawl_br_headshots.py"' in l)
    assert done_i < relay_guard_i, (
        "接力 self-guard 必须在 gamelog 循环 done(行 %d) 之后，实际在行 %d" % (done_i, relay_guard_i)
    )


def test_relay_block_calls_headshots_resume():
    assert "crawl_br_headshots.py --resume" in _relay_block()


def test_relay_does_not_invoke_run_headshots_all():
    """设计要点：接力直接调 python，而非 run_headshots_all.sh（避免被其 gamelog 互斥锁误拦）。

    注意：接力块的*注释*会提到 run_headshots_all.sh 以解释“为何不调”，因此只断言
    非注释代码行中不出现对它的执行调用。
    """
    for line in _relay_block().splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        assert "run_headshots_all.sh" not in stripped, (
            "接力块不应执行 run_headshots_all.sh，发现于代码行: %s" % stripped
        )


def test_env_exports_before_relay_block():
    """env 导出（BR_COOKIE_FILE / BROWSER_BACKEND / CHROME_CDP_URL / source .env）在接力块之前。"""
    content = SCRIPT.read_text(encoding="utf-8")
    relay_idx = content.index("GAMELOG ALL DONE")
    head = content[:relay_idx]
    assert "export BROWSER_BACKEND=cdp" in head
    assert "export CHROME_CDP_URL=http://127.0.0.1:9222" in head
    assert "export BR_COOKIE_FILE=/tmp/br_cf_cookies.json" in head
    assert ".env" in head and "set -a" in head


def test_headshot_log_defined():
    assert "HEADSHOT_LOG=" in SCRIPT.read_text(encoding="utf-8")


# ── 3) 接力逻辑受控模拟（核心） ─────────────────────────────────────────────
def test_scenario_a_normal_relay_calls_once_after_gamelog(tmp_path):
    """场景 A：正常接力 —— pgrep 判定 headshots 未在跑 → 恰好调用一次 --resume，且串行在 gamelog 之后。"""
    harness, paths = _build_relay_harness(tmp_path, headshots_running=False, headshot_fail=False)
    proc = subprocess.run(["bash", str(harness)], capture_output=True, text=True,
                          errors="replace", timeout=60)
    assert proc.returncode == 0, proc.stdout + proc.stderr

    calls = _calls(paths["order_log"])
    headshot_calls = [c for c in calls if "crawl_br_headshots.py" in c]
    assert len(headshot_calls) == 1, "headshots 应被恰好调用一次，实际: %s" % calls
    assert "--resume" in headshot_calls[0], "调用必须带 --resume"

    gamelog_calls = [i for i, c in enumerate(calls) if "crawl_br_gamelog.py" in c]
    assert len(gamelog_calls) == 6, "gamelog 6 个季节应全部跑完，实际: %s" % calls
    headshot_idx = next(i for i, c in enumerate(calls) if "crawl_br_headshots.py" in c)
    assert max(gamelog_calls) < headshot_idx, (
        "headshots 必须等待 gamelog 全部季跑完后才调用（串行铁证），调用序: %s" % calls
    )


def test_scenario_b_self_guard_skips_when_headshots_running(tmp_path):
    """场景 B：self-guard —— pgrep 判定已有 headshots 在跑 → 跳过调用，绝不强行并行。"""
    harness, paths = _build_relay_harness(tmp_path, headshots_running=True, headshot_fail=False)
    proc = subprocess.run(["bash", str(harness)], capture_output=True, text=True,
                          errors="replace", timeout=60)
    assert proc.returncode == 0, proc.stdout + proc.stderr

    calls = _calls(paths["order_log"])
    headshot_calls = [c for c in calls if "crawl_br_headshots.py" in c]
    assert len(headshot_calls) == 0, "已有 headshots 在跑时必须跳过接力，实际: %s" % calls

    gamelog_calls = [c for c in calls if "crawl_br_gamelog.py" in c]
    assert len(gamelog_calls) == 6, "gamelog 不受影响应照常跑完，实际: %s" % calls

    gamelog_log = paths["gamelog_log"].read_text(encoding="utf-8", errors="replace")
    assert "跳过接力" in gamelog_log, "应打印跳过接力的提示"


def test_scenario_c_failure_fallback_continues(tmp_path):
    """场景 C：失败兜底 —— headshots stub 返回非 0 → 脚本不中断，继续到「全部流程结束」并提示失败。"""
    harness, paths = _build_relay_harness(tmp_path, headshots_running=False, headshot_fail=True)
    proc = subprocess.run(["bash", str(harness)], capture_output=True, text=True,
                          errors="replace", timeout=60)
    assert proc.returncode == 0, "接力失败不应中断整脚本，实际 rc=%d\n%s" % (
        proc.returncode, proc.stdout + proc.stderr)

    calls = _calls(paths["order_log"])
    headshot_calls = [c for c in calls if "crawl_br_headshots.py" in c]
    assert len(headshot_calls) == 1, "headshots 应被尝试调用一次（即便随后失败），实际: %s" % calls

    gamelog_log = paths["gamelog_log"].read_text(encoding="utf-8", errors="replace")
    assert "接力失败" in gamelog_log, "应打印接力失败提示"
    assert "全部流程结束" in gamelog_log, "脚本应继续跑到全部流程结束（兜底）"


# ── 4) 独立脚本回归：run_headshots_all.sh 双锁仍完好 ────────────────────────
def test_regression_headshots_double_lock_static():
    """静态确认 run_headshots_all.sh 双锁两段仍在（本次改动未触碰）。"""
    content = HEADSHOTS_SCRIPT.read_text(encoding="utf-8")
    assert 'pgrep -f "crawl_br_headshots.py"' in content
    assert 'pgrep -f "crawl_br_gamelog.py"' in content
    assert content.count("exit 1") >= 2


def test_regression_headshots_self_lock_fires(tmp_path):
    """隔离：自身锁（headshots 在跑）命中 → exit 1 且不打印 GUARD_PASSED。"""
    fake = _write_fake_pgrep_headshots(tmp_path, "crawl_br_headshots.py")
    guard = tmp_path / "guard.sh"
    guard.write_text(_headshots_guard_block(), encoding="utf-8")
    guard.chmod(0o755)
    env = dict(os.environ, PATH="%s:%s" % (tmp_path, os.environ.get("PATH", "")))
    proc = subprocess.run(["bash", str(guard)], env=env,
                          capture_output=True, text=True, timeout=30)
    assert proc.returncode == 1
    assert "GUARD_PASSED" not in proc.stdout


def test_regression_headshots_gamelog_lock_fires(tmp_path):
    """隔离：gamelog 互斥锁命中 → exit 1 且不打印 GUARD_PASSED。"""
    fake = _write_fake_pgrep_headshots(tmp_path, "crawl_br_gamelog.py")
    guard = tmp_path / "guard.sh"
    guard.write_text(_headshots_guard_block(), encoding="utf-8")
    guard.chmod(0o755)
    env = dict(os.environ, PATH="%s:%s" % (tmp_path, os.environ.get("PATH", "")))
    proc = subprocess.run(["bash", str(guard)], env=env,
                          capture_output=True, text=True, timeout=30)
    assert proc.returncode == 1
    assert "GUARD_PASSED" not in proc.stdout


def test_regression_headshots_both_idle_passes(tmp_path):
    """隔离：双空闲 → 两锁都不触发 → GUARD_PASSED（证明 guard 不会永远 exit 1）。"""
    fake = _write_fake_pgrep_headshots(tmp_path, "")
    guard = tmp_path / "guard.sh"
    guard.write_text(_headshots_guard_block(), encoding="utf-8")
    guard.chmod(0o755)
    env = dict(os.environ, PATH="%s:%s" % (tmp_path, os.environ.get("PATH", "")))
    proc = subprocess.run(["bash", str(guard)], env=env,
                          capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0
    assert "GUARD_PASSED" in proc.stdout
