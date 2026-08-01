#!/usr/bin/env bash
# watchdog_shot_chart.sh — shot chart 爬虫看门狗（2026-07-28）
# 作用：定时巡检「爬虫进程 + 数据库进度」，发现意外停止/卡死就自动重开，
#       并在 shot chart 真正完成后交接给 Phase1（run_team_data.sh）。
#
# 设计要点（针对 2026-07-28 09:15 事故）：
#   1) 重启前先验证 Chrome CDP 9223 可达 —— 否则不重开（避免秒死/会话竞态）。
#   2) 重启前 wait-for-exit —— 等旧进程 quit_driver 收尾完再连，杜绝同秒会话竞态。
#   3) 完成守卫：已完成对 == 宇宙对 才算真完成，才放行 Phase1（防接力误触发）。
#   4) 卡死检测：进程在但日志 N 分钟无更新 → 视为卡死，重启。
#
# 运行：nohup bash ./watchdog_shot_chart.sh >> /Volumes/12T/NBA/watchdog.log 2>&1 &
set -u
# 修复 bash `set -u` + 多字节 UTF-8（中文日志）的兼容性崩溃：
# 在 C.UTF-8 / en_US.UTF-8 等 locale 下，含中文的双引号字符串中嵌入 $var
# 会被 bash 误报为 "unbound variable" 而整脚本崩溃（看门狗自愈层随之失效）。
# 强制字节级 locale 即可规避；业务库查询/日期格式均为 ASCII，不受影响。
export LC_ALL=C
cd "$(dirname "$0")"
ROOT="$(pwd)"

# ---------- 配置 ----------
CHECK_INTERVAL=300        # 巡检间隔（秒）=5 分钟，撞死/卡死最多 5 分钟内拉起。
HANG_LOG_STALE=1200      # 日志多久无更新判为"冻死"（秒），默认 20 分钟
CDP_URL="http://127.0.0.1:9223/json/version"
PATTERN="crawl_br_player_shot_chart.py"     # shot chart 爬虫
TEAM_PATTERN="run_team_data.sh"              # Phase1 爬虫
PHASE1_FLAG="/Volumes/12T/NBA/.phase1_launched.flag"
WATCHDOG_LOG="/Volumes/12T/NBA/watchdog.log"
CRAWLER_LOG="/Volumes/12T/NBA/shot_chart_crawl.log"

export PGPASSWORD='R!h0N-ctlg=xB01V_-1VJcFeCCuBjS6UCvV1'
export BROWSER_BACKEND=cdp
export CHROME_CDP_URL=http://127.0.0.1:9223
PSQL="/opt/homebrew/bin/psql -h localhost -p 5433 -U postgres -d nba -t -A"

log(){ echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$WATCHDOG_LOG"; }

proc_alive(){ pgrep -f "$1" >/dev/null 2>&1; }
cdp_ok(){ curl -s --max-time 5 "$CDP_URL" >/dev/null 2>&1; }
db_pairs(){
  local sql="$1"
  $PSQL -c "$sql" 2>/dev/null | tail -1 | tr -d ' '
}
done_pairs(){ db_pairs "SELECT COUNT(DISTINCT (player_id,season)) FROM player_shot_chart;"; }
universe_pairs(){ db_pairs "SELECT COUNT(DISTINCT (player_id,season)) FROM player_shooting;"; }

# 干净地等旧进程退出（让它的 finally/quit_driver 跑完），再返回
wait_exit(){
  local pat="$1"; local i
  for i in $(seq 1 30); do
    proc_alive "$pat" || return 0
    sleep 1
  done
  return 1   # 30s 还没退，交给调用方强制
}

# 完全脱离看门狗：用 python os.setsid() 起独立会话（macOS 无 setsid 命令，故走 python）。
# 这样爬虫/Phase1 是独立会话，看门狗自身重启或死亡都不会波及它们。
detach(){
  local logfile="$1"; shift
  .venv/bin/python -c "import os,sys,subprocess; os.setsid(); sys.exit(subprocess.run(sys.argv[1:], cwd='$ROOT', env=dict(os.environ)).returncode)" "$@" >> "$logfile" 2>&1 &
  echo $!
}

start_crawler(){
  if ! cdp_ok; then
    log "⚠ CDP 9223 不可达，暂不重启爬虫（避免 09:15 同秒竞态秒死）。等 Chrome 恢复后下轮自动拉起。"
    return 1
  fi
  pid=$(detach "$CRAWLER_LOG" .venv/bin/python external_crawler/crawler/crawl_br_player_shot_chart.py --resume)
  log "✅ 已拉起 shot chart 爬虫 (PID $pid)"
  return 0
}

# 先确保专用 Chrome(9223) 在线：断了就先拉 Chrome，再决定爬虫。
# 返回 0=Chrome 可达；1=拉起超时（本轮不启爬虫，下轮重试）。
ensure_chrome(){
  if cdp_ok; then return 0; fi
  log "⚠ CDP 9223 不可达 → 先拉起专用 Chrome (launch_chrome_cdp.sh)"
  bash launch_chrome_cdp.sh >/dev/null 2>&1
  local i
  for i in $(seq 1 18); do      # 18×5s = 90s 轮询
    sleep 5
    if cdp_ok; then log "✅ Chrome 9223 已起"; return 0; fi
  done
  log "❌ Chrome 9223 拉起超时（90s 仍不可达），本轮跳过爬虫管理"
  return 1
}

start_team_data(){
  if ! cdp_ok; then log "⚠ Phase1 前 CDP 不可达，暂缓启动。"; return 1; fi
  pid=$(detach /Volumes/12T/NBA/team_data_watchdog.log bash ./run_team_data.sh)
  log "🚀 交接启动 Phase1 (Team PBP + logo) PID $pid"
}

# 确保业务库 PG 5433 在线：断了就先拉库，再管 Chrome/爬虫。
# 返回 0=库可达；1=拉起失败（本轮跳过）。
# 这是 2026-07-28 那次「内存不足把 postgres 一起 OOM 杀掉、爬虫连库 refused 崩」的根因补丁。
ensure_postgres(){
  if /opt/homebrew/bin/pg_isready -h 127.0.0.1 -p 5433 >/dev/null 2>&1; then return 0; fi
  log "⚠ PG 5433 不可达 → 先拉起业务库 (pg_ctl start)"
  rm -f /Volumes/12T/NBA/nba_pg/postmaster.pid 2>/dev/null
  /opt/homebrew/bin/pg_ctl start -D /Volumes/12T/NBA/nba_pg -o "-p 5433" \
    -l /Volumes/12T/NBA/nba_pg/startup.log >/dev/null 2>&1
  local i
  for i in $(seq 1 12); do      # 12×2s = 24s 轮询
    sleep 2
    if /opt/homebrew/bin/pg_isready -h 127.0.0.1 -p 5433 >/dev/null 2>&1; then
      log "✅ PG 5433 已起"; return 0
    fi
  done
  log "❌ PG 5433 拉起超时，本轮跳过"
  return 1
}

log "=== 看门狗启动：间隔 ${CHECK_INTERVAL}s，卡死阈值 ${HANG_LOG_STALE}s ==="

while true; do
  ensure_postgres || { sleep "$CHECK_INTERVAL"; continue; }
  universe=$(universe_pairs)
  done=$(done_pairs)
  log "进度: 完成 $done / 宇宙 $universe"

  if [ -n "$universe" ] && [ "$done" = "$universe" ]; then
    # ---- shot chart 真正完成 ----
    log "🎉 shot chart 全部完成"
    if proc_alive "$TEAM_PATTERN"; then
      touch "$PHASE1_FLAG"
      log "✅ Phase1 运行中"
    elif [ -f "$PHASE1_FLAG" ]; then
      log "⚠ Phase1 进程不在（曾启动过），疑似中途退出 → 可手动 --resume 续跑。"
    else
      start_team_data && touch "$PHASE1_FLAG"
    fi
    else
      # ---- shot chart 未完成：先确保 Chrome 在线，再盯住爬虫 ----
      if ! ensure_chrome; then
        log "⚠ 本轮跳过爬虫管理（Chrome 未就绪），下轮重试"
      elif proc_alive "$PATTERN"; then
      # 卡死检测（两种）：
      #  (a) 日志很久没动（进程冻死）；
      #  (b) 日志在动但连续多次巡检都卡在同一条 URL（进程在死 target
      #      上重试）—— 这正是 2026-07-28 15:xx 那次「监控无效」的真凶：
      #      重试日志每 2s 刷一行，mtime 永远新鲜，普通 staleness 检测识别不出。
      log_tail=$(tail -200 "$CRAWLER_LOG" 2>/dev/null)
      if [ -f "$CRAWLER_LOG" ]; then
        stale=$(( $(date +%s) - $(stat -f %m "$CRAWLER_LOG") ))
      else
        stale=99999
      fi
      cur_url=$(printf '%s\n' "$log_tail" | grep -oE 'shooting/[0-9]+' | tail -1)
      # URL 状态文件：记录上次巡检的 URL + 连续相同计数
      url_state="$ROOT/.watchdog_url_state"
      last_url=""; last_cnt=0
      if [ -f "$url_state" ]; then
        last_url=$(cut -d'|' -f1 "$url_state" 2>/dev/null)
        last_cnt=$(cut -d'|' -f2 "$url_state" 2>/dev/null || echo 0)
      fi
      if [ "$cur_url" = "$last_url" ] && [ -n "$cur_url" ]; then
        last_cnt=$((last_cnt+1))
      else
        last_cnt=0
      fi
      printf '%s|%s\n' "$cur_url" "$last_cnt" > "$url_state"
      if [ "$stale" -gt "$HANG_LOG_STALE" ]; then
        log "⚠ 爬虫进程在但日志 ${stale}s 无更新（疑似冻死），重启"
        pkill -TERM -f "$PATTERN" 2>/dev/null
        wait_exit "$PATTERN" || pkill -KILL -f "$PATTERN" 2>/dev/null
        sleep 3
        start_crawler
      elif [ "$last_cnt" -ge 2 ]; then
        log "⚠ 爬虫连续 ${last_cnt} 次巡检卡在同一 URL ($cur_url)，判定卡死，重启"
        pkill -TERM -f "$PATTERN" 2>/dev/null
        wait_exit "$PATTERN" || pkill -KILL -f "$PATTERN" 2>/dev/null
        sleep 3
        start_crawler
      else
        log "✅ 爬虫存活中（日志 ${stale}s 前更新；当前 URL=$cur_url；同URL计数=$last_cnt）"
      fi
    else
      log "❌ 爬虫进程不在（意外停止），尝试重启"
      start_crawler
    fi
  fi

  sleep "$CHECK_INTERVAL"
done
