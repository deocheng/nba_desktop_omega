# FIBA 每日增量爬虫 · 每日运行报告归档（2026-08-29 ~ 2026-09-28）

> 归档时间：2026-09-28 16:14
> 来源：`fiba_scraper/.workbuddy/memory/automations/e962d9f0-c4a0-4dc4-a9e8-747f5b46584d/memory.md`
> 说明：本文件为历史每日运行报告的**完整原样归档**，共 30 个条目。
> 活动记录（最近 5 天）仍保留在来源文件中，供自动化读取上次执行上下文。

---

# Automation: FIBA daily incremental scraper (e962d9f0-c4a0-4dc4-a9e8-747f5b46584d)

## 2026-08-29 10:10 GMT+8
- Ran `daily_scrape_fiba.py` (venv: nba_desktop_omega_mac_migrate_2026-07-13/.venv).
- Exit 0, no errors.
- Summary: PBP captured this run=6, boxscore refreshed=6. DB totals: games_with_pbp=12, play_by_play_rows=6857.
- Processed 6 recent games in competition 208943 (FIBA 2027 WC European Qualifiers), 2d window. Each grabbed 526-625 PBP events, 24-player boxscore.
- Behavior verified safe: only writes PBP when live feed returns events; no deletion of already-captured PBP.

## 2026-08-31 10:10 GMT+8
- Ran `daily_scrape_fiba.py` (venv: nba_desktop_omega_mac_migrate_2026-07-13/.venv).
- Exit 0, no errors.
- Summary: PBP captured this run=0, boxscore refreshed=0. DB totals: games_with_pbp=18, play_by_play_rows=10248.
- 2-day look-back window found 0 recent games in competition 208943 — quiet run, no data captured. DB totals up from prior run (12/6857) reflecting intervening captures.

## 2026-09-01 13:43 GMT+8
- First attempt FAILED: PG 5433 down; the script's own pg_ctl auto-start could not revive it.
- ROOT CAUSE (durable): PG18 on macOS fails at startup with `FATAL: postmaster became multithreaded during startup` / `HINT: Set the LC_ALL environment variable to a valid locale.` Ambient LANG=C.UTF-8 triggers it. The script calls pg_ctl with NO LC_ALL, so its auto-start always fails whenever the cluster is down.
- FIX: started the cluster manually with `LC_ALL=C /opt/homebrew/opt/postgresql@18/bin/pg_ctl -D /Volumes/12T/NBA/nba_pg -o "-p 5433" -l /Volumes/12T/NBA/nba_pg/pg.log start` → server up. Script NOT modified (per instruction).
- Re-ran script: exit 0. Summary: `PBP captured this run=0, boxscore refreshed=0. DB totals: games_with_pbp=12, play_by_play_rows=6857`.
- 0 hits is legitimate: no competition-208943 games inside the 2d window; next qualifying window is 2027-02-26..03-01 (66 INIT games). Verified, not a silent miss.
- REGRESSION FOUND: DB totals regressed 18/10248 (08-31) → 12/6857. Games 127119/127120/127084/127121/127085/127086 have pbp_loaded=False and 0 rows = 3391 PBP rows missing.
- FULLY RECOVERABLE: raw_archive/batch_<gid>/live_detail.json holds all 3391 events (567/676/498/512/581/557 — exact match to the 08-31 log). FIBA's live feed has rolled off, so the archive is the ONLY remaining source.
- Recovery path: parse archived JSON via fiba_api.parse_play_by_play + delete+INSERT.

## 2026-09-01 (2nd run, same day) — automation rebuilt
- User asked to automate as much as possible. All of the above is now fixed and automated.
- PG is now kept alive by launchd agent com.nba.pg5433 (RunAtLoad + KeepAlive, LC_ALL=C, log ~/Library/Logs/pg5433.log). Crash self-heal verified (kill -9 → back in 3s).
- Gotcha: launchd log path MUST be on the local disk; pointing it at /Volumes/12T gave exit 78 with no log at all.
- Recovered all 3391 missing rows via new recover_pbp_from_archive.py (dry-run by default, --apply to write, idempotent). DB restored to 18/10248, verified independently.
- Refactored batch_scrape_fiba.py: PBP write path extracted into insert_pbp_from_live(), now shared by load_game() and the recovery script (single source of truth).
- New run_daily_fiba.sh wrapper = ensure PG -> daily scrape -> auto-recover. Self-heal path tested with launchd disabled.
- This automation's command was changed from the bare python script to `bash /Volumes/12T/NBA/fiba_scraper/run_daily_fiba.sh`.

## 2026-09-02 10:05 GMT+8
- Ran `bash /Volumes/12T/NBA/fiba_scraper/run_daily_fiba.sh`.
- Exit 0, no errors. PG came up via launchd self-heal (no manual start needed).
- daily_scrape_fiba.py: competition 208943, 2d window → 0 recent games.
- Summary: `PBP captured this run=0, boxscore refreshed=0. DB totals: games_with_pbp=18, play_by_play_rows=10248`.
- recover_pbp_from_archive.py: 168 archived games scanned → 18 already in DB, 150 archived-but-no-PBP, 0 MISSING. Result: "nothing to recover".
- Quiet run — no qualifying games in the 2d window; DB totals stable at 18/10248 (matches 2026-09-01 post-recovery baseline). Next window 2027-02-26..03-01.

## 2026-09-03 10:05 GMT+8
- Ran `bash /Volumes/12T/NBA/fiba_scraper/run_daily_fiba.sh`.
- Exit 0, no errors. PG came up via launchd self-heal (no manual start needed).
- daily_scrape_fiba.py: competition 208943, 2d window → 0 recent games.
- Summary: `PBP captured this run=0, boxscore refreshed=0. DB totals: games_with_pbp=18, play_by_play_rows=10248`.
- recover_pbp_from_archive.py: 168 archived games scanned → 18 already in DB, 150 archived-but-no-PBP, 0 MISSING. Result: "nothing to recover".
- Quiet run — no qualifying games in the 2d window; DB totals stable at 18/10248 (matches post-recovery baseline). Next window 2027-02-26..03-01.

## 2026-09-04 10:08 GMT+8
- Ran `bash /Volumes/12T/NBA/fiba_scraper/run_daily_fiba.sh`.
- Exit 0, no errors. PG came up via launchd self-heal (no manual start needed).
- daily_scrape_fiba.py: competition 208943, 2d window → 0 recent games.
- Summary: `PBP captured this run=0, boxscore refreshed=0. DB totals: games_with_pbp=18, play_by_play_rows=10248`.
- recover_pbp_from_archive.py: 168 archived games scanned → 18 already in DB, 150 archived-but-no-PBP, 0 MISSING. Result: "nothing to recover".
- Quiet run — no qualifying games in the 2d window; DB totals stable at 18/10248 (matches post-recovery baseline). Next window 2027-02-26..03-01.

## 2026-09-05 10:09 GMT+8
- Ran `bash /Volumes/12T/NBA/fiba_scraper/run_daily_fiba.sh`.
- Exit 0, no errors. PG came up via launchd self-heal (no manual start needed).
- daily_scrape_fiba.py: competition 208943, 2d window → 0 recent games.
- Summary: `PBP captured this run=0, boxscore refreshed=0. DB totals: games_with_pbp=18, play_by_play_rows=10248`.
- recover_pbp_from_archive.py: 168 archived games scanned → 18 already in DB, 150 archived-but-no-PBP, 0 MISSING. Result: "nothing to recover".
- Quiet run — no qualifying games in the 2d window; DB totals stable at 18/10248 (matches post-recovery baseline). Next window 2027-02-26..03-01.

## 2026-09-06 15:41 GMT+8
- Ran `bash /Volumes/12T/NBA/fiba_scraper/run_daily_fiba.sh`.
- Exit 0, no errors. PG came up via launchd self-heal (no manual start needed).
- daily_scrape_fiba.py: competition 208943, 2d window → 0 recent games.
- Summary: `PBP captured this run=0, boxscore refreshed=0. DB totals: games_with_pbp=18, play_by_play_rows=10248`.
- recover_pbp_from_archive.py: 168 archived games scanned → 18 already in DB, 150 archived-but-no-PBP, 0 MISSING. Result: "nothing to recover".
- Quiet run — no qualifying games in the 2d window; DB totals stable at 18/10248 (matches post-recovery baseline). Next window 2027-02-26..03-01.

## 2026-09-07 10:00 GMT+8
- Ran `bash /Volumes/12T/NBA/fiba_scraper/run_daily_fiba.sh`.
- Exit 0, no errors. PG came up via launchd self-heal (no manual start needed).
- daily_scrape_fiba.py: competition 208943, 2d window → 0 recent games.
- Summary: `PBP captured this run=0, boxscore refreshed=0. DB totals: games_with_pbp=18, play_by_play_rows=10248`.
- recover_pbp_from_archive.py: 168 archived games scanned → 18 already in DB, 150 archived-but-no-PBP, 0 MISSING. Result: "nothing to recover".
- Quiet run — no qualifying games in the 2d window; DB totals stable at 18/10248 (matches post-recovery baseline). Next window 2027-02-26..03-01.

## 2026-09-08 10:03 GMT+8
- Ran `bash /Volumes/12T/NBA/fiba_scraper/run_daily_fiba.sh`.
- Exit 0, no errors. PG came up via launchd self-heal (no manual start needed).
- daily_scrape_fiba.py: competition 208943, 2d window → 0 recent games.
- Summary: `PBP captured this run=0, boxscore refreshed=0. DB totals: games_with_pbp=18, play_by_play_rows=10248`.
- recover_pbp_from_archive.py: 168 archived games scanned → 18 already in DB, 150 archived-but-no-PBP, 0 MISSING. Result: "nothing to recover".
- Quiet run — no qualifying games in the 2d window; DB totals stable at 18/10248 (matches post-recovery baseline). Next window 2027-02-26..03-01.

## 2026-09-09 10:09 GMT+8
- Ran `bash /Volumes/12T/NBA/fiba_scraper/run_daily_fiba.sh`.
- Exit 0, no errors. PG came up via launchd self-heal (no manual start needed).
- daily_scrape_fiba.py: competition 208943, 2d window → 0 recent games.
- Summary: `PBP captured this run=0, boxscore refreshed=0. DB totals: games_with_pbp=18, play_by_play_rows=10248`.
- recover_pbp_from_archive.py: 168 archived games scanned → 18 already in DB, 150 archived-but-no-PBP, 0 MISSING. Result: "nothing to recover".
- Quiet run — no qualifying games in the 2d window; DB totals stable at 18/10248 (matches post-recovery baseline). Next window 2027-02-26..03-01.

## 2026-09-10 10:03 GMT+8
- Ran `bash /Volumes/12T/NBA/fiba_scraper/run_daily_fiba.sh`.
- Exit 0, no errors. PG came up via launchd self-heal (no manual start needed).
- daily_scrape_fiba.py: competition 208943, 2d window → 0 recent games.
- Summary: `PBP captured this run=0, boxscore refreshed=0. DB totals: games_with_pbp=18, play_by_play_rows=10248`.
- recover_pbp_from_archive.py: 168 archived games scanned → 18 already in DB, 150 archived-but-no-PBP, 0 MISSING. Result: "nothing to recover".
- Quiet run — no qualifying games in the 2d window; DB totals stable at 18/10248 (matches post-recovery baseline). Next window 2027-02-26..03-01.

## 2026-09-11 10:10 GMT+8
- Ran `bash /Volumes/12T/NBA/fiba_scraper/run_daily_fiba.sh`.
- Exit 0, no errors. PG came up via launchd self-heal (no manual start needed).
- daily_scrape_fiba.py: competition 208943, 2d window → 0 recent games.
- Summary: `PBP captured this run=0, boxscore refreshed=0. DB totals: games_with_pbp=18, play_by_play_rows=10248`.
- recover_pbp_from_archive.py: 168 archived games scanned → 18 already in DB, 150 archived-but-no-PBP, 0 MISSING. Result: "nothing to recover".
- Quiet run — no qualifying games in the 2d window; DB totals stable at 18/10248 (matches post-recovery baseline). Next window 2027-02-26..03-01.

## 2026-09-12 10:06 GMT+8
- Ran `bash /Volumes/12T/NBA/fiba_scraper/run_daily_fiba.sh`.
- Exit 0, no errors. PG came up via launchd self-heal (no manual start needed).
- daily_scrape_fiba.py: competition 208943, 2d window → 0 recent games.
- Summary: `PBP captured this run=0, boxscore refreshed=0. DB totals: games_with_pbp=18, play_by_play_rows=10248`.
- recover_pbp_from_archive.py: 168 archived games scanned → 18 already in DB, 150 archived-but-no-PBP, 0 MISSING. Result: "nothing to recover".
- Quiet run — no qualifying games in the 2d window; DB totals stable at 18/10248 (matches post-recovery baseline). Next window 2027-02-26..03-01.

## 2026-09-13 10:03 GMT+8
- Ran `bash /Volumes/12T/NBA/fiba_scraper/run_daily_fiba.sh`.
- Exit 0, no errors. PG came up via launchd self-heal (no manual start needed).
- daily_scrape_fiba.py: competition 208943, 2d window → 0 recent games.
- Summary: `PBP captured this run=0, boxscore refreshed=0. DB totals: games_with_pbp=18, play_by_play_rows=10248`.
- recover_pbp_from_archive.py: 168 archived games scanned → 18 already in DB, 150 archived-but-no-PBP, 0 MISSING. Result: "nothing to recover".
- Quiet run — no qualifying games in the 2d window; DB totals stable at 18/10248 (matches post-recovery baseline). Next window 2027-02-26..03-01.

## 2026-09-14 10:05 GMT+8
- Ran `bash /Volumes/12T/NBA/fiba_scraper/run_daily_fiba.sh`.
- Exit 0, no errors. PG came up via launchd self-heal (no manual start needed).
- daily_scrape_fiba.py: competition 208943, 2d window → 0 recent games.
- Summary: `PBP captured this run=0, boxscore refreshed=0. DB totals: games_with_pbp=18, play_by_play_rows=10248`.
- recover_pbp_from_archive.py: 168 archived games scanned → 18 already in DB, 150 archived-but-no-PBP, 0 MISSING. Result: "nothing to recover".
- Quiet run — no qualifying games in the 2d window; DB totals stable at 18/10248 (matches post-recovery baseline). Next window 2027-02-26..03-01.

## 2026-09-15 13:04 GMT+8
- Ran `bash /Volumes/12T/NBA/fiba_scraper/run_daily_fiba.sh`.
- Exit 0, no errors. PG came up via launchd self-heal (no manual start needed).
- daily_scrape_fiba.py: competition 208943, 2d window → 0 recent games.
- Summary: `PBP captured this run=0, boxscore refreshed=0. DB totals: games_with_pbp=18, play_by_play_rows=10248`.
- recover_pbp_from_archive.py: 168 archived games scanned → 18 already in DB, 150 archived-but-no-PBP, 0 MISSING. Result: "nothing to recover".
- Quiet run — no qualifying games in the 2d window; DB totals stable at 18/10248 (matches post-recovery baseline). Next window 2027-02-26..03-01.

## 2026-09-17 18:43 GMT+8
- Ran `bash /Volumes/12T/NBA/fiba_scraper/run_daily_fiba.sh`.
- Exit 0, no errors. PG came up via launchd self-heal (no manual start needed).
- daily_scrape_fiba.py: competition 208943, 2d window → 0 recent games.
- Summary: `PBP captured this run=0, boxscore refreshed=0. DB totals: games_with_pbp=18, play_by_play_rows=10248`.
- recover_pbp_from_archive.py: 168 archived games scanned → 18 already in DB, 150 archived-but-no-PBP, 0 MISSING. Result: "nothing to recover".
- Quiet run — no qualifying games in the 2d window; DB totals stable at 18/10248 (matches post-recovery baseline). Next window 2027-02-26..03-01.

## 2026-09-18 10:06 GMT+8
- Ran `bash /Volumes/12T/NBA/fiba_scraper/run_daily_fiba.sh`.
- Exit 0, no errors. PG was already up (run completed in ~1s, no manual start needed).
- daily_scrape_fiba.py: competition 208943, 2d window → 0 recent games.
- Summary: `PBP captured this run=0, boxscore refreshed=0. DB totals: games_with_pbp=18, play_by_play_rows=10248`.
- recover_pbp_from_archive.py: 168 archived games scanned → 18 already in DB, 150 archived-but-no-PBP, 0 MISSING. Result: "nothing to recover".
- Quiet run — no qualifying games in the 2d window; DB totals stable at 18/10248 (matches post-recovery baseline). Next window 2027-02-26..03-01.

## 2026-09-19 10:06 GMT+8
- Ran `bash /Volumes/12T/NBA/fiba_scraper/run_daily_fiba.sh`.
- Exit 0, no errors. PG came up via launchd self-heal (no manual start needed, run ~2s).
- daily_scrape_fiba.py: competition 208943, 2d window → 0 recent games.
- Summary: `PBP captured this run=0, boxscore refreshed=0. DB totals: games_with_pbp=18, play_by_play_rows=10248`.
- recover_pbp_from_archive.py: 168 archived games scanned → 18 already in DB, 150 archived-but-no-PBP, 0 MISSING. Result: "nothing to recover".
- Quiet run — no qualifying games in the 2d window; DB totals stable at 18/10248 (matches post-recovery baseline). Next window 2027-02-26..03-01.

## 2026-09-20 10:10 GMT+8
- Ran `bash /Volumes/12T/NBA/fiba_scraper/run_daily_fiba.sh`.
- Exit 0, no errors. PG up, run ~1s, no manual start needed.
- daily_scrape_fiba.py: competition 208943, 2d window → 0 recent games.
- Summary: `PBP captured this run=0, boxscore refreshed=0. DB totals: games_with_pbp=18, play_by_play_rows=10248`.
- recover_pbp_from_archive.py: 168 archived games scanned → 18 already in DB, 150 archived-but-no-PBP, 0 MISSING. Result: "nothing to recover".
- Quiet run — no qualifying games in the 2d window; DB totals stable at 18/10248 (matches post-recovery baseline). Next window 2027-02-26..03-01.

## 2026-09-21 10:03 GMT+8
- Ran `bash /Volumes/12T/NBA/fiba_scraper/run_daily_fiba.sh`.
- Exit 0, no errors. PG up, run ~1s, no manual start needed.
- daily_scrape_fiba.py: competition 208943, 2d window → 0 recent games.
- Summary: `PBP captured this run=0, boxscore refreshed=0. DB totals: games_with_pbp=18, play_by_play_rows=10248`.
- recover_pbp_from_archive.py: 168 archived games scanned → 18 already in DB, 150 archived-but-no-PBP, 0 MISSING. Result: "nothing to recover".
- Quiet run — no qualifying games in the 2d window; DB totals stable at 18/10248 (matches post-recovery baseline). Next window 2027-02-26..03-01.

## 2026-09-22 10:06 GMT+8
- Ran `bash /Volumes/12T/NBA/fiba_scraper/run_daily_fiba.sh`.
- Exit 0, no errors. PG up, run ~2s, no manual start needed.
- daily_scrape_fiba.py: competition 208943, 2d window → 0 recent games.
- Summary: `PBP captured this run=0, boxscore refreshed=0. DB totals: games_with_pbp=18, play_by_play_rows=10248`.
- recover_pbp_from_archive.py: 168 archived games scanned → 18 already in DB, 150 archived-but-no-PBP, 0 MISSING. Result: "nothing to recover".
- Quiet run — no qualifying games in the 2d window; DB totals stable at 18/10248 (matches post-recovery baseline). Next window 2027-02-26..03-01.

## 2026-09-23 10:05 GMT+8
- Ran `bash /Volumes/12T/NBA/fiba_scraper/run_daily_fiba.sh`.
- Exit 0, no errors. PG up, run ~4s, no manual start needed.
- daily_scrape_fiba.py: competition 208943, 2d window → 0 recent games.
- Summary: `PBP captured this run=0, boxscore refreshed=0. DB totals: games_with_pbp=18, play_by_play_rows=10248`.
- recover_pbp_from_archive.py: 168 archived games scanned → 18 already in DB, 150 archived-but-no-PBP, 0 MISSING. Result: "nothing to recover".
- Quiet run — no qualifying games in the 2d window; DB totals stable at 18/10248 (matches post-recovery baseline). Next window 2027-02-26..03-01.

## 2026-09-24 10:02 GMT+8
- Ran `bash /Volumes/12T/NBA/fiba_scraper/run_daily_fiba.sh`.
- Exit 0, no errors. PG up, run ~1s, no manual start needed.
- daily_scrape_fiba.py: competition 208943, 2d window → 0 recent games.
- Summary: `PBP captured this run=0, boxscore refreshed=0. DB totals: games_with_pbp=18, play_by_play_rows=10248`.
- recover_pbp_from_archive.py: 168 archived games scanned → 18 already in DB, 150 archived-but-no-PBP, 0 MISSING. Result: "nothing to recover".
- Quiet run — no qualifying games in the 2d window; DB totals stable at 18/10248 (matches post-recovery baseline). Next window 2027-02-26..03-01.

## 2026-09-25 10:12 GMT+8
- Ran `bash /Volumes/12T/NBA/fiba_scraper/run_daily_fiba.sh`.
- Exit 0, no errors. PG up, run ~1s, no manual start needed.
- daily_scrape_fiba.py: competition 208943, 2d window → 0 recent games.
- Summary: `PBP captured this run=0, boxscore refreshed=0. DB totals: games_with_pbp=18, play_by_play_rows=10248`.
- recover_pbp_from_archive.py: 168 archived games scanned → 18 already in DB, 150 archived-but-no-PBP, 0 MISSING. Result: "nothing to recover".
- Quiet run — no qualifying games in the 2d window; DB totals stable at 18/10248 (matches post-recovery baseline). Next window 2027-02-26..03-01.

## 2026-09-26 10:07 GMT+8
- Ran `bash /Volumes/12T/NBA/fiba_scraper/run_daily_fiba.sh`.
- Exit 0, no errors. PG up, run ~2s, no manual start needed.
- daily_scrape_fiba.py: competition 208943, 2d window → 0 recent games.
- Summary: `PBP captured this run=0, boxscore refreshed=0. DB totals: games_with_pbp=18, play_by_play_rows=10248`.
- recover_pbp_from_archive.py: 168 archived games scanned → 18 already in DB, 150 archived-but-no-PBP, 0 MISSING. Result: "nothing to recover".
- Quiet run — no qualifying games in the 2d window; DB totals stable at 18/10248 (matches post-recovery baseline). Next window 2027-02-26..03-01.

## 2026-09-27 10:05 GMT+8
- Ran `bash /Volumes/12T/NBA/fiba_scraper/run_daily_fiba.sh`.
- Exit 0, no errors. PG up (run ~1s), no manual start needed.
- daily_scrape_fiba.py: competition 208943, 2d window → 0 recent games.
- Summary: `PBP captured this run=0, boxscore refreshed=0. DB totals: games_with_pbp=18, play_by_play_rows=10248`.
- recover_pbp_from_archive.py: 168 archived games scanned → 18 already in DB, 150 archived-but-no-PBP, 0 MISSING. Result: "nothing to recover".
- Quiet run — no qualifying games in the 2d window; DB totals stable at 18/10248 (matches post-recovery baseline). Next window 2027-02-26..03-01.

## 2026-09-28 10:06 GMT+8
- Ran `bash /Volumes/12T/NBA/fiba_scraper/run_daily_fiba.sh`.
- Exit 0, no errors. PG up (run ~4s), no manual start needed.
- daily_scrape_fiba.py: competition 208943, 2d window → 0 recent games.
- Summary: `PBP captured this run=0, boxscore refreshed=0. DB totals: games_with_pbp=18, play_by_play_rows=10248`.
- recover_pbp_from_archive.py: 168 archived games scanned → 18 already in DB, 150 archived-but-no-PBP, 0 MISSING. Result: "nothing to recover".
- Quiet run — no qualifying games in the 2d window; DB totals stable at 18/10248 (matches post-recovery baseline). Next window 2027-02-26..03-01.
