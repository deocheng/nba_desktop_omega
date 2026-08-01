#!/usr/bin/env bash
# run_after_shot_chart.sh — 接力调度器（2026-07-27）
# 作用：等待 shot chart 爬虫（crawl_br_player_shot_chart.py）自然结束后，
#       自动拉起 run_team_data.sh（Phase 1: Team PBP + logo 回填）。
# 目的：避免两个 BR 爬虫共用 CDP 9222 并行抓取导致请求频率翻倍触发屏蔽
#       （防屏蔽铁律，2026-07-27 屏蔽事故教训）。
# 运行：nohup ./run_after_shot_chart.sh > /Volumes/12T/NBA/relay_scheduler.log 2>&1 &
set -u
cd "$(dirname "$0")"

export PGPASSWORD='R!h0N-ctlg=xB01V_-1VJcFeCCuBjS6UCvV1'

PATTERN='crawl_br_player_shot_chart.py'
CHECK_INTERVAL=120   # 每 2 分钟探测一次

echo "=== [$(date)] 接力调度器启动：等待 shot chart 爬虫结束 ==="
echo "    探测模式: pgrep -f ${PATTERN} (间隔 ${CHECK_INTERVAL}s)"

while pgrep -f "$PATTERN" > /dev/null 2>&1; do
    sleep "$CHECK_INTERVAL"
done

echo "=== [$(date)] shot chart 爬虫已结束 ==="
# 缓冲：让 Chrome CDP / DB 连接释放干净，并额外留出 BR 冷却时间
sleep 60

# 完成守卫（2026-07-28 修补）：进程退出 ≠ 真的跑完。
# 校验「已完成对 == 宇宙对」才放行 Phase1，否则极可能是撞死/崩溃，
# 误启动 Phase1 会让大量 shot chart 数据被 --resume 永久跳过。
DONE=$(/opt/homebrew/bin/psql -h localhost -p 5433 -U postgres -d nba -t -A -c "SELECT COUNT(DISTINCT (player_id,season)) FROM player_shot_chart;" 2>/dev/null | tail -1 | tr -d ' ')
UNIV=$(/opt/homebrew/bin/psql -h localhost -p 5433 -U postgres -d nba -t -A -c "SELECT COUNT(DISTINCT (player_id,season)) FROM player_shooting;" 2>/dev/null | tail -1 | tr -d ' ')
if [ -n "$UNIV" ] && [ "$DONE" != "$UNIV" ]; then
    echo "!! [$(date)] 未完成（完成 $DONE / 宇宙 $UNIV），疑似爬虫提前退出。不启动 Phase1。"
    echo "!! 请排查 shot chart 爬虫停止原因并修复后重跑，勿让 Phase1 抢跑。"
    exit 1
fi

# 安全检查：确认 Chrome CDP 9222 仍可达（用户 Chrome 还开着）
if ! curl -s --max-time 5 "http://127.0.0.1:9222/json/version" > /dev/null 2>&1; then
    echo "!! [$(date)] Chrome CDP 9222 不可达，无法启动 Phase 1。"
    echo "!! 请重新以调试模式启动 Chrome 并手动过 CF 后，手动运行 ./run_team_data.sh"
    exit 1
fi

echo "=== [$(date)] 启动 Phase 1（Team PBP + logo，--resume 自动跳过已落库） ==="
./run_team_data.sh
echo "=== [$(date)] 接力调度器结束 ==="
