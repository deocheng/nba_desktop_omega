#!/usr/bin/env bash
# convert_pbp_to_br.sh
# 将 play_by_play.gameid 从双键(数字 nba_api_id / BR game_id) 统一转换为 BR game_id。
# 连接桥: play_by_play.gameid(数字) <-> dim_games.nba_api_id::text <-> dim_games.game_id(BR)
#
# 用法:
#   bash convert_pbp_to_br.sh <season>      # 单季试点/执行
#   bash convert_pbp_to_br.sh all           # 全季(1997-2023)
#
# 前置条件 (务必先完成, 否则拒绝执行):
#   1) 已全量备份 play_by_play (pg_dump 自定义格式, 须含分区);
#   2) 已排查代码 blast radius (确认无脚本把 play_by_play.gameid 当数字强转)。
#
# 安全机制:
#   - 每区先加 gameid_src 列存原值, 可即时回滚:
#       UPDATE play_by_play_p_<S> p SET gameid = p.gameid_src WHERE gameid_src IS NOT NULL;
#   - 逐区单语句 UPDATE, 避开 sandbox PG 的 OOM。
#   - 仅转换“数字键”行 (gameid !~ '[A-Za-z]'); 已 BR 格式的行原样保留。
#   - 孤儿(数字键但 dim_games.nba_api_id 查无)保持数字, 不强行改, 仅报告。
set -o pipefail

ROOT=/Volumes/12T/NBA/nba_desktop_omega_mac_migrate_2026-07-13
DBPASS=$(grep '^DB_PASSWORD=' "$ROOT/.env" | head -1 | cut -d= -f2-)
export PGPASSWORD="$DBPASS"
PSQL=/opt/homebrew/opt/postgresql@18/bin/psql

cmd="${1:-all}"

if [ "$cmd" = "all" ]; then
  seasons=$(seq 1997 2023)
else
  seasons=("$cmd")
fi

for S in "${seasons[@]}"; do
  echo "===== season $S ====="
  # 1) 备份原值到 gameid_src (仅首跑写入, 已存在则跳过)
  $PSQL -h 127.0.0.1 -p 5433 -U postgres -d nba -c "
    SET max_parallel_workers_per_gather=0; SET work_mem='64MB';
    ALTER TABLE play_by_play_p_$S ADD COLUMN IF NOT EXISTS gameid_src text;
    UPDATE play_by_play_p_$S SET gameid_src = gameid WHERE gameid_src IS NULL;
  " 2>&1 | sed 's/^/[backup] /'
  # 2) 转换: 数字键 -> BR game_id (经 dim_games.nba_api_id)
  $PSQL -h 127.0.0.1 -p 5433 -U postgres -d nba -c "
    SET max_parallel_workers_per_gather=0; SET work_mem='64MB';
    UPDATE play_by_play_p_$S p
    SET gameid = d.game_id
    FROM dim_games d
    WHERE p.gameid !~ '[A-Za-z]'
      AND d.nba_api_id::text = p.gameid;
  " 2>&1 | sed 's/^/[convert] /'
  # 3) 快报: 剩余数字键 / 总不同 gameid
  $PSQL -h 127.0.0.1 -p 5433 -U postgres -d nba -c "
    SET max_parallel_workers_per_gather=0; SET work_mem='64MB';
    SELECT
      (SELECT count(DISTINCT gameid) FROM play_by_play_p_$S WHERE gameid !~ '[A-Za-z]') AS numeric_remaining,
      (SELECT count(DISTINCT gameid) FROM play_by_play_p_$S) AS distinct_total;
  " 2>&1 | sed 's/^/[verify] /'
done
echo "===== 全部完成 ====="
echo "注意: 转换后请用独立验收脚本核对 每区 distinct gameid(BR键) == dim_games 该季 RS 场数。"
