#!/usr/bin/env bash
# NBACore v8 — 数据到位后一键建库/灌结构/灌数据 (macOS)
# 前置: nba_csv/ 已拷到本目录同级 (与 _import_csv_to_db.py 同级)
# 用法: bash migrate_db.sh
set -e

DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

PGDATA="$HOME/nba_pg"
PGPORT=5433
PGUSER=postgres
PGDB=nba
CSV_DIR="/Users/deocheng/Downloads/nba_csv"

echo "===== [0] 检查 nba_csv ====="
if [ ! -d "$CSV_DIR" ]; then
  echo "[ERROR] 未找到 $CSV_DIR —— CSV 数据还没到位,请先拷 nba_csv/ 到项目根同级"
  exit 1
fi
CSV_N=$(ls -1 "$CSV_DIR"/*.csv 2>/dev/null | wc -l | tr -d ' ')
echo "[OK] nba_csv/ 已就位, 含 $CSV_N 个 CSV"

echo "===== [1] PostgreSQL (端口 $PGPORT) ====="
if nc -z -w2 127.0.0.1 "$PGPORT" 2>/dev/null; then
  echo "[OK] 5433 已在监听, 跳过 initdb"
else
  echo "[*] 初始化/启动 PG ..."
  if [ ! -d "$PGDATA/base" ]; then
    initdb -D "$PGDATA" -U "$PGUSER" -A trust -E UTF8 >/dev/null 2>&1
    echo "    initdb done"
  fi
  pg_ctl -D "$PGDATA" -o "-p $PGPORT -k /tmp" -l "$PGDATA/pg.log" start
  sleep 3
fi

echo "===== [2] 建库 nba (若不存在) ====="
if psql -p "$PGPORT" -h localhost -U "$PGUSER" -tc "SELECT 1 FROM pg_database WHERE datname='$PGDB'" | grep -q 1; then
  echo "[OK] 库 $PGDB 已存在"
else
  createdb -p "$PGPORT" -h localhost -U "$PGUSER" "$PGDB"
  echo "[OK] 建库 $PGDB done"
fi
psql -p "$PGPORT" -h localhost -U "$PGUSER" -c "ALTER USER $PGUSER PASSWORD '$PGUSER';" >/dev/null 2>&1 || true

echo "===== [3] 灌表结构 nba_schema_only.sql ====="
psql -p "$PGPORT" -h localhost -U "$PGUSER" -d "$PGDB" -f nba_schema_only.sql
TBL=$(psql -p "$PGPORT" -h localhost -U "$PGUSER" -d "$PGDB" -tAc "SELECT count(*) FROM information_schema.tables WHERE table_schema='public' AND table_type='BASE TABLE';")
echo "[OK] public 表数 = $TBL (期望 59)"

echo "===== [4] 灌 CSV 数据 (大表 play_by_play 约数分钟) ====="
"$DIR/.venv/bin/python" "$DIR/_import_csv_to_db.py" --csv-dir "$CSV_DIR" --port "$PGPORT"

echo "===== [5] 校验 ====="
PBP=$(psql -p "$PGPORT" -h localhost -U "$PGUSER" -d "$PGDB" -tAc "SELECT count(*) FROM play_by_play;" 2>/dev/null || echo "n/a")
echo "[DONE] play_by_play 行数 = $PBP (期望 ≈ 18,370,598)"
echo "下一步: ./start_mac.sh  (会自动装依赖并起 uvicorn :5577)"
