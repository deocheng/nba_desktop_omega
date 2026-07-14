# -*- mode: python ; coding: utf-8 -*-
"""NBACore Studio v8 — PyInstaller spec.

Builds a single-file executable with backend + frontend + logos.
Usage: pyinstaller nbacore.spec
"""

from pathlib import Path

project_root = Path.cwd()

# ── Data files to bundle ──
datas = [
    (str(project_root / "frontend"), "frontend"),
    (str(project_root / "NBAlogo"), "NBAlogo"),
]

# Collect backend package
hiddenimports = [
    "backend",
    "backend.app",
    "backend.core.config",
    "backend.core.db",
    "backend.core.logging",
    "backend.core.runtime_guard",
    "backend.api.schemas",
    "backend.api.routers.players",
    "backend.api.routers.metrics",
    "backend.api.routers.vs",
    "backend.api.routers.batch",
    "backend.api.routers.context",
    "backend.api.routers.export",
    "backend.api.routers.monitor",
    "backend.services.metric_engine",
    "backend.services.metric_engine.metrics.basic",
    "backend.services.metric_engine.metrics.advanced",
    "backend.services.metric_engine.metrics.composite",
    "backend.services.context_engine",
    "backend.services.context_engine.similar_players",
    "backend.services.context_engine.role_evolution",
    "backend.services.context_engine.trend_analysis",
    "backend.services.export_service",
    "backend.data_layer.schema",
    "backend.data_layer.schema_validator",
    "backend.data_layer.batch_loader",
    "backend.data_layer.temp_loader",
    "backend.data_layer.joins",
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
        "tkinter",
        "matplotlib",
        "scipy",
        "IPython",
        "jupyter",
        "notebook",
        "pytest",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=None,
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
