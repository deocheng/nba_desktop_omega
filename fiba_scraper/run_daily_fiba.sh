#!/usr/bin/env bash
# Daily FIBA incremental scrape — self-healing wrapper.
#
# Chain: ensure PG (5433) -> daily_scrape_fiba.py -> recover_pbp_from_archive.py
#
# Why the wrapper exists
# ----------------------
# 1) The PG cluster on 5433 lives on an external volume and can be down.
#    `daily_scrape_fiba.py` tries to start it itself, but its pg_ctl call has NO
#    LC_ALL, and PG18 on macOS then dies with
#      "FATAL: postmaster became multithreaded during startup"
#    so its auto-start can never succeed. Here we start it with LC_ALL=C.
# 2) The cluster is normally kept alive by the launchd agent
#    com.nba.pg5433 (RunAtLoad + KeepAlive), so if it's down we first give
#    launchd a short window to self-heal before starting it by hand.
# 3) Even when the scrape runs, a DB write can fail after the raw payload was
#    already archived. FIBA's live feed expires (~17h) so that data can never be
#    re-fetched — recover_pbp_from_archive.py replays it from the archive.

set -uo pipefail

PY="/Volumes/12T/NBA/nba_desktop_omega_mac_migrate_2026-07-13/.venv/bin/python"
DIR="/Volumes/12T/NBA/nba_desktop_omega_mac_migrate_2026-07-13/fiba_scraper"
PGCTL="/opt/homebrew/opt/postgresql@18/bin/pg_ctl"
PGREADY="/opt/homebrew/opt/postgresql@18/bin/pg_isready"
PGDATA="/Volumes/12T/NBA/nba_pg"
PGLOG="/Volumes/12T/NBA/nba_pg/pg.log"
HOST="127.0.0.1"
PORT="5433"

log() { echo "[wrapper $(date '+%F %T')] $*"; }

up() { "$PGREADY" -h "$HOST" -p "$PORT" >/dev/null 2>&1; }

# --- 1) ensure the cluster is accepting connections -------------------------
if ! up; then
  log "PG not ready — giving launchd up to 30s to self-heal…"
  for _ in $(seq 1 6); do
    sleep 5
    if up; then log "PG recovered by launchd."; break; fi
  done
fi

if ! up; then
  log "still down — starting manually with LC_ALL=C (required on macOS/PG18)."
  LC_ALL=C "$PGCTL" -D "$PGDATA" -o "-p $PORT" -l "$PGLOG" start
  for _ in $(seq 1 12); do
    sleep 5
    if up; then log "PG is up (manual start)."; break; fi
  done
fi

if ! up; then
  log "ERROR: PG still unreachable on $HOST:$PORT — aborting."
  exit 1
fi

# --- 2) incremental scrape (boxscore refresh + PBP in retention window) -----
log "running daily_scrape_fiba.py …"
"$PY" "$DIR/daily_scrape_fiba.py"
rc=$?
log "daily_scrape_fiba.py exit=$rc"

# --- 3) replay any archived payload that never landed in the DB -------------
# Read-only dry run first so the log always records what was missing.
log "checking for archived PBP missing from the DB …"
"$PY" "$DIR/recover_pbp_from_archive.py" | sed 's/^/  /'
log "recovering (if anything is missing) …"
"$PY" "$DIR/recover_pbp_from_archive.py" --apply | sed 's/^/  /'

exit "$rc"
