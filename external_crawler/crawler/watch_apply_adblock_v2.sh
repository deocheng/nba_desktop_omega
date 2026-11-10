#!/usr/bin/env bash
# watch_apply_adblock_v2.sh — v2（修复 2026-08-16 代码审查 P0-③）
#
# 相对 watch_apply_adblock.sh（原版保留不动）的修复：
#   [P0-③] pkill 模式 "recrawl_2004_2026.sh" 是正则，永远匹配不到现役
#          recrawl_2004_2026_autofill.sh → 停不掉 driver。v2 模式统一为
#          "recrawl_2004_2026"（覆盖 .sh 与 _autofill.sh），且改两段式
#          TERM→确认→KILL→确认，死透才继续（与 watchdog_v2 同一套纪律）。
#   [顺带] Chrome 就绪探测弃用 `PUT /json/new?about:blank`（MEMORY 铁律：
#          会泄漏空白 tab）→ 改 GET /json/version + GET /json/list 双探，
#          零 tab 创建。
#   [顺带] start_crawler 启动现役 driver（recrawl_2004_2026_autofill.sh），
#          原版写死的旧 recrawl_2004_2026.sh 已退役。
#   [顺带] 冒烟窗口 180s→420s，且只统计「重启之后新写入」的日志行，
#          避免把重启前的历史 ERR 计入误判。
#
# 其余流程（等 2026 完成 → 备份 cookie → 清 AI 模型 → 迁 profile →
# 重启 Chrome(adblock|safe) → 冒烟 → 回滚）与原版一致。
ROOT=/Volumes/12T/NBA/nba_desktop_omega_mac_migrate_2026-07-13
CRAWLER=$ROOT/external_crawler/crawler
LOGDIR=$ROOT/logs
STATE=$LOGDIR/recrawl_done_2004_2026.txt
WLOG=$LOGDIR/watch_apply_adblock_v2.log
OLD_PROFILE=/tmp/chrome_cdp_profile
PROFILE=/Volumes/12T/NBA/chrome_cdp_profile
CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
CDP=http://127.0.0.1:9223
DRIVER=recrawl_2004_2026_autofill.sh     # 现役 driver（原版写死旧 .sh 已退役）
KILL_TERM_WAIT=15
KILL_KILL_WAIT=15

log() { echo "[$(date '+%F %T')] $*" | tee -a "$WLOG"; }

# ---- v2：两段式停止爬虫树（模式串覆盖新旧 driver 名）----
kill_crawler_tree() {
  local label="$1" i pid pgid
  pgrep -f 'recrawl_2004_2026' >/dev/null 2>&1 || pgrep -f 'crawl_br_gamelog.py' >/dev/null 2>&1 || { log "[kill:$label] 无爬虫进程"; return 0; }
  log "[kill:$label] SIGTERM → recrawl_2004_2026* / crawl_br_gamelog.py"
  pkill -TERM -f 'recrawl_2004_2026' 2>/dev/null
  pkill -TERM -f 'crawl_br_gamelog.py' 2>/dev/null
  for i in $(seq 1 "$KILL_TERM_WAIT"); do
    sleep 1
    pgrep -f 'recrawl_2004_2026' >/dev/null 2>&1 || pgrep -f 'crawl_br_gamelog.py' >/dev/null 2>&1 || { log "[kill:$label] TERM 后 ${i}s 退净"; return 0; }
  done
  log "[kill:$label] TERM 未退净，升级 kill -9（逐 pgid）"
  for pid in $(pgrep -f 'recrawl_2004_2026' 2>/dev/null) $(pgrep -f 'crawl_br_gamelog.py' 2>/dev/null); do
    pgid=$(ps -o pgid= -p "$pid" 2>/dev/null | tr -d ' ')
    [ -n "$pgid" ] && kill -9 -"$pgid" 2>/dev/null
    kill -9 "$pid" 2>/dev/null
  done
  for i in $(seq 1 "$KILL_KILL_WAIT"); do
    sleep 1
    pgrep -f 'recrawl_2004_2026' >/dev/null 2>&1 || pgrep -f 'crawl_br_gamelog.py' >/dev/null 2>&1 || { log "[kill:$label] KILL 后 ${i}s 全部消失"; return 0; }
  done
  log "[kill:$label] !! 仍有残留，返回失败"
  return 1
}

# ── 1. 等 2026 完成 ────────────────────────────────────────────────────────
log "watcher-v2 启动，等待 season 2026 完成…"
while ! grep -qxF 2026 "$STATE" 2>/dev/null; do
  sleep 60
done
log "season 2026 已完成（STATE 落盘）。开始切换。"

# ── 2. 停爬虫（v2：两段式 + 模式串修复）────────────────────────────────────
kill_crawler_tree "phase2" || log "!! 爬虫未死透，继续切换（脚本幂等，残留进程稍后由看门狗处理）"

# ── 3. 备份 cookie ─────────────────────────────────────────────────────────
mkdir -p /Volumes/12T/NBA/cdp_cookie_backup
cp "$OLD_PROFILE/Default/Cookies" \
   "/Volumes/12T/NBA/cdp_cookie_backup/Cookies_$(date +%Y%m%d_%H%M)_premigrate.bak" 2>/dev/null \
   && log "cookie 已备份（源：${OLD_PROFILE}）。"

# ── 3b. 停 Chrome → 清 AI 模型 → 迁 profile ────────────────────────────────
pkill -f "remote-debugging-port=9223" 2>/dev/null
sleep 6
log "Chrome 已停止，开始清理与迁移。"

if [ ! -d /Volumes/12T/NBA ]; then
  log "!! 数据盘未挂载，放弃迁移，保持 $OLD_PROFILE 原地运行。"
  PROFILE="$OLD_PROFILE"
else
  AIDIR="$OLD_PROFILE/OptGuideOnDeviceModel"
  case "$AIDIR" in
    /tmp/chrome_cdp_profile/OptGuideOnDeviceModel)
      if [ -d "$AIDIR" ]; then
        SZ=$(du -sh "$AIDIR" 2>/dev/null | cut -f1)
        rm -rf "$AIDIR" && log "已清除端侧 AI 模型（${SZ}）。"
      fi ;;
    *) log "!! AI 模型路径校验未通过，跳过清理：$AIDIR" ;;
  esac

  if [ -d "$OLD_PROFILE/Default" ] && [ ! -d "$PROFILE/Default" ]; then
    log "迁移 $OLD_PROFILE -> ${PROFILE}（约 $(du -sh "$OLD_PROFILE" 2>/dev/null | cut -f1)）…"
    if mv "$OLD_PROFILE" "$PROFILE" 2>>"$WLOG"; then
      log "迁移完成。"
    else
      log "mv 失败（跨卷？），改用 cp -a …"
      if cp -a "$OLD_PROFILE" "$PROFILE" 2>>"$WLOG"; then
        rm -rf "$OLD_PROFILE"
        log "cp -a 迁移完成，源目录已清理。"
      else
        log "!! 迁移失败，回退使用 ${OLD_PROFILE}。"
        PROFILE="$OLD_PROFILE"
      fi
    fi
  elif [ -d "$PROFILE/Default" ]; then
    log "目标已存在 profile，跳过迁移。"
  fi
fi

CFN=$(strings "$PROFILE/Default/Cookies" 2>/dev/null | grep -c cf_clearance)
log "迁移后 cf_clearance 命中: ${CFN} 处"
[ "${CFN:-0}" -eq 0 ] && log "!! cf_clearance 丢失，可能需要人工在 Chrome 窗口点 Verify you are human。"

# ── 3c. 重启 Chrome（v2：就绪探测零 tab 创建）──────────────────────────────
restart_chrome() {
  pkill -f "remote-debugging-port=9223" 2>/dev/null
  sleep 6
  if [ "$1" = "adblock" ]; then
    ( cd "$ROOT" && env -u HTTP_PROXY -u HTTPS_PROXY -u http_proxy -u https_proxy \
        python3 detach_launch.py /tmp/chrome_cdp.log bash launch_chrome_cdp.sh )
  else
    env -u HTTP_PROXY -u HTTPS_PROXY -u http_proxy -u https_proxy \
      python3 "$ROOT/detach_launch.py" /tmp/chrome_cdp.log \
      "$CHROME" --remote-debugging-port=9223 --user-data-dir="$PROFILE" \
      --no-sandbox --no-proxy-server --no-first-run --no-default-browser-check \
      --disable-features=OptimizationGuideOnDeviceModel,OptimizationHints \
      --disk-cache-size=104857600 \
      "https://www.basketball-reference.com"
  fi
  # v2：GET /json/version（端口活）+ GET /json/list（DevTools 域活）。
  #     绝不用 PUT /json/new —— 每次调用都新建空白 tab（MEMORY 铁律）。
  for i in $(seq 1 24); do
    sleep 5
    CODE=$(curl -s --noproxy '*' --max-time 8 -o /dev/null -w '%{http_code}' "$CDP/json/version" 2>/dev/null)
    NTAB=$(curl -s --noproxy '*' --max-time 8 "$CDP/json/list" 2>/dev/null | grep -c '"id"')
    if [ "$CODE" = "200" ] && [ "${NTAB:-0}" -ge 1 ]; then
      log "Chrome($1) 就绪（/json/version=200，现有 tab ${NTAB} 个，第 ${i} 次探测）。"
      return 0
    fi
  done
  log "!! Chrome($1) 起不来（CDP 未就绪）。"
  return 1
}

start_crawler() {
  ( cd "$CRAWLER" && env -u HTTP_PROXY -u HTTPS_PROXY -u http_proxy -u https_proxy \
      python3 "$ROOT/detach_launch.py" "$LOGDIR/recrawl_launcher_desc.log" \
      bash "$DRIVER" )
  sleep 20
  log "driver（${DRIVER}）已重启。"
}

restart_chrome adblock || { log "!! 广告拦截版启动失败，回落保守版。"; restart_chrome safe; }

# 冒烟基线：记录重启时刻，稍后只统计 mtime 晚于该时刻的新日志
RESTART_TS=$(date +%s)
start_crawler

# ── 4. 冒烟（v2：420s 窗口 + 只看重启后的新日志）───────────────────────────
sleep 420
NEWLOG=$(ls -t "$LOGDIR"/recrawl_gamelog_20*.log 2>/dev/null | head -1)
if [ -z "$NEWLOG" ]; then
  log "!! 冒烟失败：找不到任何 recrawl 日志。"
  ERRN=999
else
  LOG_MTIME=$(stat -f %m "$NEWLOG" 2>/dev/null || echo 0)
  if [ "$LOG_MTIME" -lt "$RESTART_TS" ]; then
    log "!! 冒烟失败：最新日志 $(basename "$NEWLOG") 早于重启时刻（driver 可能没起来）。"
    ERRN=999
  else
    ERRN=$(grep -c "ERR:" "$NEWLOG" 2>/dev/null || echo 0)
    DONEN=$(grep -c "场" "$NEWLOG" 2>/dev/null || echo 0)
    log "冒烟：$(basename "$NEWLOG") 成功 ${DONEN} 人 / ERR ${ERRN}（仅统计重启后日志）"
  fi
fi

if [ "${ERRN:-0}" -gt 15 ]; then
  log "!! ERR 超阈值，判定广告拦截误伤 -> 回滚为保守配置。"
  kill_crawler_tree "rollback" || log "!! 回滚前爬虫未死透"
  restart_chrome safe && start_crawler
  log "已回滚到保守配置（无广告域黑洞）并重启爬虫。"
else
  log "广告拦截配置生效且无误伤。切换完成。"
fi

# ── 5. 记录效果 ────────────────────────────────────────────────────────────
sleep 5
log "target 数: $(curl -s --noproxy '*' --max-time 8 $CDP/json | grep -c '\"id\"')"
log "Cache 体积: $(du -sh $PROFILE/Default/Cache 2>/dev/null | cut -f1)"
log "cf_clearance: $(strings $PROFILE/Default/Cookies 2>/dev/null | grep -c cf_clearance) 处"
log "watcher-v2 结束。"
