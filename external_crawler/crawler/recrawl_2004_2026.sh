#!/usr/bin/env bash
# recrawl_2004_2026.sh — 用已修复(含 MP 解析)的 crawl_br_gamelog.py 全量重爬 2004–2026 球员 gamelog。
# 背景：07-04 批次用错误的 gameid 编码写入、且只有身份无数据；2004-2022 此前已清空重爬。
# 本轮扩展覆盖 2023/2024/2025/2026（修复版含 MP→minutes），并对 2026 这类混有旧编码行的季先清除错配行。
# 每季开爬前先删 gameid 与 dim_games.nba_api_id 错配的旧编码行，避免重爬后留脏副本。
# 幂等：爬虫每场先 delete_existing(gameid, br_player_id) 再 INSERT；唯一索引兜底防重复。
# 注：本脚本不启用 set -u —— 此前 watcher 因 set -u 在「中文日志串 + 反斜杠续行」组合下
# 变量展开失效而崩溃（SRC_PROFILE unbound）。保持简单，未定义变量当空串更安全。
ROOT=/Volumes/12T/NBA/nba_desktop_omega_mac_migrate_2026-07-13
CRAWLER=$ROOT/external_crawler/crawler
PY=$ROOT/.venv/bin/python
LOGDIR=$ROOT/logs
mkdir -p "$LOGDIR"
STATE=$LOGDIR/recrawl_done_2004_2026.txt
MASTERLOG=$LOGDIR/recrawl_2004_2026_master.log

# DB 口令取自本机 .env（明文，仅本机）
export DB_PASSWORD="$(grep '^DB_PASSWORD=' "$ROOT/.env" | head -1 | cut -d= -f2-)"
# 驱动用户已通过 CF 的 Chrome（9223），复用其 cf_clearance，避免无头浏览器反复撞墙
export BROWSER_BACKEND=cdp
export CHROME_CDP_URL=http://127.0.0.1:9223
# 剥离死代理（否则 CDP/网络走代理 → 假 502 / 连接失败）
unset HTTP_PROXY HTTPS_PROXY http_proxy https_proxy
export NO_PROXY='*' no_proxy='*'

# 顺序：近季优先（2025-26 赛季 = season 2026 起往前倒推）。
# 理由：近期数据使用频率最高，先落地可用；老赛季排后面慢慢补。
# 已完成的季在 STATE 文件里会被自动 skip，不受顺序影响。
SEASONS=(2026 2025 2024 2023 2022 2021 2020 2019 2018 2017 2016 2015 2014 2013 2012 2011 2010 2009 2008 2007 2006 2005 2004)

cd "$CRAWLER"
echo "===== RECRAWL START $(date) =====" | tee -a "$MASTERLOG"

# 安全网：备份 2023-2026 全量（可回滚；2004-2022 已在 player_gamelog_recrawl_bak_20260805）
export PGPASSWORD="$DB_PASSWORD"
/opt/homebrew/opt/postgresql@18/bin/psql -h localhost -p 5433 -U postgres -d nba -t -A -c "
CREATE TABLE IF NOT EXISTS player_gamelog_recrawl_bak_20260805_2326 (LIKE player_gamelog INCLUDING ALL);
-- 幂等：仅在备份表为空时灌入（重启脚本不会重复插/撞唯一索引报错）
INSERT INTO player_gamelog_recrawl_bak_20260805_2326
SELECT * FROM player_gamelog WHERE season BETWEEN 2023 AND 2026
  AND NOT EXISTS (SELECT 1 FROM player_gamelog_recrawl_bak_20260805_2326);
SELECT 'backup 2023-2026 rows=' || count(*) FROM player_gamelog_recrawl_bak_20260805_2326;" 2>&1 | tee -a "$MASTERLOG"

for S in "${SEASONS[@]}"; do
  if grep -qxF "$S" "$STATE" 2>/dev/null; then
    echo "----- skip season $S (already done) -----" | tee -a "$MASTERLOG"
    continue
  fi
  # 清除本季 gameid 与 dim_games 错配的旧编码行（重爬按当前 gameid 删不掉，会留脏副本）
  /opt/homebrew/opt/postgresql@18/bin/psql -h localhost -p 5433 -U postgres -d nba -t -A -c "
    DELETE FROM player_gamelog
    WHERE season = $S
      AND (gameid IS NULL OR gameid::bigint NOT IN (SELECT DISTINCT nba_api_id FROM dim_games WHERE season = $S));" 2>&1 | sed "s/^/[pre-delete $S] /" | tee -a "$MASTERLOG"
  LOG="$LOGDIR/recrawl_gamelog_${S}.log"
  echo "===== $(date) START season $S =====" | tee -a "$MASTERLOG"
  # 前台跑爬虫：一季跑完才写 STATE；失败即停（不自动重启 Chrome，
  # 低内存环境下重启反而越重启越胖——会话恢复 + target 泄漏双重累积）。需人工释放主机内存后续跑。
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
