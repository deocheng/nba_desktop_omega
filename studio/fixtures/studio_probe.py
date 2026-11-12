#!/usr/bin/env python3
"""Studio Runner 契约验证 fixture —— **不是战术分析脚本**。

用途：在完全可控、零外部依赖、零数据盘写入的前提下，验证编排层的
参数渲染、流式日志、超时、取消、非零退出归因、产物校验六项能力。

输出目录由 Runner 通过 ``STUDIO_JOB_DIR`` 注入（隔离的 job 目录）；
``--write`` 只在该目录内写一个小 JSON，绝不触碰 action_analysis/ 既有产物。

真实战术步骤的接入仍需主理人视觉签核（见 studio/manifest.json 的 planned 项）。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path, PurePosixPath


def main() -> int:
    ap = argparse.ArgumentParser(description="Studio Runner contract fixture")
    ap.add_argument("--lines", type=int, default=3)
    ap.add_argument("--sleep", type=float, default=0.0)
    ap.add_argument("--tag", default="default")
    ap.add_argument("--fail", type=int, default=0)
    ap.add_argument("--write", default="", help="相对 STUDIO_JOB_DIR 的产物文件名")
    args = ap.parse_args()

    job_dir = os.environ.get("STUDIO_JOB_DIR", "")
    print(f"[fixture] tag={args.tag} lines={args.lines} sleep={args.sleep}", flush=True)

    for i in range(1, args.lines + 1):
        print(f"[fixture] line {i}/{args.lines}", flush=True)
        if args.sleep > 0:
            time.sleep(args.sleep)

    if args.write:
        rel = PurePosixPath(args.write)
        if rel.is_absolute() or ".." in rel.parts or not job_dir:
            print("[fixture] 产物路径不合法或 STUDIO_JOB_DIR 未设置", file=sys.stderr, flush=True)
            return 2
        target = Path(job_dir).joinpath(*rel.parts)
        target.write_text(
            json.dumps({"tag": args.tag, "lines": args.lines}, ensure_ascii=False),
            encoding="utf-8",
        )
        print(f"[fixture] wrote {args.write}", flush=True)

    if args.fail:
        print(f"[fixture] intentional failure rc={args.fail}", file=sys.stderr, flush=True)
        return args.fail

    print("[fixture] done", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
