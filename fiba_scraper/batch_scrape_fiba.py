"""FIBA batch scraper — materializes a whole competition into the `fiba` DB.

Coverage for one competition (default: FIBA Basketball World Cup 2027
European Qualifiers, competition_id=208943, 168 games):

  * competitions / rounds            — reference data (from the games list)
  * teams / players                  — dimension tables (merged from boxscore)
  * games                           — one row per game (from the games list)
  * game_team_stats                 — per-team boxscore (derived from player lines)
  * game_player_stats               — per-player boxscore (from getgdapgamestatisticsbygameid)
  * play_by_play                    — PBP events (live-info route; only games that expose it)
  * competition_player_game_highs / competition_team_game_highs — 6 stat leaderboards

Data-source notes (verified 2026-08-28):
  * The Next.js live-info proxy (game-live-info/{id}/detail) serves a full boxscore+PBP
    object for only ~6 of 168 games; the rest return {"game":{"content":null}}. So boxscore
    is sourced from the universal catalog call getgdapgamestatisticsbygameid (works for ALL
    games, clean field names). Team totals are derived by summing player lines per org.
  * PBP exists only in the live-info object; we load it where present and skip otherwise.

All writes are idempotent (ON CONFLICT / DELETE+INSERT). Re-running resumes from the DB
(games already fully loaded are skipped via the boxscore_loaded marker).

Anti-scraping posture: FIBA's APIM has no Cloudflare wall, no bot-challenge, only a public
subscription-key gate (401 if missing), and no observed rate limit. We still apply polite
pacing + a 429/error backoff as defense-in-depth.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import defaultdict
from typing import Any, Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fiba_api as fa
import fiba_db as db

# Statistic codes for the competition leaderboards.
STAT_CODES = ("PTS", "EFF", "REB", "AST", "STL", "BLK")

# Polite pacing + backoff (defense-in-depth; no limit was observed).
REQUEST_DELAY = 0.10          # seconds between API calls
MAX_RETRIES = 5
BACKOFF_BASE = 1.5            # seconds, doubled per attempt

ARCHIVE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "raw_archive")

# getgdap boxscore field -> (our column, int-coerced?)
_PLAYER_FIELDS = [
    ("points", "pts"), ("fieldGoalsMade", "fg_made"), ("fieldGoalsAttempted", "fg_att"),
    ("threePointsMade", "fg3_made"), ("threePointsAttempted", "fg3_att"),
    ("freeThrowsMade", "ft_made"), ("freeThrowsAttempted", "ft_att"),
    ("offensiveRebounds", "oreb"), ("defensiveRebounds", "dreb"), ("rebounds", "reb"),
    ("assists", "ast"), ("steals", "stl"), ("blockedShots", "blk"),
    ("turnovers", "tov"), ("personalFouls", "pf"),
    ("plusMinus", "plus_minus"), ("efficiency", "eff"),
]
# team aggregate accumulates the same numeric keys (minus plus_minus/efficiency which are
# per-player only; team totals sum the counting stats).
_TEAM_SUM_FIELDS = [(src, col) for src, col in _PLAYER_FIELDS
                    if col not in ("plus_minus", "eff")]


# ---------------------------------------------------------------------------
# API helpers (retry / backoff)
# ---------------------------------------------------------------------------
def _api(fn, *args, **kwargs):
    """Call a fiba_api function with exponential backoff on failure."""
    last = None
    for attempt in range(MAX_RETRIES):
        try:
            return fn(*args, **kwargs)
        except fa.FIBAError as e:
            last = e
            wait = BACKOFF_BASE * (2 ** attempt)
            print(f"    [retry {attempt+1}/{MAX_RETRIES}] {fn.__name__} failed: {e}; "
                  f"sleeping {wait:.1f}s")
            time.sleep(wait)
    raise last or RuntimeError("api failed")


def _delay() -> None:
    if REQUEST_DELAY:
        time.sleep(REQUEST_DELAY)


# ---------------------------------------------------------------------------
# Field coercion
# ---------------------------------------------------------------------------
def _org_id(raw_id: Any) -> Optional[int]:
    if raw_id is None:
        return None
    s = str(raw_id).strip()
    if "_" in s:
        s = s.split("_")[-1]
    try:
        return int(s)
    except ValueError:
        return None


def _player_id(raw_id: Any) -> Optional[int]:
    if raw_id is None:
        return None
    s = str(raw_id).strip()
    if "_" in s:
        s = s.split("_")[-1]
    try:
        return int(s)
    except ValueError:
        return None


def _si(d: Dict[str, Any], key: str) -> Optional[int]:
    v = d.get(key)
    if v is None:
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _num(v: Any) -> Optional[float]:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _utc(s: Optional[str]) -> Optional[str]:
    if not s:
        return None
    s = s.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    elif "+" not in s and "T" in s:
        s = s + "+00:00"
    return s


# ---------------------------------------------------------------------------
# Upserts
# ---------------------------------------------------------------------------
def upsert_teams(conn, rows: List[tuple]) -> None:
    """rows: (org_id, code, official_name, short_name, country, country_code, logo_url).
    COALESCE keeps earlier non-null values when a later source lacks a field."""
    if not rows:
        return
    sql = (
        "INSERT INTO teams (org_id, code, official_name, short_name, country, "
        "country_code, logo_url) VALUES %s "
        "ON CONFLICT (org_id) DO UPDATE SET "
        "code=COALESCE(EXCLUDED.code, teams.code), "
        "official_name=COALESCE(EXCLUDED.official_name, teams.official_name), "
        "short_name=COALESCE(EXCLUDED.short_name, teams.short_name), "
        "country=COALESCE(EXCLUDED.country, teams.country), "
        "country_code=COALESCE(EXCLUDED.country_code, teams.country_code), "
        "logo_url=COALESCE(EXCLUDED.logo_url, teams.logo_url)"
    )
    with conn.cursor() as cur:
        db.extras.execute_values(cur, sql, rows, page_size=100)
    conn.commit()


def upsert_competition(conn, comp: Dict[str, Any]) -> None:
    cid = comp.get("competitionId")
    if cid is None:
        return
    cols = ["competition_id", "competition_code", "season", "official_name",
            "start_date", "end_date", "gender", "zone"]
    row = (
        cid, comp.get("competitionCode"), comp.get("season"), comp.get("officialName"),
        _utc(comp.get("start")), _utc(comp.get("end")), comp.get("gender"),
        comp.get("fibaZone"),
    )
    db.upsert_many(conn, "competitions", cols, ["competition_id"], [row])


def upsert_rounds(conn, competition_id: int, rounds: List[Dict[str, Any]]) -> None:
    cols = ["round_id", "competition_id", "name", "type"]
    rows = [
        (r.get("roundId"), competition_id, r.get("roundName"), r.get("roundType"))
        for r in rounds if r.get("roundId") is not None
    ]
    if rows:
        db.upsert_many(conn, "rounds", cols, ["round_id"], rows)


def upsert_teams_from_games(conn, games: List[Dict[str, Any]]) -> None:
    rows: List[tuple] = []
    seen = set()
    for g in games:
        for side in ("teamA", "teamB"):
            t = g.get(side) or {}
            org = t.get("organisationId")
            if org is None or org in seen:
                continue
            seen.add(org)
            code = t.get("code")
            name = t.get("officialName") or t.get("shortName")
            rows.append((org, code, name, t.get("shortName"), name, code, None))
    upsert_teams(conn, rows)


def upsert_rounds_from_games(conn, competition_id: int,
                             games: List[Dict[str, Any]]) -> None:
    seen = set()
    rows = []
    for g in games:
        r = g.get("round") or {}
        rid = r.get("roundId")
        if rid is None or rid in seen:
            continue
        seen.add(rid)
        rows.append((rid, competition_id, r.get("roundName"), r.get("roundType")))
    if rows:
        db.upsert_many(conn, "rounds", ["round_id", "competition_id", "name", "type"],
                       ["round_id"], rows)


def upsert_games(conn, games: List[Dict[str, Any]], competition_id: int) -> None:
    cols = ["game_id", "competition_id", "round_id", "technical_name",
            "team_a_org", "team_b_org", "team_a_score", "team_b_score", "status",
            "game_datetime_utc", "venue_name", "host_city", "host_country",
            "spectators", "raw"]
    rows = []
    for g in games:
        ta = (g.get("teamA") or {}).get("organisationId")
        tb = (g.get("teamB") or {}).get("organisationId")
        rd = (g.get("round") or {}).get("roundId")
        rows.append((
            g.get("gameId"), competition_id, rd, g.get("gameName"),
            ta, tb, _si(g, "teamAScore"), _si(g, "teamBScore"), g.get("statusCode"),
            _utc(g.get("gameDateTimeUTC")), g.get("venueName"),
            g.get("hostCity"), g.get("hostCountry"), _si(g, "spectators"),
            json.dumps(g, ensure_ascii=False),
        ))
    if rows:
        db.upsert_many(conn, "games", cols, ["game_id"], rows)


def upsert_players(conn, rows: List[tuple]) -> None:
    if not rows:
        return
    db.upsert_many(conn, "players",
                   ["player_id", "first_name", "last_name", "full_name",
                    "nationality", "position_code", "date_of_birth", "uniform_number",
                    "headshot_url"],
                   ["player_id"], rows)


# ---------------------------------------------------------------------------
# Per-game load (boxscore via getgdap + PBP via live-info where available)
# ---------------------------------------------------------------------------
def insert_pbp_from_live(conn, gid: int, live: Dict[str, Any]) -> int:
    """Parse a live-detail payload and (re)write that game's PBP rows.

    Single source of truth for the PBP write path, shared by:
      * load_game()                -- payload freshly fetched from FIBA
      * recover_pbp_from_archive.py -- payload replayed from raw_archive/

    `live` is the raw live-detail dict; it may come from the network or from the
    archived JSON. The parse + insert logic is identical either way.

    SAFE: only delete+insert when the payload actually contains events. If it
    doesn't (feed rolled off / archived null-content game), any previously
    captured PBP is left untouched -- never silently wiped.

    Returns the number of PBP rows written (0 if the payload had no events).
    """
    pbp = fa.parse_play_by_play(live)  # [] when no periodActions (null-content games)
    if not pbp:
        return 0
    db.delete_game_events(conn, gid)
    pbp_rows = []
    for e in pbp:
        shot = e.get("act") == "shot"
        pbp_rows.append((
            gid, e.get("quarter"), _si(e, "order"), e.get("Time"),
            _si(e, "GT"), _si(e, "SA"), _si(e, "SB"), e.get("act"), e.get("ac"),
            e.get("txt"),
            e.get("made") if shot else None,
            _si(e, "pts") if shot else None,
            _si(e, "x") if shot else None,
            _si(e, "y") if shot else None,
            _org_id(e.get("oId")), _player_id(e.get("pId")),
            json.dumps(e, ensure_ascii=False),
        ))
    # play_by_play has no composite unique key (only event_id PK); we
    # delete-then-insert per game, so a plain INSERT is correct & idempotent.
    sql = (
        "INSERT INTO play_by_play (game_id, quarter, seq_order, event_time, "
        "gt_epoch, score_a, score_b, act, action_code, description, made, pts, "
        "x, y, org_id, player_id, raw) VALUES %s"
    )
    with conn.cursor() as cur:
        db.extras.execute_values(cur, sql, pbp_rows, page_size=200)
        cur.execute(
            "UPDATE games SET pbp_loaded=TRUE WHERE game_id=%s", (gid,))
    conn.commit()
    return len(pbp_rows)


def load_game(conn, game: Dict[str, Any], archive: bool = True,
              competition_id: int = None) -> Dict[str, int]:
    """Boxscore from getgdapgamestatisticsbygameid (all games); PBP from live-info (subset)."""
    gid = game.get("gameId")
    tA = (game.get("teamA") or {}).get("organisationId")
    tB = (game.get("teamB") or {}).get("organisationId")
    sA = game.get("teamAScore")
    sB = game.get("teamBScore")
    counts = {"players": 0, "player_stats": 0, "team_stats": 0, "pbp": 0}

    # --- Boxscore (universal getgdap source) ---
    bs = _api(fa.get_game_boxscore, gid)
    _delay()
    if archive:
        d = os.path.join(ARCHIVE_DIR, f"batch_{gid}")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "boxscore.json"), "w", encoding="utf-8") as f:
            json.dump(bs, f, ensure_ascii=False)

    player_rows: List[tuple] = []
    player_stat_rows: List[tuple] = []
    team_acc: Dict[int, Dict[str, int]] = defaultdict(lambda: defaultdict(int))

    if isinstance(bs, list):
        for line in bs:
            pl = line.get("player") or {}
            tm = line.get("team") or {}
            org = _org_id(tm.get("organisationId"))
            pid = _player_id(pl.get("playerId")) or _player_id(pl.get("id"))
            # Accumulate team totals for EVERY player who appeared (incl. rows
            # with a null playerId), so team sums stay complete.
            if org is not None:
                acc = team_acc[org]
                for src, col in _TEAM_SUM_FIELDS:
                    v = _si(line, src)
                    if v:
                        acc[col] += v
            if pid is None:
                continue
            fn = pl.get("firstName")
            ln = pl.get("lastName")
            full = (fn and ln and f"{fn} {ln}") or pl.get("name")
            # GAP-3 bio enrichment: position / birthdate / jersey are carried in
            # the boxscore player object. Headshot URL is deterministic per
            # player_id from FIBA's public Cloudinary CDN (no APIM key needed).
            position_code = pl.get("positionCode")
            dob = pl.get("dateOfBirth")  # ISO string -> TIMESTAMPTZ on insert
            try:
                uniform_number = int(pl["uniformNumber"]) if pl.get("uniformNumber") is not None else None
            except (TypeError, ValueError):
                uniform_number = None
            headshot_url = (f"https://res.cloudinary.com/ddsbdyeyj/image/upload/"
                            f".headshot--person_{pid}"
                            + (f"--competition_{competition_id}"
                               if competition_id else ""))
            player_rows.append(
                (pid, fn, ln, full, pl.get("nationality"),
                 position_code, dob, uniform_number, headshot_url))
            try:
                jersey = int(pl["uniformNumber"]) if pl.get("uniformNumber") is not None else None
            except (TypeError, ValueError):
                jersey = None
            pstat = [gid, pid, org, jersey, bool(line.get("isStarter"))]
            for src, col in _PLAYER_FIELDS:
                pstat.append(_si(line, src))
            pstat.append(json.dumps(line, ensure_ascii=False))
            player_stat_rows.append(tuple(pstat))

    # --- Team stats (derived aggregates) ---
    team_stat_rows: List[tuple] = []
    for org, acc in team_acc.items():
        if org == tA and isinstance(sA, int) and isinstance(sB, int):
            is_winner = sA > sB
            score = sA
        elif org == tB and isinstance(sA, int) and isinstance(sB, int):
            is_winner = sB > sA
            score = sB
        else:
            is_winner = None
            score = acc.get("pts")
        tstat = [gid, org, is_winner, score]
        for src, col in _TEAM_SUM_FIELDS:
            tstat.append(acc.get(col))
        tstat.append(json.dumps(dict(acc), ensure_ascii=False))
        team_stat_rows.append(tuple(tstat))

    upsert_players(conn, player_rows)
    counts["players"] = len(player_rows)
    if player_stat_rows:
        db.upsert_many(conn, "game_player_stats",
                       ["game_id", "player_id", "org_id", "jersey", "is_starter",
                        "pts", "fg_made", "fg_att", "fg3_made", "fg3_att", "ft_made",
                        "ft_att", "oreb", "dreb", "reb", "ast", "stl", "blk", "tov",
                        "pf", "plus_minus", "eff", "raw_stats"],
                       ["game_id", "player_id"], player_stat_rows)
    counts["player_stats"] = len(player_stat_rows)
    if team_stat_rows:
        db.upsert_many(conn, "game_team_stats",
                       ["game_id", "org_id", "is_winner", "score", "pts", "fg_made",
                        "fg_att", "fg3_made", "fg3_att", "ft_made", "ft_att", "oreb",
                        "dreb", "reb", "ast", "stl", "blk", "tov", "pf", "raw_stats"],
                       ["game_id", "org_id"], team_stat_rows)
    counts["team_stats"] = len(team_stat_rows)

    # --- PBP (live-info route; only games inside FIBA's retention window) ---
    live = _api(fa.get_game_live_detail, gid)
    _delay()
    if archive:
        d = os.path.join(ARCHIVE_DIR, f"batch_{gid}")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "live_detail.json"), "w", encoding="utf-8") as f:
            json.dump(live, f, ensure_ascii=False)
    counts["pbp"] = insert_pbp_from_live(conn, gid, live)
    # insert_pbp_from_live() is a no-op when the live feed has rolled off
    # (payload carries no events) -> previously captured PBP is left untouched,
    # never deleted, and pbp_loaded keeps its value.
    return counts


# ---------------------------------------------------------------------------
# Leaderboards
# ---------------------------------------------------------------------------
def load_leaderboards(conn, competition_id: int, codes=STAT_CODES) -> Dict[str, int]:
    res = {}
    for code in codes:
        pg = _api(fa.get_competition_players_game_highs, competition_id, code)
        _delay()
        tg = _api(fa.get_competition_teams_game_highs, competition_id, code)
        _delay()
        p_rows, t_rows = [], []
        for e in (pg or []):
            s = e.get("statistics", {}) or {}
            p_rows.append((
                competition_id, code, _si(e, "rank"), _player_id(e.get("personId")),
                e.get("firstName"), e.get("lastName"), e.get("nationality"),
                _player_id(e.get("gameId")), _utc(e.get("gameDate")),
                e.get("teamName"), _si(e, "teamScore"), e.get("vsTeamName"),
                _si(e, "vsTeamScore"), _num(s.get("Value")), s.get("RawValue"),
                _si(s, "PTS"), _si(s, "EFF"), _si(s, "FG2M"), _si(s, "FG2A"),
                _si(s, "FG3M"), _si(s, "FG3A"), _si(s, "FTM"), _si(s, "FTA"),
                _num(s.get("FTP")), json.dumps(e, ensure_ascii=False),
            ))
        for e in (tg or []):
            s = e.get("statistics", {}) or {}
            t_rows.append((
                competition_id, code, _si(e, "rank"), _player_id(e.get("competitionTeamId")),
                _player_id(e.get("gameId")), _utc(e.get("gameDate")),
                e.get("teamName"), _si(e, "teamScore"), e.get("vsTeamName"),
                _si(e, "vsTeamScore"), _num(s.get("Value")), s.get("RawValue"),
                json.dumps(e, ensure_ascii=False),
            ))
        if p_rows:
            db.upsert_many(conn, "competition_player_game_highs",
                           ["competition_id", "statistic_code", "rank", "person_id",
                            "first_name", "last_name", "nationality", "game_id",
                            "game_date", "team_name", "team_score", "vs_team_name",
                            "vs_team_score", "value", "raw_value", "pts", "eff",
                            "fg2_made", "fg2_att", "fg3_made", "fg3_att", "ft_made",
                            "ft_att", "ft_pct", "raw"],
                           ["competition_id", "statistic_code", "person_id",
                            "game_id"], p_rows)
        if t_rows:
            db.upsert_many(conn, "competition_team_game_highs",
                           ["competition_id", "statistic_code", "rank",
                            "competition_team_id", "game_id", "game_date", "team_name",
                            "team_score", "vs_team_name", "vs_team_score", "value",
                            "raw_value", "raw"],
                           ["competition_id", "statistic_code", "competition_team_id",
                            "game_id"], t_rows)
        res[code] = len(p_rows) + len(t_rows)
        print(f"    leaderboard[{code}]: {len(p_rows)} players + {len(t_rows)} teams")
    return res


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------
def run(competition_id: int = 208943, limit: Optional[int] = None,
        resume: bool = True, with_leaders: bool = True, archive: bool = True) -> None:
    conn = db.get_conn()
    try:
        # 1) Reference data from the games list.
        print(f"[1/4] Fetching games list for competition {competition_id} ...")
        games = _api(fa.getgdap, "getgdapgamesbycompetitionid",
                     gdapCompetitionId=competition_id)
        _delay()
        if not isinstance(games, list) or not games:
            print("  !! empty games list, aborting")
            return
        comp = (games[0].get("competition") or {})
        if not comp.get("competitionId"):
            comp = {"competitionId": competition_id}
        upsert_competition(conn, comp)
        rnds = _api(fa.get_rounds, competition_id) or []
        _delay()
        upsert_rounds(conn, competition_id, rnds if isinstance(rnds, list) else [])
        upsert_teams_from_games(conn, games)
        upsert_rounds_from_games(conn, competition_id, games)
        print(f"  games list: {len(games)} games; rounds: "
              f"{len(rnds) if isinstance(rnds, list) else 0}")

        # 2) Resume set (games already fully scraped).
        done = set()
        if resume:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT game_id FROM games WHERE competition_id=%s "
                    "AND boxscore_loaded", (competition_id,))
                done = {r[0] for r in cur.fetchall()}
        todo = [g for g in games if g.get("gameId") not in done]
        if limit:
            todo = todo[:limit]
        print(f"[2/4] Loading {len(todo)} games (resume={resume}, "
              f"already={len(done)}) ...")

        t0 = time.time()
        for i, g in enumerate(todo, 1):
            gid = g.get("gameId")
            try:
                upsert_games(conn, [g], competition_id)
                c = load_game(conn, g, archive=archive,
                              competition_id=competition_id)
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE games SET boxscore_loaded=TRUE WHERE game_id=%s", (gid,))
                    conn.commit()
                if i % 10 == 0 or i == len(todo):
                    print(f"  [{i}/{len(todo)}] game {gid}: players={c['players']} "
                          f"pstats={c['player_stats']} tstats={c['team_stats']} "
                          f"pbp={c['pbp']} ({(time.time()-t0):.0f}s)")
            except Exception as e:
                # A failed game aborts this connection's transaction; roll back so
                # the next game starts clean (otherwise every later game cascades
                # with InFailedSqlTransaction). Leave boxscore_loaded unset so a
                # re-run retries this game.
                try:
                    conn.rollback()
                except Exception:
                    pass
                print(f"  [{i}/{len(todo)}] game {gid} ERROR: {e!r}")
            _delay()

        # 3) Leaderboards.
        if with_leaders:
            print(f"[3/4] Loading leaderboards ({', '.join(STAT_CODES)}) ...")
            load_leaderboards(conn, competition_id, STAT_CODES)
        else:
            print("[3/4] Leaderboards skipped (--no-leaders)")

        # 4) Summary.
        print("[4/4] Summary:")
        with conn.cursor() as cur:
            for tbl in ("competitions", "rounds", "teams", "players", "games",
                        "game_team_stats", "game_player_stats", "play_by_play",
                        "competition_player_game_highs",
                        "competition_team_game_highs"):
                cur.execute(f"SELECT COUNT(*) FROM {tbl}")
                n = cur.fetchone()[0]
                print(f"    {tbl:32s}: {n}")
    finally:
        conn.close()


def main() -> None:
    ap = argparse.ArgumentParser(description="Batch-scrape a FIBA competition into the fiba DB.")
    ap.add_argument("competition_id", nargs="?", type=int, default=208943,
                    help="FIBA competition id (default 208943 = WC2027 European Qualifiers)")
    ap.add_argument("--limit", type=int, default=None,
                    help="Only load the first N games (smoke test)")
    ap.add_argument("--no-resume", action="store_true",
                    help="Ignore already-loaded games and reload everything")
    ap.add_argument("--no-leaders", action="store_true",
                    help="Skip the competition leaderboards")
    ap.add_argument("--no-archive", action="store_true",
                    help="Do not save raw JSON per game")
    args = ap.parse_args()
    run(competition_id=args.competition_id, limit=args.limit,
        resume=not args.no_resume, with_leaders=not args.no_leaders,
        archive=not args.no_archive)


if __name__ == "__main__":
    main()
