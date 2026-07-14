#!/bin/bash
# BR 综合爬虫 —— 全自动无值守(向前增量捕获)
# 接入(ARCH T05):
#   ① 桥接对账 game_id_bridge(幂等, 每轮先跑, 补全 BR gid ↔ nba_api_id ↔ ESPN event)
#   ② BR 各数据集(pbp 向前增量 / teams / gamelog / player / espn_broad 宽爬)
#   ③ 归档校验钩子 verify_archive(每轮后跑, 比对文件数 vs 表行数, 输出缺口)
# 2023+ 已全覆盖 → 本守护只抓【未来新比赛】, 已覆盖的自动跳过, 不毁坐标。
# 重型/一次性数据集(teams 补全 / player 整季重爬)仍可单独跑:
#   python br_crawler.py --datasets teams
#   python br_crawler.py --datasets player --seasons 2023 2024 2025 2026
# 用法(脱离终端):
#   nohup bash run_br_crawler.sh > br_crawler.out 2>&1 &
set -u
cd /Users/deocheng/Downloads/nba_desktop_omega_mac_migrate_2026-07-13
# 注入 .env 中的 DB_PASSWORD 等机密到环境变量（供 Python 爬虫连接 PG）
set -a; [ -f "$PWD/.env" ] && . "$PWD/.env"; set +a
PY="$PWD/.venv/bin/python"
LOG="$PWD/br_crawler.log"
PGCTL=/opt/homebrew/opt/postgresql@18/bin/pg_ctl
PGDATA=/Users/deocheng/nba_pg
PGLOG=/tmp/nba_pg.log
INTERVAL=21600   # 6h

log(){ echo "[$(date '+%F %T')] $*" | tee -a "$LOG"; }

# PG 5433 探活自拉起(会话刷新可能杀掉)
if ! pg_isready -h localhost -p 5433 >/dev/null 2>&1; then
  log "PG 5433 未就绪, 尝试拉起..."
  "$PGCTL" -D "$PGDATA" -o "-p 5433 -k /tmp" -l "$PGLOG" start >>"$LOG" 2>&1
  sleep 4
fi

log "=== 启动 BR 综合爬虫(桥接对账 + 数据集 + 归档校验, 间隔 6h) ==="
while true; do
  log "--- ① 桥接对账 game_id_bridge (幂等, 补全键空间) ---"
  "$PY" game_id_bridge.py >>"$LOG" 2>&1 || log "桥接对账返回非0, 继续下一轮"

  log "--- ② BR 数据集(pbp/gamelog/espn_broad, 向前增量; teams/player 为一次性, 不进循环) ---"
  "$PY" br_crawler.py --datasets pbp gamelog espn_broad >>"$LOG" 2>&1 \
    || log "数据集返回非0, 继续下一轮"

  log "--- ③ 归档校验 verify_archive ---"
  "$PY" verify_archive.py >>"$LOG" 2>&1 || true

  log "睡眠 ${INTERVAL}s 后进入下一轮"
  sleep "$INTERVAL"
done
