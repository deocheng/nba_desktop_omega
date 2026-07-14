#!/bin/bash
cd /Users/deocheng/Downloads/nba_desktop_omega_mac_migrate_2026-07-13
# 注入 .env 中的 DB_PASSWORD 等机密到环境变量（供 Python 爬虫连接 PG）
set -a; [ -f "$PWD/.env" ] && . "$PWD/.env"; set +a
echo "[chain $(date +%H:%M:%S)] 等待旧批(br_fill_pbp 无--force)退出..."
while ps aux | grep -q "[b]r_fill_pbp"; do sleep 15; done
echo "[chain $(date +%H:%M:%S)] 旧批已退出, 启动 --force 增强轮补全全部377场(原始HTML+语义层+异常表)"
nohup .venv/bin/python br_fill_pbp.py --force > pbp_force.log 2>&1 &
echo "force PID=$!"
echo "[chain $(date +%H:%M:%S)] 监控 --force 轮直到完成..."
while ps aux | grep -q "br_fill_pbp.py --force"; do sleep 30; done
echo "=== --force 轮最终统计 $(date +%H:%M:%S) ==="
echo "成功场次(events=):"; grep -c "events=" pbp_force.log
echo "FAIL 总数:"; grep -c "FAIL" pbp_force.log
echo "404:"; grep -c "FAIL(404)" pbp_force.log
echo "其他FAIL:"; grep "FAIL" pbp_force.log | grep -v 404 | tail -8
echo "=== 日志末尾 ==="; tail -6 pbp_force.log
echo "[chain] 完成"
