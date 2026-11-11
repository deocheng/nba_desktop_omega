#!/usr/bin/env python3
"""nba_paths — 全项目路径解析的唯一来源（纯标准库、零依赖）。

问题背景：本项目横跨两个代码根 + 一个仓外产物目录，硬编码绝对路径
（用户目录与数据盘根的绝对路径）曾散落在 60+ 个脚本中，
换机 / 迁移 / 容器化即断。

本模块提供统一的路径解析，优先级自高而低：
    1. 环境变量覆盖（NBA_REPO_ROOT / NBA_WORKSPACE_ROOT / NBA_ANALYSIS_ROOT ...）
    2. 由本文件位置反推（repo root = 本文件的上上级）
    3. 已知候选路径探测（存在即用）

用法：
    from nba_paths import REPO_ROOT, WORKSPACE_ROOT, env_file, repo_file

设计约束：
- **不递归扫描**大目录（外置盘 6TB 素材区会导致卡死 / exit 137）。
  探测只做 os.path.exists 单次 stat。
- 路径解析是纯函数式读取，模块导入不产生副作用。
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path

# ── 根目录候选（按优先级）──────────────────────────────────────────────────
# 主仓库（本文件位于 R/<sub>/nba_paths.py 时，R = parents[1]）
_THIS = Path(__file__).resolve()
REPO_ROOT_DEFAULT = _THIS.parent.parent

# 会话工作区（W）与仓外产物（P）的已知候选
_WORKSPACE_CANDIDATES = (
    os.path.expanduser("~/WorkBuddy/2026-07-13-10-47-43"),
    str(REPO_ROOT_DEFAULT / "workspace" / "workbuddy-scripts"),
)
_ANALYSIS_CANDIDATES = (
    str(REPO_ROOT_DEFAULT.parent / "nba_analysis"),
)


def _from_env(name: str) -> str | None:
    v = os.environ.get(name)
    return v.strip() if v and v.strip() else None


def _abs(p: str) -> Path:
    """转绝对路径但**不解析符号链接**。

    本机的会话工作区本身是软链
    （``~/WorkBuddy/<会话> -> <盘根>/WorkBuddy/<会话>``），
    若用 Path.resolve() 会把逻辑路径换成物理路径，报告输出路径将与
    用户预期不一致，也会让脚本之间的路径比较失败。故统一用 abspath。
    """
    return Path(os.path.abspath(os.path.expanduser(p)))


def _first_existing(candidates) -> Path | None:
    """返回第一个存在的候选路径；全不存在返回 None。只做单次 stat，不递归。"""
    for c in candidates:
        if c and os.path.exists(c):
            return _abs(c)
    return None


def _resolve(name: str, candidates, fallback: Path | None = None) -> Path:
    """解析一个根路径：环境变量 > 已知候选 > fallback。"""
    env = _from_env(name)
    if env:
        return _abs(env)
    found = _first_existing(candidates)
    if found is not None:
        return found
    if fallback is not None:
        return _abs(str(fallback))
    raise RuntimeError(
        f"无法定位 {name}：请设置环境变量 {name} 指向正确路径"
    )


# ── 三个逻辑来源 ──────────────────────────────────────────────────────────
#: R —— 主仓库，唯一代码根
REPO_ROOT: Path = _resolve(
    "NBA_REPO_ROOT", (str(REPO_ROOT_DEFAULT),), REPO_ROOT_DEFAULT
)
#: W —— 会话工作区（一次性脚本 / 报告产物层）
WORKSPACE_ROOT: Path = _resolve(
    "NBA_WORKSPACE_ROOT", _WORKSPACE_CANDIDATES, REPO_ROOT_DEFAULT / "workspace"
)
#: 会话工作区的**父目录**（``~/WorkBuddy``）—— 同级还有其它项目目录
#: （如 ``NBA_BR_爬虫``），**不可**一律映射到 WORKSPACE_ROOT。
WORKSPACE_PARENT: Path = WORKSPACE_ROOT.parent

#: P —— 仓外报告产物目录
ANALYSIS_ROOT: Path = _resolve(
    "NBA_ANALYSIS_ROOT", _ANALYSIS_CANDIDATES, REPO_ROOT_DEFAULT.parent / "nba_analysis"
)

#: R 内逻辑入口（workspace/ 与 reports/ 的只读软链入口）
WORKSPACE_LINK: Path = REPO_ROOT / "workspace" / "workbuddy-scripts"
ANALYSIS_LINK: Path = REPO_ROOT / "reports" / "nba-analysis"

#: 数据库 .env（口令严禁硬编码，统一从此处或环境变量读取）
ENV_FILE: Path = REPO_ROOT / ".env"


# ── 数据盘根（D）──────────────────────────────────────────────────────────
# D 与 R 的关系：仓库 R 通常**直接位于**数据盘根下（``<盘根>/<仓库名>``），
# 但仓库也可能被 clone 到别处 → 不能只靠「父目录」推断，必须用**特征标记**校验。
#
# 特征标记（命中任一即认定该候选是数据盘根）：
#   nba_pg      —— PostgreSQL 数据目录
#   raw_archive —— BR 归档（24GB，只读引用）
#   headshots   —— 头像缓存
#
# 解析优先级：环境变量 NBA_DATA_ROOT > 特征校验通过的候选 > 仓库父目录兜底。
_DATA_ROOT_MARKERS = ("nba_pg", "raw_archive", "headshots")


def _looks_like_data_root(candidate: Path) -> bool:
    """特征校验：候选目录下是否存在任一数据盘特征子目录。只做单次 stat。"""
    for marker in _DATA_ROOT_MARKERS:
        if (candidate / marker).exists():
            return True
    return False


def _resolve_data_root() -> Path:
    env = _from_env("NBA_DATA_ROOT")
    if env:
        return _abs(env)
    candidates = (REPO_ROOT.parent, REPO_ROOT_DEFAULT.parent)
    for c in candidates:
        if c and os.path.exists(c) and _looks_like_data_root(_abs(c)):
            return _abs(c)
    # 兜底：仓库父目录（结构未就绪时至少给出可预期路径）
    return _abs(str(REPO_ROOT_DEFAULT.parent))


#: D —— 数据盘根（nba_pg / raw_archive / headshots / 各类 cache 与爬虫日志）
DATA_ROOT: Path = _resolve_data_root()

#: PostgreSQL 数据目录（**生产实例所在处**）。
#:
#: 🔴 口径澄清（2026-11-10 实测 `SHOW data_directory` 确认）：
#: 生产实例位于**本机本地盘** ``~/nba_pg``（``postmaster.pid`` 存在即证实在用），
#: 而数据盘根下的 ``nba_pg`` 是**从 12T 迁出前的旧副本**（无 postmaster.pid）。
#: 两者都存在，容易误认 —— 以本机盘为生产口径，旧副本另经 ``DATA_ROOT / "nba_pg"`` 访问。
#:
#: 解析顺序：环境变量 ``NBA_PG_DATA_DIR`` > 本机 ``~/nba_pg``（有 PG_VERSION 即用）
#: > 数据盘根下的旧副本。
_PG_LOCAL_DEFAULT = Path(os.path.expanduser("~")) / "nba_pg"


def _resolve_pg_data_dir() -> Path:
    env = _from_env("NBA_PG_DATA_DIR")
    if env:
        return _abs(env)
    if (_PG_LOCAL_DEFAULT / "PG_VERSION").exists():
        return _PG_LOCAL_DEFAULT
    return DATA_ROOT / "nba_pg"


#: 生产 PostgreSQL 数据目录
PG_DATA_DIR: Path = _resolve_pg_data_dir()

#: 数据盘根下的**旧副本**（迁移前 PG 落位处，只读引用，不启动）
PG_DATA_DIR_LEGACY: Path = DATA_ROOT / "nba_pg"

#: BR 归档根（24GB，只读引用，禁止写入/移动/删除）
ARCHIVE_ROOT: Path = DATA_ROOT / "raw_archive"

#: 头像缓存根
HEADSHOTS_ROOT: Path = DATA_ROOT / "headshots"

#: 战术分析项目（2026-11-11 迁入主仓库，见 docs/change-log.md 当日条目）
#:
#: 🔴 **代码与数据分离**：代码根在仓库内（纳入 git / ruff / 质量门禁）；
#: 数据根仍在外置盘（action_work 21G、bonsai 13G、clips 9G、reports 982M、
#: backups 1.8G、.venv 与模型权重），**绝不入库**。
#: 数据盘原目录对迁走的代码文件保留同名软链指回 tactics/，
#: 因此历史脚本里的绝对路径在运行时仍然有效，迁移不改变任何读写落点。
TACTICS_CODE_ROOT: Path = REPO_ROOT / "tactics"
TACTICS_DATA_ROOT: Path = DATA_ROOT / "action_analysis"

#: 仓库内虚拟环境解释器（Python 3.12）
VENV_PYTHON: Path = REPO_ROOT / ".venv" / "bin" / "python"

#: 爬虫看门狗脚本（WorkBuddy 技能资产，位于用户目录 → 用 ~ 表达，不写死用户名）
WATCHDOG_SCRIPT_DEFAULT: Path = (
    Path(os.path.expanduser("~")) / ".workbuddy" / "skills" / "nba-crawler-watch" / "scripts" / "watch_crawlers.py"
)


def env_file() -> Path:
    """返回 .env 路径；不存在时抛 RuntimeError（调用方需处理缺失）。"""
    if ENV_FILE.exists():
        return ENV_FILE
    raise RuntimeError(f"未找到 {ENV_FILE}；请设置 NBA_REPO_ROOT 或补齐 .env")


def repo_file(*parts: str) -> Path:
    """主仓库内的路径：repo_file("backend", "core", "db.py")"""
    return REPO_ROOT.joinpath(*parts)


def workspace_file(*parts: str) -> Path:
    """会话工作区内的路径"""
    return WORKSPACE_ROOT.joinpath(*parts)


def analysis_file(*parts: str) -> Path:
    """仓外产物目录内的路径"""
    return ANALYSIS_ROOT.joinpath(*parts)


def data_file(*parts: str) -> Path:
    """数据盘根内的路径：data_file("raw_archive", "br_players_shooting")"""
    return DATA_ROOT.joinpath(*parts)


def tactics_code_file(*parts: str) -> Path:
    """战术分析**代码**路径（仓库内）：tactics_code_file("engine", "tacboard.py")"""
    return TACTICS_CODE_ROOT.joinpath(*parts)


def tactics_data_file(*parts: str) -> Path:
    """战术分析**数据**路径（外置盘）：tactics_data_file("action_work", "x.json")"""
    return TACTICS_DATA_ROOT.joinpath(*parts)


def node_binary() -> str | None:
    """定位 node 可执行文件。

    优先用 PATH（shutil.which）——**不要**硬编码某个用户目录下的 node 路径，
    那是换机即断的写法。找不到时返回 None，由调用方决定跳过还是报错。
    """
    return shutil.which("node")


def watchdog_script() -> Path:
    """爬虫看门狗脚本路径。

    环境变量 NBA_WATCHDOG_SCRIPT > 默认位置（用户目录下的 WorkBuddy 技能资产）。
    默认位置用 ``~`` 展开，**不写死用户名**。
    """
    env = _from_env("NBA_WATCHDOG_SCRIPT")
    if env:
        return _abs(env)
    return WATCHDOG_SCRIPT_DEFAULT


def output_file(name: str, *, root: Path | None = None) -> Path:
    """报告输出路径。默认写到工作区；传 root 则写到指定目录。"""
    base = root or WORKSPACE_ROOT
    p = base / name
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def cache_dir(name: str) -> Path:
    """缓存目录（主仓库内，按需创建）。"""
    d = REPO_ROOT / name
    d.mkdir(parents=True, exist_ok=True)
    return d


def describe() -> str:
    """人类可读的路径概览（用于 --check / 诊断输出）。"""
    lines = [
        "路径解析结果：",
        f"  R 主仓库      : {REPO_ROOT}  [{'存在' if REPO_ROOT.exists() else '缺失'}]",
        f"  D 数据盘根    : {DATA_ROOT}  [{'存在' if DATA_ROOT.exists() else '缺失'}]",
        f"  W 会话工作区  : {WORKSPACE_ROOT}  [{'存在' if WORKSPACE_ROOT.exists() else '缺失'}]",
        f"  P 仓外产物    : {ANALYSIS_ROOT}  [{'存在' if ANALYSIS_ROOT.exists() else '缺失'}]",
        f"  .env          : {ENV_FILE}  [{'存在' if ENV_FILE.exists() else '缺失'}]",
        f"  PG 数据目录   : {PG_DATA_DIR}  [{'存在' if PG_DATA_DIR.exists() else '缺失'}]",
        f"  BR 归档根     : {ARCHIVE_ROOT}  [{'存在' if ARCHIVE_ROOT.exists() else '缺失'}]",
        f"  头像缓存根    : {HEADSHOTS_ROOT}  [{'存在' if HEADSHOTS_ROOT.exists() else '缺失'}]",
        f"  战术代码根    : {TACTICS_CODE_ROOT}  [{'存在' if TACTICS_CODE_ROOT.exists() else '缺失'}]",
        f"  战术数据根    : {TACTICS_DATA_ROOT}  [{'存在' if TACTICS_DATA_ROOT.exists() else '缺失'}]",
        f"  venv 解释器   : {VENV_PYTHON}  [{'存在' if VENV_PYTHON.exists() else '缺失'}]",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    print(describe())
