# -*- mode: python ; coding: utf-8 -*-
"""NBACore Studio v8 — PyInstaller spec (one-file local web app).

Builds a single-file executable that starts uvicorn (FastAPI) and opens the
bundled static frontend in the default browser. PostgreSQL stays **external**:
the app degrades gracefully (``/health`` reports ``database_connected=false``)
when no database is reachable.

Usage:
    .venv/bin/python -m PyInstaller --noconfirm nbacore.spec
or simply:
    bash scripts/build_app.sh

🔴 维护铁律（2026-11-11 落地时踩过的坑）
------------------------------------------
1. **不要用 ``Path.cwd()`` 定位仓库根** —— 从别的目录调用 spec 时 cwd 不是仓库根。
   用 PyInstaller 注入的 ``SPECPATH``（spec 文件所在目录）。
2. **不要手写 hiddenimports 清单** —— 旧 spec 只列了 7 个 router，
   而 ``backend/app.py`` 实际 include 26 个；手写清单必然随新增路由过时。
   改用 ``collect_submodules("backend")`` 自动收集。
3. **backend 依赖 3 个顶层模块**（旧 spec 完全没声明）：
   ``common.nba_paths`` / ``common.season_type_norm`` / ``viz.theme``。
   只显式收这 3 个，不要 ``collect_submodules("common")`` —— 那会把
   ``common.browser`` 连带 Playwright / undetected-chromedriver 拖进包里。
4. **别传 PyInstaller 6 已移除的参数**：``cipher``、``win_no_prefer_redirects``、
   ``win_private_assemblies`` 在 6.x 会直接 TypeError。
"""
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

# PyInstaller 把 spec 所在目录注入为 SPECPATH；保留 cwd 兜底以防版本差异。
project_root = Path(globals().get("SPECPATH", ".")).resolve()

# ── 随包携带的数据文件（(源, 目标目录) 均相对 bundle root）──
datas = [
    (str(project_root / "frontend"), "frontend"),
    (str(project_root / "NBAlogo"), "NBAlogo"),
    # viz.theme 的令牌快照；compat_vars() 会读它
    (str(project_root / "viz" / "theme_tokens.json"), "viz"),
    # 首次启动的连接配置模板（真实 .env / 口令绝不随包分发）
    (str(project_root / ".env.example"), "."),
    # 结构 DDL：便于在目标机初始化外部 PG（仅结构，不含数据）
    (str(project_root / "db" / "schema.sql"), "db"),
    # Studio 能力目录：编排顺序与参数的唯一来源，必须随包分发
    (str(project_root / "studio" / "manifest.json"), "studio"),
]

# ── 自动收集 backend 全部子模块，排除测试模块（否则把 pytest 拖进包）──
hiddenimports = [
    m for m in collect_submodules("backend")
    if ".tests" not in m and not m.endswith("tests")
]
# backend 实际引用的 3 个顶层模块（纯标准库，不会牵连爬虫依赖）
hiddenimports += [
    "common.nba_paths",
    "common.season_type_norm",
    "viz.theme",
]

a = Analysis(
    ["main.py"],
    pathex=[str(project_root)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # GUI / 科学计算（原 spec 已有）
        "tkinter", "matplotlib", "scipy", "IPython", "jupyter", "notebook",
        # 测试
        "pytest",
        # 爬虫工具箱：backend 不 import，排除以显著减小体积
        "playwright", "playwright_stealth", "selenium",
        "undetected_chromedriver", "curl_cffi", "bs4", "lxml",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="NBACore",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
