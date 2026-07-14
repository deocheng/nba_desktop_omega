# Live 30-team HOF / Executives Crawl — Runbook

This runbook explains how to run the **live** crawl across all 30 NBA teams and
upsert the results into `team_hof` / `team_executives`. The code path is the
same one validated offline against the DET gold fixtures.

> ⚠️ **Run this on the user's Mac, not in the sandbox.**
> The sandbox is blocked by Cloudflare (`CF 403` / JS challenge) and has no
> Chrome profile. The offline DET load (`--offline-dir`) is the only part that
> runs in CI/sandbox.

## Prerequisites (on the Mac)

- Python 3.11+ with the project's `.venv` activated.
- `undetected_chromedriver` + a working Chrome install (the package drives a
  real UC Chrome instance, reusing the existing `.uc_br_profile` session cookie
  strategy from `scrape_br_hof_exec.py`).
- `.env` present with `DB_PASSWORD` (the loader in `hof_exec/config.py` reads
  it; nothing is hardcoded).
- Postgres reachable at `localhost:5433` (dbname `nba`, user `postgres`).

```bash
cd /path/to/nba_desktop_omega_mac_migrate
source .venv/bin/activate
```

## Build / verify the schema first (once)

```bash
.venv/bin/python - <<'PY'
from hof_exec.config import get_conn
sql = open("db/team_hof_exec.sql", encoding="utf-8").read()
with get_conn() as conn, conn.cursor() as cur:
    cur.execute(sql)
    conn.commit()
print("team_hof / team_executives ready")
PY
```

## Run the full 30-team crawl

```bash
.venv/bin/python -m hof_exec --all-teams --kind both
```

This iterates `hof_exec.config.TEAM_ABBRS` (the 30 canonical abbrs from
`common.bridge_constants._CANON`), resolves each to its BR slug via
`BR_TEAM_SLUGS` (BKN→BRK, CHA→CHO, rest identity), and for each team fetches
both `/hof` and `/executives`, parses, and upserts.

## Batching & rate-limiting (recommended)

BR/Cloudflare will throttle aggressive traffic. Run in waves rather than one
shot:

```bash
# East (e.g. 15 teams) then West (remaining 15) — split the abbr list as you like
.venv/bin/python -m hof_exec --team BOS --kind both
.venv/bin/python -m hof_exec --team NYK --kind both
# ... repeat per team, or wrap in a shell loop with `sleep 5` between teams
```

A simple paced loop:

```bash
for t in BOS BKN NYK PHI TOR CHI CLE DET IND MIL ATL CHA MIA ORL WAS \
         DEN MIN OKC POR UTA GSW LAC LAL PHX SAC DAL HOU MEM NOP SAS; do
  echo "=== $t ==="
  .venv/bin/python -m hof_exec --team "$t" --kind both
  sleep 5
done
```

## 404 / missing-team handling

- `fetch_team_page` detects a BR 404 payload (`looks_like_404`) and the CLI
  **skips** that team/kind with a `SKIP ... 404 page detected` log line — no
  crash, no partial row.
- For historical franchises BR may not host a modern `/hof` page; those teams
  are simply skipped and logged, so the run finishes cleanly.
- Re-running is safe: upserts refresh `scraped_at` and never duplicate rows
  (unique keys `(team_abbr, season, player_name)` and `(team_abbr, rk)`).

## Verify after the run

```sql
SELECT team_abbr, count(*) FROM team_hof GROUP BY team_abbr ORDER BY team_abbr;
SELECT team_abbr, count(*) FROM team_executives GROUP BY team_abbr ORDER BY team_abbr;
```

## Offline one-team load (sandbox-safe, already validated)

```bash
.venv/bin/python -m hof_exec --offline-dir det2026_br --team DET --kind both
```
