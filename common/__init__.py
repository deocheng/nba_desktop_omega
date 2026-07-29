# common/__init__.py
# 使 common 成为可导入包（Python 3 命名空间包亦可，但显式 __init__ 更稳）。

from . import team_names
from .team_names import (
    BR_TEAM_SLUGS,
    TEAM_ABBRS,
    TEAM_FULL_NAME,
    check_against_db,
    get_br_slug,
    get_full_name,
)
#
# 注意：本文件**不** re-export common.team_names，以避免循环依赖：
#   common/__init__.py -> common.team_names -> hof_exec.config -> common.*
# 会让 hof_exec.config 在半初始化时回引 common，触发 ImportError。
# 需要 30 队英文名/slug 时，直接 `from common.team_names import ...`（子模块按需导入）。
