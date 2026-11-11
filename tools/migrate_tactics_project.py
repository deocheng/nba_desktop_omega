#!/usr/bin/env python3
"""一次性迁移器：把战术分析项目的**代码层**并入主仓库 ``tactics/``。

背景
----
战术分析项目原本整体躺在数据盘 ``action_analysis/``：代码只有约 8MB，
但同目录混着 43GB 素材/语料/权重（action_work 21G、bonsai 13G、clips 9G、
reports 982M、backups 1.8G、.venv 与 yolov8n.pt）。整目录进 git 不可行。

本工具做「代码与数据分离」：

1. 把代码/配置/文档（.py/.sh/.md/.yaml/.toml/.txt/.cff + vocab/*.json）
   按原相对路径复制到 ``REPO_ROOT/tactics/``（纳入 git）；
2. 数据盘原位置把这些文件换成**指回 tactics/ 的软链** —— 于是历史脚本里的
   绝对路径 ``.../action_analysis/...`` 在运行时仍然有效，读写落点零变化；
3. 大素材、权重、.venv、backups、第三方 RelateAnything 原封不动留在外置盘。

工程约束
--------
- **先备份再删**：原文件先 copy2 到 ``.trash/tactics_pre_migration_20261111/``
  （同卷、可回滚），确认备份成功才 unlink + symlink。
- **零硬编码路径**：源/目标根一律取自 ``common.nba_paths``，本文件不含绝对路径字面量。
- **不递归读大文件**：rglob 只列目录项，不读取素材内容。
- 支持 ``--dry-run`` / ``--apply`` / ``--rollback``。

用法：
    python tools/migrate_tactics_project.py --dry-run
    python tools/migrate_tactics_project.py --apply
    python tools/migrate_tactics_project.py --rollback
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from common import nba_paths as nba_paths  # noqa: E402

CODE_SUFFIXES = {".py", ".sh", ".md", ".yaml", ".yml", ".toml", ".txt", ".cff"}
EXCLUDE_PARTS = {
    ".venv", "backups", "RelateAnything", "__pycache__", ".git",
    ".pytest_cache", ".ruff_cache", ".mypy_cache",
}
#: 第三方 / 构建 / 模型目录 —— 里面的 .py/.md/.txt 都不是本项目源码
THIRD_PARTY_PARTS = {
    "node_modules", "build-mac", "CMakeFiles", "llama.cpp",
    "community-benchmarks", "weights", "poc_frames", "demos",
    "assets", "bin", "_scratch", "models", ".github",
}
#: 只有 vocab/ 下的 json 是**配置**，随代码入库；其余 json 都是数据产物
CONFIG_JSON_TOP = {"vocab"}
BACKUP_DIR = REPO_ROOT / ".trash" / "tactics_pre_migration_20261111"


def _should_migrate(path: Path, rel: Path) -> bool:
    """判定是否属于「本项目代码层」。已存在的软链直接跳过（幂等）。

    🔴 ``bonsai/`` 是克隆的第三方仓库（自带 .git、llama.cpp、node_modules、
    构建产物），只收它**顶层**的自写脚本与 POC 文档；嵌套内容一律留盘。
    """
    parts = rel.parts
    if any(part in EXCLUDE_PARTS for part in parts):
        return False
    if path.is_symlink():
        return False
    if parts and parts[0] == "bonsai":
        if len(parts) != 2:
            return False
        return path.suffix == ".py" or path.name.startswith("BONSAI_POC_")
    if any(part in THIRD_PARTY_PARTS for part in parts):
        return False
    if path.suffix in CODE_SUFFIXES or path.name == ".gitignore":
        return True
    return path.suffix == ".json" and bool(parts) and parts[0] in CONFIG_JSON_TOP


def _targets(src_root: Path) -> list[Path]:
    return sorted(
        p for p in src_root.rglob("*")
        if p.is_file() and _should_migrate(p, p.relative_to(src_root))
    )


def _apply(files: list[Path], src_root: Path, dst_root: Path) -> None:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    dst_root.mkdir(parents=True, exist_ok=True)
    total = 0
    for src in files:
        rel = src.relative_to(src_root)
        backup = BACKUP_DIR / rel
        backup.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, backup)
        if not backup.is_file() or backup.stat().st_size != src.stat().st_size:
            raise RuntimeError(f"备份校验失败: {rel}")

        dst = dst_root / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        if not dst.is_file() or dst.stat().st_size != src.stat().st_size:
            raise RuntimeError(f"复制校验失败: {rel}")

        src.unlink()
        src.symlink_to(dst)
        total += 1
    print(f"[apply] 已迁移 {total} 个文件 -> {dst_root}")
    print(f"[apply] 原位置已替换为软链；备份: {BACKUP_DIR}")


def _rollback(src_root: Path) -> None:
    if not BACKUP_DIR.is_dir():
        raise RuntimeError(f"备份不存在，无法回滚: {BACKUP_DIR}")
    count = 0
    for backup in sorted(p for p in BACKUP_DIR.rglob("*") if p.is_file()):
        rel = backup.relative_to(BACKUP_DIR)
        target = src_root / rel
        if target.is_symlink() or target.is_file():
            target.unlink()
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(backup, target)
        count += 1
    print(f"[rollback] 已从备份恢复 {count} 个原文件；tactics/ 保留未删，请人工确认后清理")


def main() -> int:
    ap = argparse.ArgumentParser(description="战术分析项目代码层迁入 tactics/")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true", help="只统计，不写盘")
    g.add_argument("--apply", action="store_true", help="备份 + 复制 + 原位置替换为软链")
    g.add_argument("--rollback", action="store_true", help="从备份恢复原文件")
    args = ap.parse_args()

    src_root = nba_paths.TACTICS_DATA_ROOT
    dst_root = nba_paths.TACTICS_CODE_ROOT
    if not src_root.is_dir():
        raise RuntimeError(f"数据盘项目根不存在: {src_root}")

    if args.rollback:
        _rollback(src_root)
        return 0

    files = _targets(src_root)
    size = sum(p.stat().st_size for p in files)
    print(f"[scan] 代码层文件 {len(files)} 个，合计 {size / 1024 / 1024:.2f} MiB")
    print(f"[scan] 源: {src_root}")
    print(f"[scan] 目标: {dst_root}")
    for p in files[:8]:
        print(f"  + {p.relative_to(src_root)}")
    if len(files) > 8:
        print(f"  ... 其余 {len(files) - 8} 个")

    if args.apply:
        _apply(files, src_root, dst_root)
    else:
        print("[dry-run] 未写盘")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
