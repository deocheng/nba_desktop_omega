#!/usr/bin/env bash
# watch_apply_adblock.sh — 等 season 2026 重爬跑完后，自动重启 Chrome 应用广告拦截配置，
# 再把重爬脚本接回来继续 2025→2004。
#
# 背景（2026-08-06）：
#   BR 每页 ~50 个广告 iframe → Chrome 缓存堆到 1.2G、target 数 64、内存/swap 吃紧
#   → Chrome fork 不出渲染进程 → Target.createTarget 返回 HTTP 500 → 爬虫整季空转。
#   `launch_chrome_cdp.sh` 已加 --host-resolver-rules 黑洞 30 个广告域 + 关端侧 AI 模型
#   + 磁盘缓存上限 100MB，但需要重启 Chrome 才生效。用户要求「等 25-26 赛季跑完再处理」。
#
# 行为：
#   1. 轮询 STATE 文件，等 "2026" 落盘（= season 2026 rc=0 完成）。
#   2. 停掉重爬脚本与其子爬虫（中断损失几分钟，脚本幂等）。
#   3. 备份 cookie → 清 4.0G 端侧 AI 模型 → profile 从 /tmp 迁到数据盘
#      → 重启 Chrome（新配置）→ 校验 CDP 可建 target。
#   4. 重启重爬脚本（STATE 会自动 skip 2004-2012 与 2026，从 2025 续跑）。
#   5. 冒烟：3 分钟后查新季日志 ERR 数；若 >15 判定广告拦截误伤，
#      自动回滚为「不带 --host-resolver-rules」的保守启动并再次重启爬虫。
#
# profile 迁移说明（2026-08-06 用户要求）：
#   /tmp/chrome_cdp_profile 位于系统数据卷 disk3s5，长期爬取堆到 4.5G，
#   且 /tmp 有被系统清理的风险（一旦清掉 cf_clearance 就要人工重过 CF）。
#   迁到 /Volumes/12T/NBA/chrome_cdp_profile（与 nba_pg / raw_archive 同级，
#   不放进 git 仓库避免污染）。其中 4.0G 的 OptGuideOnDeviceModel 是 Chrome
#   端侧 AI 模型（Gemini Nano），与爬取无关，不搬直接清掉；新启动参数已用
#   --disable-features 阻止它重新下载。实际搬运量约 500M。
#
# 用法（必须 detach 启动，否则会话结束被带走）：
#   env -u HTTP_PROXY -u HTTPS_PROXY -u http_proxy -u https_proxy \
#     python3 detach_launch.py <logfile> bash watch_apply_adblock.sh

ROOT=/Volumes/12T/NBA/nba_desktop_omega_mac_migrate_2026-07-13
CRAWLER=$ROOT/external_crawler/crawler
LOGDIR=$ROOT/logs
STATE=$LOGDIR/recrawl_done_2004_2026.txt
WLOG=$LOGDIR/watch_apply_adblock.log
OLD_PROFILE=/tmp/chrome_cdp_profile
PROFILE=/Volumes/12T/NBA/chrome_cdp_profile
CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
CDP=http://127.0.0.1:9223

log() { echo "[$(date '+%F %T')] $*" | tee -a "$WLOG"; }

# ── 1. 等 2026 完成 ────────────────────────────────────────────────────────
log "watcher 启动，等待 season 2026 完成…"
while ! grep -qxF 2026 "$STATE" 2>/dev/null; do
  sleep 60
done
log "season 2026 已完成（STATE 落盘）。开始切换。"

# ── 2. 停爬虫 ─────────────────────────────────────────────────────────────
pkill -f "recrawl_2004_2026.sh" 2>/dev/null
sleep 2
pkill -f "crawl_br_gamelog.py" 2>/dev/null
sleep 5
log "重爬进程已停止。"

# ── 3. 备份 cookie（迁移前，profile 此刻仍在 OLD_PROFILE）──────────────────
mkdir -p /Volumes/12T/NBA/cdp_cookie_backup
cp "$OLD_PROFILE/Default/Cookies" \
   "/Volumes/12T/NBA/cdp_cookie_backup/Cookies_$(date +%Y%m%d_%H%M)_premigrate.bak" 2>/dev/null \
   && log "cookie 已备份（源：$OLD_PROFILE）。"

# ── 3b. 停 Chrome → 清 4G AI 模型 → 迁移 profile 到数据盘 ──────────────────
pkill -f "remote-debugging-port=9223" 2>/dev/null
sleep 6
log "Chrome 已停止，开始清理与迁移。"

if [ ! -d /Volumes/12T/NBA ]; then
  log "!! 数据盘未挂载，放弃迁移，保持 $OLD_PROFILE 原地运行。"
  PROFILE="$OLD_PROFILE"
else
  # 清端侧 AI 模型（Gemini Nano，与爬取无关，实测 4.0G）。
  # 路径白名单校验，避免变量意外为空导致误删。
  AIDIR="$OLD_PROFILE/OptGuideOnDeviceModel"
  case "$AIDIR" in
    /tmp/chrome_cdp_profile/OptGuideOnDeviceModel)
      if [ -d "$AIDIR" ]; then
        SZ=$(du -sh "$AIDIR" 2>/dev/null | cut -f1)
        rm -rf "$AIDIR" && log "已清除端侧 AI 模型（$SZ）。"
      fi ;;
    *) log "!! AI 模型路径校验未通过，跳过清理：$AIDIR" ;;
  esac

  if [ -d "$OLD_PROFILE/Default" ] && [ ! -d "$PROFILE/Default" ]; then
    log "迁移 $OLD_PROFILE -> $PROFILE（约 $(du -sh "$OLD_PROFILE" 2>/dev/null | cut -f1)）…"
    if mv "$OLD_PROFILE" "$PROFILE" 2>>"$WLOG"; then
      log "迁移完成。"
    else
      # 跨卷 mv 失败 -> 退回 cp -a 再删源
      log "mv 失败（跨卷？），改用 cp -a …"
      if cp -a "$OLD_PROFILE" "$PROFILE" 2>>"$WLOG"; then
        rm -rf "$OLD_PROFILE"
        log "cp -a 迁移完成，源目录已清理。"
      else
        log "!! 迁移失败，回退使用 $OLD_PROFILE。"
        PROFILE="$OLD_PROFILE"
      fi
    fi
  elif [ -d "$PROFILE/Default" ]; then
    log "目标已存在 profile，跳过迁移。"
  fi
fi

# 迁移后校验 cf_clearance 是否完好（丢了要人工重过 CF，必须显式告警）
CFN=$(strings "$PROFILE/Default/Cookies" 2>/dev/null | grep -c cf_clearance)
log "迁移后 cf_clearance 命中: ${CFN} 处"
[ "${CFN:-0}" -eq 0 ] && log "!! cf_clearance 丢失，可能需要人工在 Chrome 窗口点 Verify you are human。"

# ── 3c. 重启 Chrome（新配置）───────────────────────────────────────────────

restart_chrome() {
  # $1 = "adblock" | "safe"（safe = 不带 host-resolver-rules，用于误伤回滚）
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
  # 等 CDP 就绪并确认能建 target（只查 /json/version 会漏判，见 MEMORY）
  for i in $(seq 1 24); do
    sleep 5
    TID=$(curl -s --noproxy '*' --max-time 8 -X PUT "$CDP/json/new?about:blank" \
          | grep '"id"' | head -1 | sed 's/.*"id": "//;s/".*//')
    if [ -n "$TID" ]; then
      curl -s --noproxy '*' --max-time 6 "$CDP/json/close/$TID" >/dev/null
      log "Chrome($1) 就绪，createTarget 正常（第 ${i} 次探测）。"
      return 0
    fi
  done
  log "!! Chrome($1) 起不来或无法建 target。"
  return 1
}

start_crawler() {
  ( cd "$CRAWLER" && env -u HTTP_PROXY -u HTTPS_PROXY -u http_proxy -u https_proxy \
      python3 "$ROOT/detach_launch.py" "$LOGDIR/recrawl_launcher_desc.log" \
      bash recrawl_2004_2026.sh )
  sleep 20
  log "重爬脚本已重启。"
}

restart_chrome adblock || { log "!! 广告拦截版启动失败，回落保守版。"; restart_chrome safe; }
start_crawler

# ── 4. 冒烟：3 分钟后检查是否误伤 ──────────────────────────────────────────
sleep 180
NEWLOG=$(ls -t "$LOGDIR"/recrawl_gamelog_20*.log 2>/dev/null | head -1)
ERRN=$(grep -c "ERR:" "$NEWLOG" 2>/dev/null || echo 0)
DONEN=$(grep -c "场" "$NEWLOG" 2>/dev/null || echo 0)
log "冒烟：$(basename "$NEWLOG") 成功 ${DONEN} 人 / ERR ${ERRN}"

if [ "$ERRN" -gt 15 ]; then
  log "!! ERR 超阈值，判定广告拦截误伤 -> 回滚为保守配置。"
  pkill -f "recrawl_2004_2026.sh" 2>/dev/null; sleep 2
  pkill -f "crawl_br_gamelog.py" 2>/dev/null; sleep 5
  restart_chrome safe && start_crawler
  log "已回滚到保守配置（无广告域黑洞）并重启爬虫。"
else
  log "广告拦截配置生效且无误伤。切换完成。"
fi

# ── 5. 记录效果 ───────────────────────────────────────────────────────────
sleep 5
log "target 数: $(curl -s --noproxy '*' --max-time 8 $CDP/json | grep -c '\"id\"')"
log "Cache 体积: $(du -sh $PROFILE/Default/Cache 2>/dev/null | cut -f1)"
log "cf_clearance: $(strings $PROFILE/Default/Cookies 2>/dev/null | grep -c cf_clearance) 处"
log "watcher 结束。"
