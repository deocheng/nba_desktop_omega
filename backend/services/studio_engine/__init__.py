"""Studio 编排层：把「脚本顺序 / 参数 / 产物」从对话上下文固化为可执行契约。

分层（见 docs/unified-desktop-app-architecture.md §3）：
    manifest.py     能力目录加载与 schema 校验（唯一顺序来源）
    capabilities.py 外部资产探测与降级矩阵
    runner.py       plan / job 状态机 / 子进程执行

🔴 本包**只以 subprocess CLI 方式**调用 tactics/ 脚本，绝不 import 它们：
约 17% 的战术脚本没有 __main__ 守卫，import 即执行（详见 tactics/README.md 探测禁令）。
"""
from __future__ import annotations

from . import capabilities, manifest, runner

__all__ = ["capabilities", "manifest", "runner"]
