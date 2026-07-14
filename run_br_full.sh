#!/bin/bash
# BR 2023→now 全量数据 —— 全自动无值守编排(安全版)
# 重要前提(详见 nba-br-crawler skill):
#   2023→now 的 PBP 已由 BBRef(213 场)/ESPN(394 场)/br_crawler 覆盖,
#   再爬 BR PBP 要么空跑、要么 --force 会覆盖掉真实坐标 → 本编排【不】对 2023+ 做 PBP 重写。
#   本编排只做两件【安全/幂等】的事:
#     ① br_fill_pbp --since 2023-07-01(无 --force): 仅补 2023+ 中"真正缺 PBP 的场"
#        (当前 2023+ 已全覆盖 → 本步恒为空跑; 未来新比赛自动被抓到, 已覆盖的自动跳过)
#     ② 球员 gamelog --resume: 2026→2023 刷新(已有自动跳过, 幂等)
#   g5_boxscore 已废弃(分歧功能, 误建为 25-26 总决赛 G5 盒式), 不再构建。
# 用法(脱离终端):
#   nohup bash run_br_full.sh > br_full.out 2>&1 &
set -u
cd /Users/deocheng/Downloads/nba_desktop_omega_mac_migrate_2026-07-13
# 注入 .env 中的 DB_PASSWORD 等机密到环境变量（供 Python 爬虫连接 PG）
set -a; [ -f "$PWD/.env" ] && . "$PWD/.env"; set +a
PY="$PWD/.venv/bin/python"
LOG="$PWD/br_full.log"
PGCTL=/opt/homebrew/opt/postgresql@18/bin/pg_ctl
PGDATA=/Users/deocheng/nba_pg
PGLOG=/tmp/nba_pg.log

log(){ echo "[$(date '+%F %T')] $*" | tee -a "$LOG"; }

# 1) PG 探活自拉起(会话刷新可能杀掉)
if ! pg_isready -h localhost -p 5433 >/dev/null 2>&1; then
  log "PG 5433 未就绪, 尝试拉起..."
  "$PGCTL" -D "$PGDATA" -o "-p 5433 -k /tmp" -l "$PGLOG" start >>"$LOG" 2>&1
  sleep 4
fi

# 2) BR PBP 安全补 2023+ 缺口(无 --force = 不覆盖; 当前 2023+ 已覆盖→空跑, 未来新场会被抓)
log "=== BR PBP 2023+ 安全补缺口(无 --force, 幂等) ==="
"$PY" br_fill_pbp.py --since 2023-07-01 >>"$LOG" 2>&1
log "=== BR PBP 完成 rc=$? (若 0 目标即 2023+ 已全覆盖) ==="

# 3) 球员 gamelog 刷新 2026→2023(--resume 跳过已有, 幂等)
for S in 2026 2025 2024 2023; do
  log "=== BR gamelog S$S 开始 ==="
  "$PY" external_crawler/crawler/crawl_br_gamelog.py --season $S --resume >>"$LOG" 2>&1
  log "=== BR gamelog S$S 完成 rc=$? ==="
done

log "=== BR 无值守编排结束 (2023+ PBP 已覆盖, 本跑仅补未来新场 + 刷新球员表) ==="
