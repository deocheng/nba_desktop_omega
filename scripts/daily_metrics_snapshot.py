#!/usr/bin/env python3
"""
daily_metrics_snapshot.py -- Take one daily snapshot of every advanced metric
that publishes NO history, and append it to `public.player_metrics_daily`.

WHY THIS EXISTS
---------------
Three of our four advanced-metric sources are "now-only": they expose the
current numbers and nothing older.

    DPM    darko.app        -> homepage hydration payload, 530 players, no archive
    RAPM   nbarapm.com      -> /api/search-index has no season dimension
    LEBRON bball-index      -> fanspo API returns total_count=0 for any past season

We verified there is no backfill path for any of them (no hoopR/DARKO static
archive exists -- see memory 2026-08-29). So instead of history we accumulate
it: run this once a day and the table becomes a real time series.

EPM is deliberately absent: dunksandthrees ships 25 seasons of history already
in `player_epm`, so snapshotting it would only duplicate data.

DESIGN (standing automation preferences)
----------------------------------------
  * Cache everything  -- raw HTML / raw JSONL archived under
                         metrics_snapshot/raw_archive/<date>/ before parsing.
  * Errors non-blocking -- one metric failing never stops the others; partial
                         success still commits what worked.
  * Idempotent        -- PK (snapshot_date, metric, player_key) + ON CONFLICT
                         DO UPDATE, so running twice in a day is a no-op upsert.
  * Reversible        -- rollback manifest written to
                         scripts/rollback/metrics_snapshot_<date>.json

USAGE
-----
    .venv/bin/python scripts/daily_metrics_snapshot.py                 # all 3
    .venv/bin/python scripts/daily_metrics_snapshot.py --metrics dpm
    .venv/bin/python scripts/daily_metrics_snapshot.py --dry-run       # no writes
    .venv/bin/python scripts/daily_metrics_snapshot.py --no-fetch      # reuse cache
    .venv/bin/python scripts/daily_metrics_snapshot.py --limit 40      # smoke test
"""
import io
import os
import sys
import json
import argparse
import subprocess
from datetime import date
from pathlib import Path

# Outbound proxy breaks egress in this sandbox; strip it before any networking.
for _v in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY",
           "all_proxy", "ALL_PROXY"):
    os.environ.pop(_v, None)

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "dpm_scraper"))  # for fetch_darko import

ARCHIVE_ROOT = ROOT / "metrics_snapshot" / "raw_archive"
ROLLBACK_DIR = ROOT / "scripts" / "rollback"

# NBA's numeric team id -> abbreviation. Verified against the live DARKO
# payload (Jokic 1610612743=DEN, Wembanyama 1610612759=SAS, Kawhi
# 1610612746=LAC). No such mapping table exists in the DB (checked
# dim_teams / team_mapping), so it lives here.
NBA_TEAM_ID_TO_ABBR = {
    1610612737: "ATL", 1610612738: "BOS", 1610612739: "CLE",
    1610612740: "NOP", 1610612741: "CHI", 1610612742: "DAL",
    1610612743: "DEN", 1610612744: "GSW", 1610612745: "HOU",
    1610612746: "LAC", 1610612747: "LAL", 1610612748: "MIA",
    1610612749: "MIL", 1610612750: "MIN", 1610612751: "BKN",
    1610612752: "NYK", 1610612753: "ORL", 1610612754: "IND",
    1610612755: "PHI", 1610612756: "PHX", 1610612757: "POR",
    1610612758: "SAC", 1610612759: "SAS", 1610612760: "OKC",
    1610612761: "TOR", 1610612762: "UTA", 1610612763: "MEM",
    1610612764: "WAS", 1610612765: "DET", 1610612766: "CHA",
}

# Basketball-Reference uses historical codes that differ from the modern NBA
# abbreviations. Everything stored in player_metrics_daily is normalised to the
# modern 30-team set so that team_abbr means the same thing across sources
# (data-consistency requirement). Verified on 2026 data: BRK/CHO/PHO/UTH.
BR_TO_MODERN_ABBR = {
    "BRK": "BKN", "CHO": "CHA", "CHH": "CHA", "PHO": "PHX", "UTH": "UTA",
    "NOH": "NOP", "NOK": "NOP", "NOJ": "NOP",
    "WSB": "WAS", "VAN": "MEM", "SEA": "OKC",
    "KCO": "SAC", "KCK": "SAC", "SDR": "LAC", "SDC": "LAC",
    "FTW": "DET", "MNL": "LAL", "ROC": "SAC", "SYR": "PHI",
    "TRI": "ATL", "AND": "IND", "DNN": "ATL", "INO": "IND", "LAS": "LAC",
}

# Values that mean "no single team" rather than a real franchise. Player rows
# aggregated across multiple teams use these; they must never be stored as if
# they were a team, so they are normalised to NULL.
MULTI_TEAM_CODES = {"2TM", "3TM", "4TM", "5TM", "TOT", "FA", "N/A", "-", ""}

# Row-count sanity floor vs. the most recent prior snapshot of the same metric.
# Below this we still write, but shout loudly (protects against silently
# persisting a half-crawl as if it were a full day).
MIN_RETENTION_RATIO = 0.60


class SnapshotError(RuntimeError):
    pass


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def slugify(name):
    return "".join(c if c.isalnum() else "-" for c in (name or "").lower()).strip("-")


def player_key_of(nba_id, player_name):
    """Stable per-player key. nba_id is authoritative; name slug is fallback."""
    if nba_id not in (None, "", 0):
        return f"nba:{int(nba_id)}"
    return f"name:{slugify(player_name)}"


def fnum(x):
    try:
        if x is None:
            return None
        return float(x)
    except (TypeError, ValueError):
        return None


def norm_team(x):
    """Normalise a team code to the modern 30-team abbreviation, or NULL.

    Guards against the empty-string trap: nbarapm returns '' (not NULL) for
    players who are not on an active roster, and `count(team_abbr)` happily
    counts '' as present -- which made coverage look complete when 26 rows had
    no team at all. Empty / whitespace / multi-team aggregate codes all become
    NULL so that "has a team" actually means "has a real team".
    """
    if x is None:
        return None
    s = str(x).strip()
    if s.upper() in MULTI_TEAM_CODES:
        return None
    return BR_TO_MODERN_ABBR.get(s.upper(), s.upper())


def read_jsonl(path):
    rows = []
    with io.open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def dedupe_last(rows, keyfn):
    """Keep the LAST occurrence of each key (files are append-only, so later
    lines are the fresher read)."""
    out = {}
    for r in rows:
        out[keyfn(r)] = r
    return list(out.values())


# --------------------------------------------------------------------------
# collectors -- each returns a list of raw source dicts
# --------------------------------------------------------------------------
def collect_dpm(ctx):
    from fetch_darko import fetch_homepage, parse_players  # local import

    arc = ctx["archive_dir"]
    cached_html = arc / "darko_home.html"

    if ctx["no_fetch"]:
        src = None
        for cand in sorted((ROOT / "dpm_scraper" / "raw_archive").glob("darko_home_*.html"),
                           reverse=True):
            src = cand
            break
        if src is None:
            raise SnapshotError("no cached darko HTML found for --no-fetch")
        print(f"[dpm] no-fetch: parsing cached {src.name}")
        html = src.read_text(encoding="utf-8", errors="replace")
    else:
        print("[dpm] GET https://www.darko.app/")
        html = fetch_homepage()
        cached_html.write_text(html, encoding="utf-8")
        print(f"[dpm] cached raw HTML -> {cached_html}")

    players = parse_players(html)
    print(f"[dpm] parsed {len(players)} players")

    if not ctx["dry_run"]:
        out = arc / "darko_players.json"
        with io.open(out, "w", encoding="utf-8") as fh:
            json.dump(players, fh, ensure_ascii=False)
        # Keep load_dpm.py's contract file in sync (it reads this path).
        contract = ROOT / "dpm_scraper" / "darko_players.json"
        with io.open(contract, "w", encoding="utf-8") as fh:
            json.dump(players, fh, ensure_ascii=False)
    return players


def _run_subprocess(script, extra_args, label):
    cmd = [sys.executable, str(script)] + extra_args
    print(f"[{label}] $ {' '.join(str(c) for c in cmd)}")
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=str(ROOT))
    tail = (proc.stdout or "").strip().splitlines()[-6:]
    for line in tail:
        print(f"[{label}]   {line}")
    if proc.returncode != 0:
        err = (proc.stderr or "").strip().splitlines()[-5:]
        for line in err:
            print(f"[{label}]   ! {line}", file=sys.stderr)
        raise SnapshotError(f"{label} scraper exited {proc.returncode}")
    return proc


def collect_rapm(ctx):
    script = ROOT / "nbarapm_scraper" / "scrape_nbarapm.py"
    arc = ctx["archive_dir"]
    out = arc / "nbarapm_rapm.jsonl"

    if ctx["no_fetch"]:
        # Prefer this run's own archived harvest; fall back to the scraper's
        # default output file.
        src = out if out.exists() else ROOT / "nbarapm_scraper" / "nbarapm_rapm.jsonl"
        if not src.exists():
            raise SnapshotError("no cached rapm JSONL found for --no-fetch")
        print(f"[rapm] no-fetch: reusing {src}")
        raw = read_jsonl(src)
    else:
        args = ["--out", str(out)]
        if ctx["limit"]:
            args += ["--limit", str(ctx["limit"])]
        _run_subprocess(script, args, "rapm")
        raw = read_jsonl(out)

    # The scraper is append-mode, so dedupe on nba_id keeping the last row.
    rows = dedupe_last(raw, lambda r: r.get("nba_id"))
    print(f"[rapm] {len(raw)} raw lines -> {len(rows)} unique players")

    # Freshness check: the scraper stamps its own date.today().
    stamps = sorted({r.get("snapshot_date") for r in rows if r.get("snapshot_date")})
    if stamps and ctx["snap_date"] not in stamps:
        print(f"[rapm] warn: scraper stamped {stamps}, snapshot date is "
              f"{ctx['snap_date']} -- using orchestrator date as the key",
              file=sys.stderr)
    return rows


def collect_lebron(ctx):
    script = ROOT / "lebron_scraper" / "scrape_lebron.py"
    arc = ctx["archive_dir"]
    out = arc / "lebron.jsonl"

    if ctx["no_fetch"]:
        src = out if out.exists() else ROOT / "lebron_scraper" / "lebron.jsonl"
        if not src.exists():
            raise SnapshotError("no cached lebron JSONL found for --no-fetch")
        print(f"[lebron] no-fetch: reusing {src}")
        raw = read_jsonl(src)
    else:
        args = ["--out", str(out), "--season", ctx["lebron_season"]]
        _run_subprocess(script, args, "lebron")
        raw = read_jsonl(out)

    rows = dedupe_last(raw, lambda r: r.get("nba_id"))
    print(f"[lebron] {len(raw)} raw lines -> {len(rows)} unique players")
    return rows


# --------------------------------------------------------------------------
# mappers -- source dict -> snapshot row
# --------------------------------------------------------------------------
def map_dpm(p, snap_date):
    nba_id = p.get("nba_id")
    tm = p.get("tm_id")
    extra_keys = ("box_dpm", "on_off_dpm", "x_minutes", "x_pace", "x_pts_100",
                  "x_ast_100", "x_fg_pct", "x_fg3_pct", "x_ft_pct",
                  "sal_market_fixed", "actual_salary", "surplus_value",
                  "career_game_num", "position", "team_name", "tm_id", "_rank")
    return {
        "snapshot_date": snap_date,
        "metric": "dpm",
        "player_key": player_key_of(nba_id, p.get("player_name")),
        "source": "darko.app",
        "nba_id": int(nba_id) if nba_id else None,
        "player_name": p.get("player_name"),
        "team_abbr": norm_team(NBA_TEAM_ID_TO_ABBR.get(tm)),
        "season_label": str(p.get("season")) if p.get("season") else None,
        "val": fnum(p.get("dpm")),
        "val_o": fnum(p.get("o_dpm")),
        "val_d": fnum(p.get("d_dpm")),
        "extra": {k: p.get(k) for k in extra_keys if p.get(k) is not None},
    }


def map_rapm(r, snap_date):
    nba_id = r.get("nba_id")

    # nbarapm publishes no official O/D split, so we derive it from the
    # Six-Factor decomposition (ots/otov/osc = offence, dts/dtov/dsc = defence).
    #
    # IMPORTANT: the Six-Factor values come from a DIFFERENT model run than the
    # headline `rapm_total`. They agree exactly for some players
    # (Jokic: 6.82-0.28+1.28-0.22-0.28+1.85 = 9.17 == rapm_total) but disagree
    # by up to ~3.8 across the league (Wendell Moore Jr.: rapm_total -2.3 vs
    # six-factor sum -6.09). So we do NOT use the raw halves as val_o/val_d:
    #   * the RAW halves are preserved in extra (raw_o_factor / raw_d_factor)
    #   * val_o / val_d are scaled proportionally so that
    #         val_o + val_d == val
    #     holds, the same invariant the other two metrics satisfy.
    # Players with a near-zero six-factor sum cannot be scaled meaningfully
    # (ratio explodes), so their split is left NULL rather than fabricated.
    o_parts = [fnum(r.get(k)) for k in ("ots", "otov", "osc")]
    d_parts = [fnum(r.get(k)) for k in ("dts", "dtov", "dsc")]
    raw_o, raw_d = None, None
    if all(v is not None for v in o_parts) and all(v is not None for v in d_parts):
        raw_o = round(sum(o_parts), 4)
        raw_d = round(sum(d_parts), 4)

    val = fnum(r.get("rapm_total"))
    val_o, val_d = None, None
    six_sum = (raw_o + raw_d) if (raw_o is not None and raw_d is not None) else None
    if val is not None and six_sum is not None and abs(six_sum) >= 0.10:
        k = val / six_sum
        val_o = round(raw_o * k, 4)
        val_d = round(raw_d * k, 4)

    extra_keys = ("rapm_rank", "rapm_pop", "rapm_sum", "ots", "otov", "osc",
                  "dts", "dtov", "dsc", "on_off_net", "on_court_net",
                  "off_rtg", "def_rtg", "position", "has_bundle")
    extra = {k: r.get(k) for k in extra_keys if r.get(k) is not None}
    if raw_o is not None:
        extra["raw_o_factor"] = raw_o
        extra["raw_d_factor"] = raw_d
        extra["split_scaled"] = val_o is not None
    return {
        "snapshot_date": snap_date,
        "metric": "rapm",
        "player_key": player_key_of(nba_id, r.get("player_name")),
        "source": "nbarapm.com",
        "nba_id": int(nba_id) if nba_id else None,
        "player_name": r.get("player_name"),
        "team_abbr": norm_team(r.get("team_abbr")),
        "season_label": None,
        "val": val,
        "val_o": val_o,
        "val_d": val_d,
        "extra": extra,
    }


def map_lebron(r, snap_date):
    nba_id = r.get("nba_id")
    extra_keys = ("boxlebron", "lebron_war", "total_luck", "mins", "off_poss",
                  "def_poss", "cum_off_poss", "cum_def_poss",
                  "off_points_added", "def_points_saved", "through_date")
    return {
        "snapshot_date": snap_date,
        "metric": "lebron",
        "player_key": player_key_of(nba_id, r.get("player_name")),
        "source": "fanspo",
        "nba_id": int(nba_id) if nba_id else None,
        "player_name": r.get("player_name"),
        "team_abbr": None,
        "season_label": r.get("season"),
        "val": fnum(r.get("lebron")),
        "val_o": fnum(r.get("olebron")),
        "val_d": fnum(r.get("dlebron")),
        "extra": {k: r.get(k) for k in extra_keys if r.get(k) is not None},
    }


COLLECTORS = {
    "dpm":    (collect_dpm,   map_dpm),
    "rapm":   (collect_rapm,  map_rapm),
    "lebron": (collect_lebron, map_lebron),
}

UPSERT_SQL = """
INSERT INTO public.player_metrics_daily
    (snapshot_date, metric, player_key, source, nba_id, player_name,
     team_abbr, season_label, val, val_o, val_d, extra)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (snapshot_date, metric, player_key) DO UPDATE SET
    source       = EXCLUDED.source,
    nba_id       = EXCLUDED.nba_id,
    player_name  = EXCLUDED.player_name,
    -- Keep the existing team when the source ships none. LEBRON never provides
    -- a team, so a plain EXCLUDED.team_abbr would wipe out whatever the
    -- enrich pass filled in on a previous run of the same day, forcing a
    -- wasteful refill every time. The source stays authoritative when it does
    -- have a value (so a trade is picked up on the next snapshot).
    team_abbr    = COALESCE(EXCLUDED.team_abbr,
                            public.player_metrics_daily.team_abbr),
    season_label = EXCLUDED.season_label,
    val          = EXCLUDED.val,
    val_o        = EXCLUDED.val_o,
    val_d        = EXCLUDED.val_d,
    extra        = EXCLUDED.extra,
    fetched_at   = now()
"""


# --------------------------------------------------------------------------
# db
# --------------------------------------------------------------------------
def load_env():
    env = {}
    for line in (ROOT / ".env").read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def connect():
    import psycopg2
    env = load_env()
    conn = psycopg2.connect(host="127.0.0.1", port=5433, dbname="nba",
                            user="postgres", password=env["DB_PASSWORD"])
    conn.autocommit = False
    return conn


def upsert_rows(conn, rows):
    from psycopg2.extras import execute_batch, Json
    params = [
        (r["snapshot_date"], r["metric"], r["player_key"], r["source"],
         r["nba_id"], r["player_name"], r["team_abbr"], r["season_label"],
         r["val"], r["val_o"], r["val_d"], Json(r["extra"]))
        for r in rows
    ]
    with conn.cursor() as cur:
        cur.execute("SET max_parallel_workers_per_gather=0")
        execute_batch(cur, UPSERT_SQL, params, page_size=500)
    conn.commit()


def crossfill_team_abbr(conn, snap_date):
    """Backfill `team_abbr` from whichever source has it, via nba_id.

    LEBRON (fanspo) ships no team field at all -- 582/582 rows were NULL on the
    first run. DPM and RAPM both carry one. Since every source keys on the same
    nba_id, we can fill the gaps inside the same snapshot date.

    Reversible without a backup: the affected rows all start NULL, so rollback
    is simply setting them back to NULL (see the manifest).

    Preference order is alphabetical by metric ('dpm' < 'lebron' < 'rapm'),
    which makes DPM the donor of choice -- it resolved 530/530 abbreviations.
    """
    sql = """
        UPDATE public.player_metrics_daily t
        SET team_abbr = s.team_abbr
        FROM (
            SELECT DISTINCT ON (nba_id) nba_id, team_abbr
            FROM public.player_metrics_daily
            WHERE snapshot_date = %s
              AND team_abbr IS NOT NULL
              AND nba_id IS NOT NULL
            ORDER BY nba_id, metric
        ) s
        WHERE t.snapshot_date = %s
          AND t.nba_id = s.nba_id
          AND t.team_abbr IS NULL
    """
    with conn.cursor() as cur:
        cur.execute("SET max_parallel_workers_per_gather=0")
        cur.execute(sql, (snap_date, snap_date))
        filled = cur.rowcount
    conn.commit()
    return filled


def team_abbr_coverage(conn, snap_date):
    with conn.cursor() as cur:
        cur.execute("SET max_parallel_workers_per_gather=0")
        cur.execute("""
            SELECT metric, count(*) AS n, count(team_abbr) AS has_abbr
            FROM public.player_metrics_daily
            WHERE snapshot_date = %s
            GROUP BY metric ORDER BY metric
        """, (snap_date,))
        return cur.fetchall()


def prior_counts(conn, metric, before_date):
    with conn.cursor() as cur:
        cur.execute("SET max_parallel_workers_per_gather=0")
        cur.execute("""
            SELECT snapshot_date, count(*)
            FROM public.player_metrics_daily
            WHERE metric = %s AND snapshot_date < %s
            GROUP BY snapshot_date
            ORDER BY snapshot_date DESC LIMIT 1
        """, (metric, before_date))
        return cur.fetchone()


def write_manifest(ctx, results):
    ROLLBACK_DIR.mkdir(parents=True, exist_ok=True)
    path = ROLLBACK_DIR / f"metrics_snapshot_{ctx['snap_date']}.json"

    # MERGE with any manifest already written today. Running a single metric
    # (e.g. re-running just dpm after a fix) must not erase the rollback
    # record for the metrics from the earlier run -- an incomplete rollback
    # manifest is worse than none.
    metrics = {}
    if path.exists():
        try:
            metrics.update(json.loads(path.read_text(encoding="utf-8")).get("metrics", {}))
        except json.JSONDecodeError:
            pass
    metrics.update({m: {"rows": n, "status": st} for m, (n, st) in results.items()})

    manifest = {
        "action": "daily_metrics_snapshot",
        "snapshot_date": ctx["snap_date"],
        "table": "public.player_metrics_daily",
        "archive_dir": str(ctx["archive_dir"]),
        "metrics": metrics,
        "rollback_sql": [
            f"DELETE FROM public.player_metrics_daily "
            f"WHERE snapshot_date = '{ctx['snap_date']}' AND metric = '{m}';"
            for m in sorted(metrics)
        ],
        "notes": (
            "Idempotent UPSERT on PK (snapshot_date, metric, player_key). "
            "Rollback = delete that date+metric slice; no other rows are touched."
        ),
    }
    with io.open(path, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2, ensure_ascii=False)
    print(f"[manifest] -> {path}")
    return path


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--metrics", default="dpm,rapm,lebron",
                    help="comma-separated subset (default: all three)")
    ap.add_argument("--date", default=None,
                    help="snapshot date YYYY-MM-DD (default: today)")
    ap.add_argument("--dry-run", action="store_true",
                    help="fetch + parse + map, but write nothing")
    ap.add_argument("--no-fetch", action="store_true",
                    help="reuse cached scraper output instead of hitting the network")
    ap.add_argument("--limit", type=int, default=0,
                    help="cap players per scraper (smoke test; 0 = all)")
    ap.add_argument("--lebron-season", default="2025-26",
                    help="season label passed to scrape_lebron.py")
    ap.add_argument("--no-crossfill", dest="crossfill", action="store_false",
                    help="skip the team_abbr cross-source backfill")
    ap.add_argument("--no-enrich", dest="enrich", action="store_false",
                    help="skip the team_abbr normalise + library backfill pass")
    args = ap.parse_args()

    snap_date = args.date or date.today().isoformat()
    metrics = [m.strip() for m in args.metrics.split(",") if m.strip()]
    unknown = [m for m in metrics if m not in COLLECTORS]
    if unknown:
        ap.error(f"unknown metric(s) {unknown}; choose from {sorted(COLLECTORS)}")

    archive_dir = ARCHIVE_ROOT / snap_date
    archive_dir.mkdir(parents=True, exist_ok=True)
    ctx = {
        "snap_date": snap_date,
        "archive_dir": archive_dir,
        "dry_run": args.dry_run,
        "no_fetch": args.no_fetch,
        "limit": args.limit,
        "lebron_season": args.lebron_season,
    }

    print(f"[run] snapshot_date={snap_date} metrics={metrics} "
          f"dry_run={args.dry_run} no_fetch={args.no_fetch} limit={args.limit}")

    conn = None
    if not args.dry_run:
        conn = connect()

    results = {}
    failures = []
    for metric in metrics:
        collector, mapper = COLLECTORS[metric]
        print(f"\n=== {metric} ===")
        try:
            # CRITICAL: start every metric on a clean transaction. Postgres
            # marks a transaction ABORTED after any error, and every later
            # statement on that connection then fails with "current transaction
            # is aborted". Without this rollback one metric's failure silently
            # poisons all the ones after it -- which defeats the whole point of
            # non-blocking errors.
            if conn is not None:
                conn.rollback()

            raw_rows = collector(ctx)
            rows = [mapper(r, snap_date) for r in raw_rows]
            rows = [r for r in rows if r["player_key"] and r["val"] is not None]
            print(f"[{metric}] mapped {len(rows)} rows with a non-null value")

            # Sanity: compare against the previous snapshot of this metric.
            if conn is not None:
                prev = prior_counts(conn, metric, snap_date)
                if prev:
                    prev_date, prev_n = prev[0], prev[1]
                    ratio = len(rows) / prev_n if prev_n else 1.0
                    flag = "OK" if ratio >= MIN_RETENTION_RATIO else "SUSPECT"
                    print(f"[{metric}] vs previous snapshot {prev_date} "
                          f"({prev_n} rows): retention {ratio:.2f} [{flag}]")
                    if ratio < MIN_RETENTION_RATIO:
                        print(f"[{metric}] WARN: only {ratio:.0%} of the "
                              f"previous day's rows -- check the source before "
                              f"trusting this date", file=sys.stderr)

            if args.dry_run:
                top = sorted(rows, key=lambda r: r["val"], reverse=True)[:5]
                print(f"[{metric}] top 5 (dry-run, not written):")
                for r in top:
                    print(f"           {r['player_name']}: {r['val']}")
                results[metric] = (len(rows), "dry-run")
            else:
                upsert_rows(conn, rows)
                print(f"[{metric}] upserted {len(rows)} rows")
                results[metric] = (len(rows), "ok")
        except Exception as exc:  # noqa: BLE001 - non-blocking by design
            print(f"[{metric}] FAILED: {exc}", file=sys.stderr)
            # Clear the aborted transaction so the NEXT metric can still write.
            if conn is not None:
                try:
                    conn.rollback()
                except Exception as rb_exc:  # noqa: BLE001
                    print(f"[{metric}] rollback also failed: {rb_exc}", file=sys.stderr)
            results[metric] = (0, f"failed: {exc}")
            failures.append(metric)

    if not args.dry_run:
        # After all metrics land, fill in team_abbr from whichever source has
        # it (LEBRON ships none). Non-fatal: a failure here must not fail the run.
        if args.crossfill and not failures:
            try:
                conn.rollback()
                filled = crossfill_team_abbr(conn, snap_date)
                print(f"\n[crossfill] team_abbr backfilled on {filled} rows")
            except Exception as exc:  # noqa: BLE001
                print(f"[crossfill] FAILED (non-fatal): {exc}", file=sys.stderr)
                conn.rollback()

            # Second pass: normalise abbreviations, kill empty strings, and
            # fill whoever is still missing from the library's own roster
            # tables. Runs as a subprocess so the two scripts stay decoupled.
            if args.enrich:
                try:
                    proc = subprocess.run(
                        [sys.executable,
                         str(ROOT / "scripts" / "enrich_metrics_team_abbr.py"),
                         "--date", snap_date],
                        capture_output=True, text=True, cwd=str(ROOT))
                    tail = [l for l in (proc.stdout or "").splitlines()
                            if l.startswith(("[step", "    dpm", "    rapm",
                                             "    lebron", "    metric"))]
                    for line in tail:
                        print(f"[enrich] {line}")
                    if proc.returncode != 0:
                        print(f"[enrich] exited {proc.returncode} (non-fatal)",
                              file=sys.stderr)
                except Exception as exc:  # noqa: BLE001
                    print(f"[enrich] FAILED (non-fatal): {exc}", file=sys.stderr)

            try:
                conn.rollback()
                for m, n, has in team_abbr_coverage(conn, snap_date):
                    print(f"[team]     {m:8s} {has}/{n} have team_abbr")
            except Exception as exc:  # noqa: BLE001
                print(f"[team] coverage check failed: {exc}", file=sys.stderr)
                conn.rollback()
        write_manifest(ctx, results)
        conn.close()

    print("\n=== summary ===")
    for m, (n, st) in results.items():
        print(f"  {m:8s} rows={n:<5d} {st}")
    if failures:
        print(f"  FAILED metrics: {failures} (exit 1)")
        return 1
    print("  all metrics ok (exit 0)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
