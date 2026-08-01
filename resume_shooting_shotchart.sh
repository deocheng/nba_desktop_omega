#!/usr/bin/env bash
# resume_shooting_shotchart.sh — 恢复 player_shooting + player_shot_chart 回填（2026-07-29）
#
# 设计要点：
#   1) 速率与「队标回填」完全一致：common/br_team_page.py 的 rate_limit() = 6.0+uniform(0,2.0)s
#      （6–8s/req，均值 ~7s）。队标回填刚跑完且未被封，证明此速率安全，故不改动。
#   2) 顺序执行（非并发）：先 player_shooting 跑完，再 player_shot_chart。
#      原因：shot_chart 的「宇宙」= DISTINCT(player_id,season) FROM player_shooting，
#      shooting 不完整会导致 shot_chart 误判「完成」。顺序执行保证 universe 先补全。
#   3) 同一 CDP 9223 串行（铁律：两爬虫不可抢同一 CDP，避免 09:15 同秒会话竞态）。
#   4) 不触发 team_data / orchestrator（超出本次范围）；只做 shooting + shot_chart 两项回填。
#
# 运行（脱离会话，防 WorkBuddy 崩溃中断）：
#   脱离会话启动（zsh 安全写法，避免 python -c 嵌套括号被 zsh 误判；nohup+disown 已足够忽略 SIGHUP）：
#   nohup bash resume_shooting_shotchart.sh >> /Volumes/12T/NBA/resume_launcher.log 2>&1 & disown
set -u
export LC_ALL=C
cd "$(dirname "$0")"
ROOT="$(pwd)"

# ---------- 环境（与队标回填一致）----------
export PGPASSWORD='R!h0N-ctlg=xB01V_-1VJcFeCCuBjS6UCvV1'
export DB_PASSWORD='R!h0N-ctlg=xB01V_-1VJcFeCCuBjS6UCvV1'
export BROWSER_BACKEND=cdp
export CHROME_CDP_URL=http://127.0.0.1:9223
# 🔴 清掉从启动会话（agent 沙箱等）继承的代理变量：死代理（如 127.0.0.1:61914）
# 会把 CDP websocket 全部劫持 → Errno 61 → 空白 tab 只建不关、越积越多且抢焦点。
# 代码层已加 proxy=None 双保险，这里从源头保证整条子进程链环境干净。
unset HTTP_PROXY HTTPS_PROXY http_proxy https_proxy ALL_PROXY all_proxy
export NO_PROXY="127.0.0.1,localhost"
export no_proxy="127.0.0.1,localhost"

PY=".venv/bin/python"
SHOOTING_LOG="/Volumes/12T/NBA/shooting_crawl.log"
SHOTCHART_LOG="/Volumes/12T/NBA/shot_chart_crawl.log"
PROGRESS_LOG="/Volumes/12T/NBA/resume_shooting_shotchart.log"
PSQL="/opt/homebrew/bin/psql -h localhost -p 5433 -U postgres -d nba -t -A"

log(){ echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$PROGRESS_LOG"; }
cdp_ok(){ curl -s --max-time 5 "http://127.0.0.1:9223/json/version" >/dev/null 2>&1; }
pg_ok(){ /opt/homebrew/bin/pg_isready -h 127.0.0.1 -p 5433 >/dev/null 2>&1; }

ensure_postgres(){
  if pg_ok; then return 0; fi
  log "⚠ PG 5433 不可达，尝试拉起"
  rm -f /Volumes/12T/NBA/nba_pg/postmaster.pid 2>/dev/null
  /opt/homebrew/bin/pg_ctl start -D /Volumes/12T/NBA/nba_pg -o "-p 5433" \
    -l /Volumes/12T/NBA/nba_pg/startup.log >/dev/null 2>&1
  for i in $(seq 1 12); do sleep 2; pg_ok && { log "✅ PG 已起"; return 0; }; done
  log "❌ PG 拉起失败"; return 1
}
ensure_chrome(){
  if cdp_ok; then return 0; fi
  log "⚠ CDP 9223 不可达，尝试拉起 Chrome"
  bash launch_chrome_cdp.sh >/dev/null 2>&1
  for i in $(seq 1 18); do sleep 5; cdp_ok && { log "✅ Chrome 9223 已起"; return 0; }; done
  log "❌ Chrome 拉起超时"; return 1
}

log "=== 启动 shooting + shot_chart 回填（速率 6–8s/req，与队标回填一致）==="

# ---- Phase 1: player_shooting（补全 2,576 个缺失球员 + 既有缺口）----
if ! ensure_postgres || ! ensure_chrome; then
  log "❌ 前置检查失败（PG 或 Chrome 不可用），退出。请恢复后重跑本脚本。"
  exit 1
fi
log "▶ 开始 player_shooting 回填 (--resume，逐季页 /shooting/{year}，枚举 1997+ 缺口对，跳过已落库)"
$PY external_crawler/crawler/crawl_br_player_shooting.py --resume >> "$SHOOTING_LOG" 2>&1
sc=$?
log "◼ player_shooting 结束 (exit=$sc)"

# ---- Phase 2: player_shot_chart（universe 现来自已补全的 player_shooting）----
if ! ensure_postgres || ! ensure_chrome; then
  log "❌ shot_chart 前 PG/Chrome 不可用，跳过。shooting 已完成，可单独重跑 shot_chart。"
  exit 1
fi
log "▶ 开始 player_shot_chart 回填 (--resume)"
$PY external_crawler/crawler/crawl_br_player_shot_chart.py --resume >> "$SHOTCHART_LOG" 2>&1
cc=$?
log "◼ player_shot_chart 结束 (exit=$cc)"

# ---- 收尾报告 ----
shooting_players=$($PSQL -c "SELECT COUNT(DISTINCT player) FROM player_shooting;" 2>/dev/null | tail -1 | tr -d ' ')
done_pairs=$($PSQL -c "SELECT COUNT(DISTINCT (player_id,season)) FROM player_shot_chart;" 2>/dev/null | tail -1 | tr -d ' ')
univ_pairs=$($PSQL -c "SELECT COUNT(DISTINCT (player_id,season)) FROM player_shooting;" 2>/dev/null | tail -1 | tr -d ' ')
log "=== 回填结束: shooting_players=$shooting_players, shot_chart done=$done_pairs / universe=$univ_pairs ==="
