#!/usr/bin/env python3
"""打包链路一致性回归测试（轻量，CI 可跑，不需要安装 PyInstaller）。

为什么需要
----------
``nbacore.spec`` 是 v8.0.0 早期的手写清单：只声明了 7 个 router，
而 ``backend/app.py`` 现在 include 26 个；``datas`` 也漏了 backend 实际依赖的
``common.nba_paths`` / ``common.season_type_norm`` / ``viz.theme``。
这类失修**不会让 CI 变红**，只会在用户拿到 app 后表现为「某些页面打不开」。

本测试把「spec 与真实代码同步」变成可执行断言：
- 不允许回退到手写 router 清单
- backend 新增 router 时，必须能被收集且可导入
- spec 声明的数据资源必须真实存在
- frozen 适配（``_MEIPASS``）不许被删
- 不许再传 PyInstaller 6 已移除的参数

运行：pytest tests/test_packaging_spec.py -v
"""
from __future__ import annotations

import importlib
import re
import sys
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
SPEC = PROJ / "nbacore.spec"
MAIN = PROJ / "main.py"
BUILD_SH = PROJ / "scripts" / "build_app.sh"


def _spec_text() -> str:
    return SPEC.read_text(encoding="utf-8")


def _router_names() -> list[str]:
    """从 backend/app.py 解析实际 include_router 的模块名。"""
    src = (PROJ / "backend" / "app.py").read_text(encoding="utf-8")
    return sorted(set(re.findall(r"app\.include_router\((\w+)\.router\)", src)))


def test_spec_exists_and_uses_submodule_collection():
    """禁止回退到手写 hiddenimports 清单（旧 spec 只覆盖 7/26 个 router）。"""
    src = _spec_text()
    assert SPEC.is_file()
    assert "collect_submodules(" in src, "spec 必须自动收集子模块，不要手写清单"
    assert 'collect_submodules("backend")' in src
    # 旧写法：逐条列举 backend.api.routers.xxx
    assert not re.search(r'"backend\.api\.routers\.\w+"', src), \
        "spec 里仍有手写 router 清单 —— 新增路由时必然过时"


def test_every_router_is_importable():
    """backend/app.py 实际 include 的每个 router 都必须可导入。

    若某个 router import 了未被 spec 覆盖的顶层模块，这一步会先在本地暴露，
    而不是等到打包产物在用户机器上 ModuleNotFoundError。
    """
    names = _router_names()
    assert len(names) >= 20, f"解析到的 router 数异常: {len(names)}"
    for name in names:
        mod = importlib.import_module(f"backend.api.routers.{name}")
        assert hasattr(mod, "router"), f"{name} 没有 router 对象"


def test_spec_declares_toplevel_dependencies():
    """backend 实际引用的 3 个顶层模块必须在 spec 里显式声明。"""
    src = _spec_text()
    for mod in ("common.nba_paths", "common.season_type_norm", "viz.theme"):
        assert f'"{mod}"' in src, f"spec 缺少 backend 依赖的顶层模块: {mod}"


def test_spec_datas_exist():
    """spec datas 里点名的关键资源必须真实存在（避免打出缺资源的空壳）。"""
    for rel in ("frontend", "NBAlogo", "viz/theme_tokens.json",
                ".env.example", "db/schema.sql", "main.py"):
        assert (PROJ / rel).exists(), f"spec 依赖的资源不存在: {rel}"
    src = _spec_text()
    for key in ("frontend", "NBAlogo", "theme_tokens.json", ".env.example", "schema.sql"):
        assert key in src, f"spec datas 未包含 {key}"


def test_no_pyinstaller5_only_parameters():
    """PyInstaller 6.x 见到这些参数会直接 TypeError。

    🔴 用 AST 查 ``Analysis(...)`` 的真实关键字参数，不要用「非 # 开头即代码行」
    的字面判据 —— spec 的 docstring 里恰好记录了这几个参数名（历史说明），
    粗糙判据会把它误判成代码（本测试第一版就踩了这个坑）。
    """
    import ast

    tree = ast.parse(_spec_text())
    calls = [n for n in ast.walk(tree)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
             and n.func.id == "Analysis"]
    assert len(calls) == 1, f"spec 里 Analysis 调用数异常: {len(calls)}"
    kws = {kw.arg for kw in calls[0].keywords}
    for bad in ("cipher", "win_no_prefer_redirects", "win_private_assemblies"):
        assert bad not in kws, f"spec 仍含 PyInstaller 6 已移除的参数: {bad}"


def test_frozen_awareness_preserved():
    """config / app 的 sys._MEIPASS 适配不许被删。"""
    for rel in ("backend/core/config.py", "backend/app.py"):
        src = (PROJ / rel).read_text(encoding="utf-8")
        assert 'getattr(sys, "frozen", False)' in src, f"{rel} 丢了 frozen 判断"
        assert "sys._MEIPASS" in src, f"{rel} 丢了 _MEIPASS 资源定位"


def test_main_and_build_script_exist():
    """入口与构建脚本必须存在；构建脚本必须走路径唯一来源。"""
    assert MAIN.is_file()
    assert BUILD_SH.is_file()
    sh = BUILD_SH.read_text(encoding="utf-8")
    assert "common/paths.sh" in sh, "构建脚本必须 source common/paths.sh"
    code_lines = [ln for ln in sh.splitlines()
                  if ln.strip() and not ln.lstrip().startswith("#")]
    joined = "\n".join(code_lines)
    # 🔴 拼接构造，别写整串：门禁 11a 检查「已跟踪 .py 不得含用户目录 /
    #    数据盘根字面量」，且读的是**整份文本、注释行也算**。本文件未入库时
    #    门禁看不见，一提交就会自报违规（与收敛轮 docstring 命中 11a 同类坑）。
    assert ("/Volumes" + "/12T") not in joined
    assert ("/Users" + "/deocheng") not in joined


def test_build_extras_declared():
    """PyInstaller 必须作为 build extra 声明，不能混进生产依赖。"""
    pyproject = (PROJ / "pyproject.toml").read_text(encoding="utf-8")
    assert re.search(r'^build\s*=\s*\["pyinstaller', pyproject, re.M), \
        "[project.optional-dependencies] 缺少 build extras"


def test_runtime_guard_skips_source_scan_in_frozen(monkeypatch):
    """frozen 下源码不在磁盘 —— guard 应明确 skipped，不能把 /health 拖成 degraded。

    实测（2026-11-11）：旧实现 open(db_mod.__file__) 抛 FileNotFoundError，
    run_startup_checks 兜成 ok=False → 打包版 /health 永远 status=degraded。
    """
    from backend.core import runtime_guard

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    results = runtime_guard.run_startup_checks()
    guard = results["no_forbidden_patterns"]
    assert guard["ok"] is True, guard
    assert guard["detail"].get("skipped"), "frozen 下必须标明 skipped 及原因"
    assert runtime_guard.all_passed(results), "frozen 下 3 个 guard 应全过"


def test_runtime_guard_scans_source_when_available(monkeypatch):
    """非 frozen（源码在磁盘）时，静态扫描必须照常执行。"""
    from backend.core import runtime_guard

    monkeypatch.delattr(sys, "frozen", raising=False)
    guard = runtime_guard.run_startup_checks()["no_forbidden_patterns"]
    assert guard["ok"] is True, guard
    assert guard["detail"].get("scanned") == "backend.core.db"


def test_main_prints_startup_selfcheck():
    """EXE 启动横幅必须给出 DB 前置条件自检（只打印，不改 router 行为）。

    无凭据 / 无 PG 时用户双击只看到 /health degraded，控制台应直接说明原因。
    自检必须走轻量 TCP 探测，不能在启动前创建连接池。
    """
    src = MAIN.read_text(encoding="utf-8")
    assert "_startup_probe" in src
    assert "is_port_open()" in src, "启动自检应走轻量 TCP 探测"
    assert "DB_PASSWORD" in src, "必须提示口令是否配置"
    assert "reconfigure(line_buffering=True)" in src, \
        "frozen 下 stdout 是块缓冲，自检横幅必须强制行缓冲才能实时落盘"
    assert "init_pool()" not in src, "启动前不要创建连接池（凭据缺失会拖慢/抛异常）"
