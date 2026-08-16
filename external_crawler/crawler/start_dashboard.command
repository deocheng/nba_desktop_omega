#!/bin/bash
# =============================================================================
# start_dashboard.command —— 双击即在浏览器打开「NBA 爬虫控制面板」
# -----------------------------------------------------------------------------
# 用法：在 Finder 里双击本文件（或右键→打开）。会在后台以【独立会话】拉起
# 控制面板（python os.setsid 脱离终端），随后自动打开浏览器到
# http://127.0.0.1:8787 。关掉终端窗口也不会影响面板与爬虫。
#
# 与 WorkBuddy 无关：本文件纯本地，任何终端都能跑。
# =============================================================================
ROOT=/Volumes/12T/NBA/nba_desktop_omega_mac_migrate_2026-07-13
PY=/Users/deocheng/.workbuddy/binaries/python/versions/3.13.12/bin/python3
DASH="$ROOT/external_crawler/crawler/crawler_dashboard.py"
PORT=8787

# 已在运行则直接提示并打开浏览器
if pgrep -f "crawler_dashboard.py" >/dev/null 2>&1; then
  echo "控制面板已在运行： http://127.0.0.1:$PORT"
  open "http://127.0.0.1:$PORT" 2>/dev/null
  sleep 2
  exit 0
fi

# 用 python os.setsid 脱离当前会话，关闭终端也不受影响
"$PY" -c "import os,subprocess; os.setsid(); subprocess.Popen(['$PY','$DASH'], stdout=open('$ROOT/logs/dashboard.out','a'), stderr=subprocess.STDOUT)"

sleep 2
echo "=========================================="
echo " 🏀 NBA 爬虫控制面板已启动"
echo " 浏览器打开： http://127.0.0.1:$PORT"
echo " 面板里可点【启动爬虫】开始补数据"
echo "=========================================="
open "http://127.0.0.1:$PORT" 2>/dev/null
sleep 3
