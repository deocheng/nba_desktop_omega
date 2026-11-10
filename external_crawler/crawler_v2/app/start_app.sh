#!/usr/bin/env bash
# BR 爬虫套装独立 App 启动器（macOS）。
# 用法: bash start_app.sh   (自动开浏览器到 http://127.0.0.1:5757)

# source 统一路径解析（与 Python 侧 common/nba_paths.py 对齐）
if [ -f "../../../common/paths.sh" ]; then
  . "../../../common/paths.sh"
fi

set -e
ROOT=$PROJ_ROOT
APP="$ROOT/external_crawler/crawler_v2/app"
VENV_PY="$ROOT/.venv/bin/python"

# 载入 DB / 代理等环境（与爬虫运行环境一致）
set -a
[ -f "$ROOT/.env" ] && source "$ROOT/.env"
set +a

cd "$APP"

# 启动前先开浏览器（server 起来后约 2s 可达）
( sleep 2; open http://127.0.0.1:5757 ) &

echo ">>> 启动 BR 爬虫控制台 (Ctrl+C 退出) ..."
exec "$VENV_PY" server.py
