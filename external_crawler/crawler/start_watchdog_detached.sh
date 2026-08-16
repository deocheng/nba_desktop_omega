#!/usr/bin/env bash
# =============================================================================
# start_watchdog_detached.sh — 让 crawler_watchdog.sh 以独立会话启动
#
# 为什么需要：看门狗若直接由 WorkBuddy run_in_background 启动，它与 Chrome、
# driver 同属一个进程组。平台 Network error 回收该后台任务时会 killpg 整组，
# 三者一并被杀（今日实测约 15min 一次）。
#
# 本脚本用 python os.setsid 把看门狗拉进【新会话/新进程组】，与后台任务原
# 始进程组脱钩。即使后台任务被回收(killpg 原始组 → 空)，看门狗仍在自己的会话里
# 存活；而 Chrome/driver 又经 crawler_watchdog.sh 内的 detach() 各自独立成会话，
# 同样不会被波及。三层会话互不隶属 → 任一层被回收都不连累爬虫树。
#
# 用法（WorkBuddy 环境）：用 Bash 工具 run_in_background 执行本脚本即可。
# =============================================================================
PY_BIN="/Users/deocheng/.workbuddy/binaries/python/versions/3.13.12/bin/python3"
WD="/Volumes/12T/NBA/nba_desktop_omega_mac_migrate_2026-07-13/external_crawler/crawler/crawler_watchdog.sh"
exec "$PY_BIN" -c "import os,sys; os.setsid(); os.execv('/bin/bash', ['bash', '$WD'])"
