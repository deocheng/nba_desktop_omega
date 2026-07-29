#!/usr/bin/env bash
# Autonomous 3-stage crawler orchestrator for NBA team pages.
# Single-process invariant: stages run sequentially, never concurrently.
# This script's own process is "bash run_crawl_all.sh", which does NOT
# contain the substring "crawl_team_pages", so `pgrep -f crawl_team_pages`
# only ever matches the actual python crawler children (no self-match deadlock).
set -u

ROOT=/Users/deocheng/Downloads/nba_desktop_omega_mac_migrate_2026-07-13
cd "$ROOT" || exit 1

ts() { date '+%Y-%m-%d %H:%M:%S'; }

run_stage() {
  local ys="$1" ye="$2" name="$3"
  echo "[$(ts)] === STAGE $name start (years $ys-$ye) ==="
  .venv/bin/python -m crawl_team_pages --all-teams --year-start "$ys" --year-end "$ye" > "team_pages_${name}.log" 2>&1
  local rc=$?
  echo "[$(ts)] === STAGE $name done (exit $rc) ==="
  return $rc
}

if pgrep -f "crawl_team_pages" >/dev/null 2>&1; then
  echo "[$(ts)] in-flight crawler detected (stage1 in progress); waiting for it to finish"
  while pgrep -f "crawl_team_pages" >/dev/null 2>&1; do
    sleep 60
  done
  echo "[$(ts)] stage1 crawler finished; proceeding to remaining stages"
  run_stage 1980 2000 stage2
  run_stage 1947 1979 stage3
else
  echo "[$(ts)] no crawler running; executing full pipeline stage1->stage2->stage3"
  run_stage 2000 2026 stage1
  run_stage 1980 2000 stage2
  run_stage 1947 1979 stage3
fi

echo "[$(ts)] === ALL CRAWL STAGES COMPLETE ==="
