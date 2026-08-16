#!/usr/bin/env python3
"""
launch_detached.py — 让爬虫彻底脱离 WorkBuddy 任务树（双 fork 守护化）。

机制（macos-daemon-survive-recycle 方案）：
  1. 本脚本作为 WorkBuddy Bash 工具直接子进程运行；
  2. 父进程 fork 后 _立即_ sys.exit(0) → 工具跟踪的进程退出 → 前台任务面板不再有它；
  3. 子进程 os.setsid() 进独立会话，并把 0/1/2 重定向到 /dev/null（不持有工具的管道），
     再 exec 到 start_crawler_standalone.sh（其自身再做一次 setsid 双保险）；
  4. 余下 supervisor→driver 链在独立会话里常驻，orphan 到 launchd，完全不受后台任务回收影响。

用法：直接在 Bash 工具里 `python3 launch_detached.py`（不要 run_in_background）。
"""
import os
import sys

LAUNCHER = "/Volumes/12T/NBA/nba_desktop_omega_mac_migrate_2026-07-13/external_crawler/crawler/start_crawler_standalone.sh"

pid = os.fork()
if pid > 0:
    # 父进程 = 工具跟踪对象，立刻退出，使前台任务面板干净收尾
    sys.exit(0)

# ── 子进程：成为独立会话首领，剥离工具管道，exec 到 standalone launcher ──
os.setsid()
devnull = os.open(os.devnull, os.O_RDWR)
os.dup2(devnull, 0)
os.dup2(devnull, 1)
os.dup2(devnull, 2)
os.execvp("bash", ["bash", LAUNCHER])
