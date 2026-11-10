"""Autonomous, caching, error-tolerant PBP backfill for FIBA games.

SOURCE OF TRUTH (reverse-engineered from FIBA's frontend bundle 2026-08-28):
  The ONLY place FIBA's website gets play-by-play is the live-info proxy route:
      GET https://www.fiba.basketball/en/events/api/game-live-info/{gameId}/detail
  The response JSON has TOP-LEVEL field `periodActions` (sibling of `game`):
      periodActions.content.items  ->  {Q1..Q4: {items:[ PBP event dicts ]}}
  There is NO getgdap* PBP function and NO separate replay endpoint (the
  getReplayVideosCard GraphQL is for *video* replays, not PBP). A WebSocket live
  feed exists but only pushes LIVE events and delivered nothing usable for backfill
  in soak testing, so REST is the single reliable channel.

BEHAVIOUR (per user instruction 2026-08-28: fully autonomous, cache, errors non-issue):
  * Polls ALL games' live-info/detail forever (or --once for a single pass).
  * Whenever `periodActions` is present, caches the raw JSON and upserts PBP
    (delete-then-insert, idempotent), flagging games.pbp_loaded.
  * NEVER deletes captured PBP when the feed is empty (protects historical data
    against FIBA's empty-response jitter / retention window).
  * Caches every raw response to raw_archive/<game_id>/liveinfo_<ts>.json so any
    run is replayable and nothing is lost.
  * Adaptive pacing: polls fast during a detected live window (a game is LIVE or
    finished within --window-hours), slow otherwise.
  * Every game wrapped in try/except; connection drops auto-restart local PG.
  * Manifest tracks per-game captured event counts; already-captured games with
    unchanged counts are skipped (unless --force) to save work.

Usage:
  backfill_pbp_rest.py [--once] [--poll-idle 600] [--poll-window 60]
                       [--window-hours 4] [--force] [--games 127604,127081]
                       [--manifest /path/manifest.json] [--cache-dir raw_archive]
                       [--max-passes 0] [--log /path/backfill.log]
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import subprocess
import sys
import time

from common.nba_paths import PG_DATA_DIR_LEGACY

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import fiba_api as fa
import fiba_db as db

ARCHIVE_DIR = os.path.join(HERE, "raw_archive")
PG_DATA_DIR = str(PG_DATA_DIR_LEGACY)
PG_PORT = 5433
PG_BIN = "/opt/homebrew/opt/postgresql@18/bin/pg_ctl"

# ---------------------------------------------------------------------------
# Safe int coercion (mirrors batch_scrape_fiba helpers)
# ---------------------------------------------------------------------------
def _si(v):
    if v is None:
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        try:
            return int(float(v))
        except (TypeError, ValueError):
            return None

def _org_id(v):
    return _si(v)

def _player_id(v):
    return _si(v)


# ---------------------------------------------------------------------------
# PG availability
# ---------------------------------------------------------------------------
def ensure_pg():
    try:
        c = db.get_conn()
        c.close()
        return True
    except Exception:
        pass
    # try to start the local cluster (same cluster the NBA project uses)
    try:
        subprocess.run(
            [PG_BIN, "-D", PG_DATA_DIR, "-o", f"-p {PG_PORT}",
             "-l", os.path.join(PG_DATA_DIR, "pg.log"), "start"],
            capture_output=True, text=True, timeout=30)
        time.sleep(3)
        c = db.get_conn()
        c.close()
        return True
    except Exception as e:
        print(f"[pg] start failed: {e}", flush=True)
        return False


# ---------------------------------------------------------------------------
# Core per-game capture
# ---------------------------------------------------------------------------
def build_pbp_rows(gid, pbp):
    rows = []
    for e in pbp:
        shot = e.get("act") == "shot"
        rows.append((
            gid, e.get("quarter"), _si(e.get("order")),
            e.get("Time"),
            _si(e.get("GT")), _si(e.get("SA")), _si(e.get("SB")),
            e.get("act"), e.get("ac"), e.get("txt"),
            (e.get("made") if shot else None),
            (_si(e.get("pts")) if shot else None),
            (_si(e.get("x")) if shot else None),
            (_si(e.get("y")) if shot else None),
            _org_id(e.get("oId")), _player_id(e.get("pId")),
            json.dumps(e, ensure_ascii=False),
        ))
    return rows


def cache_raw(gid, live, ts, cache_dir):
    d = os.path.join(cache_dir, str(gid))
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, f"liveinfo_{ts}.json")
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(live, f, ensure_ascii=False)
    except Exception as e:
        print(f"[cache] gid={gid} write failed: {e}", flush=True)
    return path


def capture_game(conn, gid, force=False, manifest=None, ts=None, cache_dir=ARCHIVE_DIR):
    """Return ('captured', n) / ('empty', 0) / ('error', msg). Does NOT delete on empty."""
    ts = ts or int(time.time())
    try:
        live = fa.get_game_live_detail(gid)
    except Exception as e:
        return ("error", f"fetch: {e}")
    if live is None:
        return ("error", "fetch returned None")
    # cache raw regardless (replayable, nothing lost)
    cache_raw(gid, live, ts, cache_dir)
    pbp = fa.parse_play_by_play(live)
    if not pbp:
        return ("empty", 0)
    if manifest and not force:
        prev = manifest.get(str(gid)) or manifest.get(gid)
        if prev and prev.get("events") == len(pbp) and prev.get("captured"):
            return ("skip", len(pbp))
    try:
        db.delete_game_events(conn, gid)
        rows = build_pbp_rows(gid, pbp)
        sql = (
            "INSERT INTO play_by_play (game_id, quarter, seq_order, event_time, "
            "gt_epoch, score_a, score_b, act, action_code, description, made, pts, "
            "x, y, org_id, player_id, raw) VALUES %s"
        )
        with conn.cursor() as cur:
            db.extras.execute_values(cur, sql, rows, page_size=200)
            cur.execute(
                "UPDATE games SET pbp_loaded=TRUE WHERE game_id=%s", (gid,))
        conn.commit()
        return ("captured", len(rows))
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        return ("error", f"db: {e}")


# ---------------------------------------------------------------------------
# Window detection
# ---------------------------------------------------------------------------
def detect_window(games, window_hours):
    now = datetime.datetime.now(datetime.timezone.utc)
    for g in games:
        dt = g.get("game_datetime_utc")
        st = (g.get("status") or "").upper()
        if st == "LIVE":
            return True
        if dt:
            try:
                if now - dt < datetime.timedelta(hours=window_hours):
                    return True
            except Exception:
                pass
    return False


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true", help="single pass then exit")
    ap.add_argument("--poll-idle", type=int, default=600, help="seconds between passes when no live window")
    ap.add_argument("--poll-window", type=int, default=60, help="seconds between passes during a live window")
    ap.add_argument("--window-hours", type=int, default=4, help="a game finished within this many hours => live window")
    ap.add_argument("--force", action="store_true", help="re-capture even if manifest count unchanged")
    ap.add_argument("--games", help="comma list of game ids to limit to")
    ap.add_argument("--manifest", default=os.path.join(HERE, "backfill_manifest_rest.json"))
    ap.add_argument("--cache-dir", default=ARCHIVE_DIR)
    ap.add_argument("--max-passes", type=int, default=0, help="0 = infinite")
    ap.add_argument("--log", default=os.path.join(HERE, "backfill_pbp_rest.log"))
    args = ap.parse_args()

    # logging to both file and stdout
    logf = open(args.log, "a", encoding="utf-8", buffering=1)
    def log(msg):
        line = f"[{datetime.datetime.now().isoformat()}] {msg}"
        print(line, flush=True)
        logf.write(line + "\n")

    if not ensure_pg():
        log("[fatal] cannot reach local PG; aborting")
        return

    conn = db.get_conn()
    with conn.cursor() as cur:
        cur.execute("SELECT game_id, game_datetime_utc, status FROM games ORDER BY game_datetime_utc")
        games = [{"game_id": r[0], "game_datetime_utc": r[1], "status": r[2]} for r in cur.fetchall()]
    log(f"loaded {len(games)} games from DB")

    if args.games:
        wanted = set(int(x) for x in args.games.split(",") if x.strip())
        games = [g for g in games if g["game_id"] in wanted]
        log(f"limited to {len(games)} games: {sorted(wanted)}")

    # manifest
    manifest = {}
    if os.path.exists(args.manifest):
        try:
            with open(args.manifest, encoding="utf-8") as f:
                manifest = json.load(f)
        except Exception:
            manifest = {}

    passes = 0
    while True:
        passes += 1
        ts = int(time.time())
        is_window = detect_window(games, args.window_hours)
        log(f"=== pass {passes} | window={'YES' if is_window else 'no'} | games={len(games)}")
        captured = skipped = empty = errors = 0
        for g in games:
            gid = g["game_id"]
            try:
                res, n = capture_game(conn, gid, force=args.force, manifest=manifest, ts=ts, cache_dir=args.cache_dir)
            except Exception as e:
                res, n = ("error", str(e))
            if res == "captured":
                captured += 1
                manifest[str(gid)] = {"events": n, "captured": True, "at": ts}
                log(f"  + captured gid={gid} events={n}")
            elif res == "skip":
                skipped += 1
            elif res == "empty":
                empty += 1
            else:
                errors += 1
                log(f"  ! gid={gid} {res}: {n}")
        # persist manifest
        try:
            with open(args.manifest, "w", encoding="utf-8") as f:
                json.dump(manifest, f, ensure_ascii=False)
        except Exception:
            pass
        total_pbp = sum(1 for v in manifest.values() if v.get("captured"))
        log(f"pass {passes} done: captured={captured} skipped={skipped} empty={empty} errors={errors} | manifest-captured={total_pbp}/{len(games)}")
        if args.once or (args.max_passes and passes >= args.max_passes):
            break
        # reconnect guard
        try:
            conn.close()
        except Exception:
            pass
        if not ensure_pg():
            log("[warn] PG down; will retry next pass")
        conn = db.get_conn()
        interval = args.poll_window if is_window else args.poll_idle
        log(f"sleeping {interval}s...")
        time.sleep(interval)


if __name__ == "__main__":
    main()
