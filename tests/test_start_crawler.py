#!/usr/bin/env python3
# =============================================================================
# tests/test_start_crawler.py
#
# 对 start_crawler.sh 的受控回归验收（QA 固化）。
#
# 设计原则（与手测 harness 一致）：
#   - 不 live 启停 Postgres / Chrome / 爬虫，不删真实 profile，不连真实 DB。
#   - 所有外部依赖（lsof/curl/pg_isready/pg_ctl/launch_chrome_cdp.sh/pgrep/tee）
#     由本测试在 tmp_path 内生成的 stub 覆盖。
#   - 双锁委托验证：直接跑真实 run_headshots_all.sh / run_gamelog_all.sh，
#     用 stub pgrep 模拟"已在跑"，stub tee 防止真实日志被写。
#
# 运行：pytest tests/test_start_crawler.py -v
# =============================================================================
import os
import re
import subprocess
from pathlib import Path

import pytest

PROJ = Path(__file__).resolve().parent.parent
SRC = PROJ / "start_crawler.sh"
REAL_HS = PROJ / "run_headshots_all.sh"
REAL_GL = PROJ / "run_gamelog_all.sh"

# ---------------------------------------------------------------------------
# stub 模板（@@STATE@@ 等占位符在 fixture 中替换；其余为字面 bash）
# ---------------------------------------------------------------------------
STUB_TEMPLATES = {
    "lsof": '''#!/usr/bin/env bash
[ -f "@@STATE@@/.pg_up" ] && exit 0 || exit 1
''',
    "pg_isready": '''#!/usr/bin/env bash
[ -f "@@STATE@@/.pg_up" ] && exit 0 || exit 1
''',
    "curl": '''#!/usr/bin/env bash
URL=""
for a in "$@"; do case "$a" in http*) URL="$a";; esac; done
if echo "$URL" | grep -q "json/version"; then
  [ -f "@@STATE@@/.chrome_up" ] && exit 0 || exit 1
else
  [ -f "@@STATE@@/.pg_up" ] && exit 0 || exit 1
fi
''',
    "pg_ctl": '''#!/usr/bin/env bash
echo "$*" > "@@STATE@@/pg_ctl_args"
touch "@@STATE@@/.pg_ctl_called"
touch "@@STATE@@/.pg_up"
exit 0
''',
    "pgrep": '''#!/usr/bin/env bash
HIT="${QA_HIT:-crawl_br_headshots.py}"
for a in "$@"; do case "$a" in *"$HIT"*) exit 0;; esac; done
exit 1
''',
    "tee": '''#!/usr/bin/env bash
cat
''',
}

LAUNCH_TEMPLATE = '''#!/usr/bin/env bash
touch "@@STATE@@/.chrome_up"
touch "@@STATE@@/.chrome_called"
exit 0
'''

DRIVER_PREAMBLE = '''#!/usr/bin/env bash
set -o pipefail
export PATH="@@STUBS@@:$PATH"
export PG_CTL_BIN="@@STUBS@@/pg_ctl"
export START_CRAWLER_LIB=1
cd "@@PGDATA@@"
. "@@SRC@@"
PROJ_ROOT="@@PROJROOT@@"
CDP_PROFILE="@@CDP@@"
PG_DATADIR="@@PGDATA@@"
PG_PORT=5433
CDP_PORT=9222
STATE="@@STATE@@"
reset_state() { rm -f "$STATE/.pg_up" "$STATE/.pg_ctl_called" "$STATE/pg_ctl_args" "$STATE/.chrome_up" "$STATE/.chrome_called"; }
'''

SCENARIO_BODIES = {
    "a": '''reset_state; touch "$STATE/.pg_up"
ensure_postgres >/dev/null 2>&1; RC=$?
echo "PGCTL_CALLED=$([ -f "$STATE/.pg_ctl_called" ] && echo 1 || echo 0)"
echo "RC=$RC"
''',
    "b": '''reset_state
ensure_postgres >/dev/null 2>&1; RC=$?
echo "PGCTL_CALLED=$([ -f "$STATE/.pg_ctl_called" ] && echo 1 || echo 0)"
echo "ARGS=$(cat "$STATE/pg_ctl_args" 2>/dev/null)"
echo "RC=$RC"
''',
    "c": '''reset_state; touch "$STATE/.chrome_up"
ensure_chrome >/dev/null 2>&1; RC=$?
echo "CHROME_CALLED=$([ -f "$STATE/.chrome_called" ] && echo 1 || echo 0)"
echo "RC=$RC"
''',
    "d": '''reset_state
touch "@@CDP@@/SingletonLock" "@@CDP@@/SingletonCookie" "@@CDP@@/SingletonSocket"
touch "@@USERP@@/SingletonLock" "@@USERP@@/SingletonCookie" "@@USERP@@/SingletonSocket"
ensure_chrome >/dev/null 2>&1; RC=$?
echo "CHROME_CALLED=$([ -f "$STATE/.chrome_called" ] && echo 1 || echo 0)"
echo "CDP_LOCK_REMOVED=$([ ! -e "@@CDP@@/SingletonLock" ] && echo 1 || echo 0)"
echo "USER_LOCK_KEPT=$([ -e "@@USERP@@/SingletonLock" ] && echo 1 || echo 0)"
echo "RC=$RC"
''',
}


@pytest.fixture
def qa(tmp_path):
    """在 tmp_path 内构建受控 stub 环境，返回路径字典。"""
    stubs = tmp_path / "stubs"
    state = tmp_path / "state"
    projroot = tmp_path / "projroot"
    cdp = tmp_path / "cdp_profile"
    userp = tmp_path / "user_default_profile"
    pgdata = tmp_path / "pg_data"
    for d in (stubs, state, projroot, cdp, userp, pgdata):
        d.mkdir(parents=True, exist_ok=True)

    repl = {
        "@@STATE@@": str(state),
        "@@STUBS@@": str(stubs),
        "@@PROJROOT@@": str(projroot),
        "@@CDP@@": str(cdp),
        "@@USERP@@": str(userp),
        "@@PGDATA@@": str(pgdata),
        "@@SRC@@": str(SRC),
    }

    for name, tpl in STUB_TEMPLATES.items():
        (stubs / name).write_text(tpl.replace("@@STATE@@", str(state)))
        os.chmod(stubs / name, 0o755)
    (projroot / "launch_chrome_cdp.sh").write_text(
        LAUNCH_TEMPLATE.replace("@@STATE@@", str(state))
    )
    os.chmod(projroot / "launch_chrome_cdp.sh", 0o755)

    return {
        "stubs": stubs,
        "state": state,
        "projroot": projroot,
        "cdp": cdp,
        "userp": userp,
        "pgdata": pgdata,
        "_repl": repl,
    }


def _write_driver(qa, scenario):
    text = DRIVER_PREAMBLE + SCENARIO_BODIES[scenario]
    for k, v in qa["_repl"].items():
        text = text.replace(k, v)
    p = qa["stubs"].parent / f"driver_{scenario}.sh"
    p.write_text(text)
    os.chmod(p, 0o755)
    return p


def _run_driver(qa, scenario):
    p = _write_driver(qa, scenario)
    r = subprocess.run(
        ["bash", str(p)], capture_output=True, text=True, env=dict(os.environ)
    )
    out = {}
    for line in r.stdout.splitlines():
        m = re.match(r"^([A-Z_]+)=(.*)$", line)
        if m:
            out[m.group(1)] = m.group(2)
    return out, r.returncode, r.stderr


def _run_real(qa, script, hit):
    env = dict(os.environ)
    env["PATH"] = f"{qa['stubs']}:{env['PATH']}"
    env["QA_HIT"] = hit
    r = subprocess.run(
        ["bash", str(script)], capture_output=True, text=True, env=env
    )
    return r.returncode, r.stdout + r.stderr


# ===========================================================================
# PART 1: 静态 + 红线（离线）
# ===========================================================================
def test_syntax_check():
    r = subprocess.run(["bash", "-n", str(SRC)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def test_no_kill_except_l0():
    src = SRC.read_text()
    # 红线：不存在 pkill / killall
    assert not re.search(r"pkill|killall", src), "出现 pkill/killall"
    # 真正的 kill 命令调用（忽略注释行里的字面词 kill）只允许 kill -0
    for m in re.finditer(r"(?m)^(\d+):(.*)$", src):
        line = m.group(2)
        if line.lstrip().startswith("#"):
            continue
        for km in re.finditer(r"\bkill\b", line):
            rest = line[km.start():]
            assert re.match(r"kill\s+-0\b", rest), (
                f"非 -0 的 kill 语句: line {m.group(1)}: {line.strip()}"
            )


def test_no_backslash_continuation():
    src = SRC.read_text()
    assert not re.search(r"\\$", src), "存在行尾反斜杠续行"


def test_key_constructs():
    src = SRC.read_text()
    assert 'cd "$(dirname "$0")"' in src
    assert "set -a" in src and "set +a" in src
    assert '. "$PROJ_ROOT/.env"' in src
    assert "export BROWSER_BACKEND=" in src
    assert "export CHROME_CDP_URL=" in src
    assert "export BR_COOKIE_FILE=" in src


def test_default_params():
    src = SRC.read_text()
    assert 'PG_DATADIR="${PG_DATADIR:-/Users/deocheng/nba_pg}"' in src
    assert 'PG_PORT="${PG_PORT:-5433}"' in src
    assert 'CDP_PORT="${CDP_PORT:-9222}"' in src
    assert 'CDP_PROFILE="${CDP_PROFILE:-/tmp/chrome_cdp_profile}"' in src


def test_delegation_not_bypass():
    src = SRC.read_text()
    assert 'nohup bash "$CRAWL_SCRIPT"' in src
    assert not re.search(r"crawl_br_(headshots|gamelog)\.py", src), (
        "脚本直接调用 crawl_br_*.py 会绕过双锁"
    )


# ===========================================================================
# PART 2: 基础设施探测 / 拉起（受控 stub）
# ===========================================================================
def test_infra_pg_up_no_start(qa):
    out, rc, err = _run_driver(qa, "a")
    assert out.get("PGCTL_CALLED") == "0", err
    assert out.get("RC") == "0"


def test_infra_pg_down_starts_with_correct_args(qa):
    out, rc, err = _run_driver(qa, "b")
    assert out.get("PGCTL_CALLED") == "1", err
    args = out.get("ARGS", "")
    assert "-p 5433" in args, f"pg_ctl 参数缺少 -p 5433: {args}"
    assert "-D" in args, f"pg_ctl 参数缺少 -D: {args}"
    assert args.rstrip().endswith("start"), f"pg_ctl 参数缺少 start: {args}"
    assert out.get("RC") == "0"


def test_infra_chrome_up_no_launch(qa):
    out, rc, err = _run_driver(qa, "c")
    assert out.get("CHROME_CALLED") == "0", err
    assert out.get("RC") == "0"


def test_infra_chrome_down_launch_and_profile_isolation(qa):
    out, rc, err = _run_driver(qa, "d")
    assert out.get("CHROME_CALLED") == "1", err
    assert out.get("CDP_LOCK_REMOVED") == "1", "专用 profile 锁未清理"
    assert out.get("USER_LOCK_KEPT") == "1", "误删了用户默认 profile 锁！"
    assert out.get("RC") == "0"


# ===========================================================================
# PART 3: 双锁委托不绕过（跑真实 run_*_all.sh，stub pgrep/tee）
# ===========================================================================
def test_double_lock_headshots_self(qa):
    rc, out = _run_real(qa, REAL_HS, "crawl_br_headshots.py")
    assert rc == 1, out
    assert re.search(r"拒绝并行|已在跑|拒绝", out), out


def test_double_lock_headshots_gamelog_mutex(qa):
    rc, out = _run_real(qa, REAL_HS, "crawl_br_gamelog.py")
    assert rc == 1, out
    assert re.search(r"gamelog|拒绝并行|已在跑", out), out


def test_double_lock_gamelog_self(qa):
    rc, out = _run_real(qa, REAL_GL, "crawl_br_gamelog.py")
    assert rc == 1, out
    assert re.search(r"拒绝并行|已在跑|拒绝", out), out


def test_double_lock_scripts_regression_no_kill():
    for f in (REAL_HS, REAL_GL):
        txt = f.read_text()
        assert not re.search(r"pkill|killall|\bkill\b", txt), f"{f.name} 出现 kill 语句"
        assert 'pgrep -f "crawl_br_headshots.py"' in txt or 'pgrep -f "crawl_br_gamelog.py"' in txt
