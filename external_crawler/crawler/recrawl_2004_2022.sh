#!/usr/bin/env bash
# recrawl_2004_2022.sh — 用已修复的 crawl_br_gamelog.py 全量重爬 2004–2022 球员 gamelog。
# 背景：07-04 批次用错误的 gameid 编码写入、且只有身份无数据；已整体清空 2004–2022
# (备份在 player_gamelog_recrawl_bak_20260805)，此处用修正后的爬虫按当前 gameid 重新入库。
# 幂等：爬虫每场先 delete_existing(gameid, br_player_id) 再 INSERT；唯一索引兜底防重复。
set -u
ROOT=/Volumes/12T/NBA/nba_desktop_omega_mac_migrate_2026-07-13
CRAWLER=$ROOT/external_crawler/crawler
PY=$ROOT/.venv/bin/python
LOGDIR=$ROOT/logs
mkdir -p "$LOGDIR"
STATE=$LOGDIR/recrawl_done_2004_2022.txt
MASTERLOG=$LOGDIR/recrawl_2004_2022_master.log

# DB 口令取自本机 .env（明文，仅本机）
export DB_PASSWORD="$(grep '^DB_PASSWORD=' "$ROOT/.env" | head -1 | cut -d= -f2-)"
# 驱动用户已通过 CF 的 Chrome（9223），复用其 cf_clearance，避免无头浏览器反复撞墙
export BROWSER_BACKEND=cdp
export CHROME_CDP_URL=http://127.0.0.1:9223
# 剥离死代理（否则 CDP/网络走代理 → 假 502 / 连接失败）
unset HTTP_PROXY HTTPS_PROXY http_proxy https_proxy
export NO_PROXY='*' no_proxy='*'

SEASONS=(2004 2005 2006 2007 2008 2009 2010 2011 2012 2013 2014 2015 2016 2017 2018 2019 2020 2021 2022)

cd "$CRAWLER"
echo "===== RECRAWL START $(date) =====" | tee -a "$MASTERLOG"
for S in "${SEASONS[@]}"; do
  if grep -qxF "$S" "$STATE" 2>/dev/null; then
    echo "----- skip season $S (already done) -----" | tee -a "$MASTERLOG"
    continue
  fi
  LOG="$LOGDIR/recrawl_gamelog_${S}.log"
  echo "===== $(date) START season $S =====" | tee -a "$MASTERLOG"
  "$PY" crawl_br_gamelog.py --season "$S" >> "$LOG" 2>&1
  RC=$?
  echo "===== $(date) END season $S (rc=$RC) =====" | tee -a "$MASTERLOG"
  if [ "$RC" -eq 0 ]; then
    echo "$S" >> "$STATE"
  else
    echo "!! season $S failed (rc=$RC); will retry on next run" | tee -a "$MASTERLOG"
  fi
done
echo "===== RECRAWL FINISH $(date) =====" | tee -a "$MASTERLOG"
