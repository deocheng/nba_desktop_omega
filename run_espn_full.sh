#!/bin/bash
# ESPN 宽数据集全量回补 —— 全自动无值守编排（ARCH T04）
# ① PG 5433 探活, 掉线自动拉起;
# ② 宽爬 espn_broad_crawler.py(抓 summary → 解析盒式+坐标 → 落盘原始 JSON → 写 espn_boxscore);
# ③ 坐标回填 espn_backfill_shot_coords.py --apply(写入 play_by_play 真实坐标, 现也落盘原始 JSON);
# ④ 归档校验钩子 verify_archive.py。
# 幂等: 已抓的场自动跳过(espn_have=true / 坐标已补), 可随时重跑。
set -u
cd /Users/deocheng/Downloads/nba_desktop_omega_mac_migrate_2026-07-13
# 注入 .env 中的 DB_PASSWORD 等机密到环境变量（供 Python 爬虫连接 PG）
set -a; [ -f "$PWD/.env" ] && . "$PWD/.env"; set +a
PY="$PWD/.venv/bin/python"
BROAD=espn_broad_crawler.py
COORD=external_crawler/crawler/espn_backfill_shot_coords.py
LOG="$PWD/espn_full.log"
PGLOG=/tmp/nba_pg.log
PGCTL=/opt/homebrew/opt/postgresql@18/bin/pg_ctl
PGDATA=/Users/deocheng/nba_pg

log(){ echo "[$(date '+%F %T')] $*" | tee -a "$LOG"; }

# ── 1. 确保 PG 在线(会话刷新可能杀掉) ───────────────────────────────
if ! pg_isready -h localhost -p 5433 >/dev/null 2>&1; then
  log "PG 5433 未就绪, 尝试拉起..."
  "$PGCTL" -D "$PGDATA" -o "-p 5433 -k /tmp" -l "$PGLOG" start >>"$LOG" 2>&1
  sleep 4
fi

# ── 2. 重试循环(覆盖瞬时 403/超时/连接抖动) ─────────────────────────
for attempt in 1 2 3; do
  log "=== attempt $attempt : ESPN 宽爬(盒式+坐标+落盘原始JSON) 2023+ ==="
  "$PY" "$BROAD" --season 2023 >>"$LOG" 2>&1
  "$PY" "$BROAD" --season 2024 >>"$LOG" 2>&1
  "$PY" "$BROAD" --season 2025 >>"$LOG" 2>&1
  "$PY" "$BROAD" --season 2026 >>"$LOG" 2>&1

  log "=== attempt $attempt : ESPN 坐标回填 play_by_play(现也落盘原始JSON) 2023+ ==="
  "$PY" "$COORD" --apply --seasons 2023 2024 2025 2026 >>"$LOG" 2>&1
done

log "=== 归档校验 ==="
"$PY" verify_archive.py >>"$LOG" 2>&1 || true

echo "[$(date)] === ESPN 全量回填 DONE (已补的场自动跳过, 残留=ESPN 映射不到/无坐标) ===" | tee -a "$LOG"
