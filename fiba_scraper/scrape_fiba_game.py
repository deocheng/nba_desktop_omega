"""Scrape FIBA games and competition stat leaderboards, archiving raw JSON.

Usage:
    python scrape_fiba_game.py game 127081
    python scrape_fiba_game.py game https://www.fiba.basketball/.../games/127081-FRA-SLO
    python scrape_fiba_game.py competition 208943
    python scrape_fiba_game.py competition <stats_url>

Behaviour (matches the project's crawler iron rules):
  * Raw API JSON is archived atomically under raw_archive/{game_id}/ or
    raw_archive/competition_{id}/ (cache-first).
  * A readable text summary is printed.
  * No DB writes here — this module only collects + archives; DB load is a separate step.

Data sources (reverse-engineered from FIBA's frontend bundle):
  * Single game tabs (#playByPlay / #shotChart / #boxscore / #gameStats):
        GET /en/events/api/game-live-info/{id}/detail
        -> periodActions.content.items  (per-quarter PBP; act=="shot" events = shot chart)
        -> game.content.c                (per-team + per-player boxscore)
  * Competition tabs (#playersGameHighs / #teamsGameHighs):
        getgdapcompetitionplayersgamehighbyid / getgdapcompetitionteamsgamehighbyid
  * #teamsLeaders (getgdapcompetitionleaderbycompetitionid) is currently HTTP 500 on
    FIBA's backend (server fault) — not scraped.
  * #gameReport is a CMS prose article (HTML route), not structured data — not scraped.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from typing import Any, Dict, List

from fiba_api import (
    FIBAError,
    get_competition_id_from_stats_url,
    get_competition_players_game_highs,
    get_competition_teams_game_highs,
    get_game,
    get_game_boxscore,
    get_game_live_detail,
    get_rounds,
    parse_boxscore_from_live,
    parse_game_id,
    parse_play_by_play,
    parse_shot_chart,
)

HERE = os.path.dirname(os.path.abspath(__file__))
ARCHIVE = os.path.join(HERE, "raw_archive")

# Default statistic codes to pull for competition leaderboards.
# FIBA's game-highs function uses these codes (TRB/RPG/APG/SPG/BPG/ORB/DRB return null;
# the correct rebounds code is REB, and 3PM/FGM also work).
DEFAULT_STAT_CODES = ("PTS", "EFF", "REB", "AST", "STL", "BLK")


def _atomic_write(path: str, data: Any) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = None
    try:
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    finally:
        if tmp and os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass


def scrape_game(ref: str) -> Dict[str, Any]:
    gid = parse_game_id(ref)
    if gid is None:
        raise SystemExit(f"cannot parse game id from: {ref}")

    gdir = os.path.join(ARCHIVE, str(gid))
    game = get_game(gid)
    box = get_game_boxscore(gid)            # getgdap flat boxscore (26 players)
    try:
        live = get_game_live_detail(gid)
    except FIBAError as e:
        print(f"  [warn] live-detail fetch failed: {e}")
        live = None

    pbp = parse_play_by_play(live) if live else []
    shots = parse_shot_chart(live) if live else []
    boxscore_live = parse_boxscore_from_live(live) if live else []

    _atomic_write(os.path.join(gdir, "summary.json"), game)
    _atomic_write(os.path.join(gdir, "boxscore.json"), box)
    if live is not None:
        _atomic_write(os.path.join(gdir, "game_live_detail.json"), live)
        _atomic_write(os.path.join(gdir, "playbyplay.json"), pbp)
        _atomic_write(os.path.join(gdir, "shotchart.json"), shots)
        _atomic_write(os.path.join(gdir, "boxscore_live.json"), boxscore_live)

    return {
        "game_id": gid, "game": game, "boxscore": box,
        "live": live, "pbp_count": len(pbp), "shot_count": len(shots),
    }


def scrape_competition(ref: str, stat_codes=DEFAULT_STAT_CODES) -> Dict[str, Any]:
    # ref may be a competition id (int) or a stats page URL.
    cid = None
    if ref.isdigit():
        cid = int(ref)
    else:
        cid = get_competition_id_from_stats_url(ref)
    if cid is None:
        raise SystemExit(f"cannot resolve competition id from: {ref}")

    cdir = os.path.join(ARCHIVE, f"competition_{cid}")
    try:
        rounds = get_rounds(cid)
    except FIBAError as e:
        print(f"  [warn] rounds fetch failed: {e}")
        rounds = []
    saved = []
    for code in stat_codes:
        try:
            pgh = get_competition_players_game_highs(cid, code)
            tgh = get_competition_teams_game_highs(cid, code)
        except FIBAError as e:
            print(f"  [warn] stat {code} failed: {e}")
            continue
        _atomic_write(os.path.join(cdir, f"players_game_highs_{code}.json"), pgh)
        _atomic_write(os.path.join(cdir, f"teams_game_highs_{code}.json"), tgh)
        saved.append((code, len(pgh) if isinstance(pgh, list) else "?",
                      len(tgh) if isinstance(tgh, list) else "?"))
    return {"competition_id": cid, "rounds": rounds, "saved": saved}


def _player_name(p: Dict[str, Any]) -> str:
    if isinstance(p, dict):
        fn = p.get("firstName", "") or ""
        ln = p.get("lastName", "") or ""
        return f"{fn} {ln}".strip() or p.get("shortName", "") or str(p.get("personId", "?"))
    return str(p)


def print_game_summary(result: Dict[str, Any]) -> None:
    g = result["game"]
    box = result["boxscore"]
    a, b = g.get("teamA", {}), g.get("teamB", {})
    print("=" * 64)
    print(f"Game {result['game_id']}  ({g.get('roundName','')} / {g.get('roundType','')})")
    print(f"  {a.get('code')} {a.get('officialName')}  {g.get('teamAScore')} - "
          f"{g.get('teamBScore')}  {b.get('officialName')} {b.get('code')}")
    print(f"  Venue: {g.get('venueName')} ({g.get('hostCity')}, {g.get('hostCountry')})")
    print(f"  Spectators: {g.get('spectators')}  Date(UTC): {g.get('gameDateTimeUTC')}")
    periods = g.get("periods", [])
    if periods:
        qs = "  ".join(f"{p.get('name')}:{p.get('teamAScore')}-{p.get('teamBScore')}" for p in periods)
        print(f"  Quarters: {qs}")
    print(f"  playByPlay events: {result.get('pbp_count')}   shot-chart shots: {result.get('shot_count')}")
    print("-" * 64)
    if isinstance(box, list):
        by_team: Dict[str, List[Dict]] = {}
        for row in box:
            tcode = (row.get("team") or {}).get("code", "?")
            by_team.setdefault(tcode, []).append(row)
        for tcode, rows in by_team.items():
            print(f"  [{tcode}] {len(rows)} players")
            for row in sorted(rows, key=lambda r: -(r.get("points") or 0)):
                pname = _player_name(row.get("player", {}))
                line = (f"    {pname:24s} {('ST' if row.get('isStarter') else 'BN'):2s} "
                        f"{(row.get('points') or 0):3d}pts "
                        f"{(row.get('fieldGoalsMade') or 0)}/{(row.get('fieldGoalsAttempted') or 0)}FG "
                        f"{(row.get('threePointsMade') or 0)}/{(row.get('threePointsAttempted') or 0)}3P "
                        f"{(row.get('rebounds') or 0)}reb {(row.get('assists') or 0)}ast "
                        f"{(row.get('steals') or 0)}stl {(row.get('blockedShots') or 0)}blk "
                        f"{(row.get('plusMinus') or 0):+d}pm {(row.get('efficiency') or 0)}eff")
                print(line)
    else:
        print("  boxscore: (unexpected shape)", type(box))
    print("=" * 64)


def print_competition_summary(result: Dict[str, Any]) -> None:
    print("=" * 64)
    print(f"Competition {result['competition_id']}")
    rounds = result.get("rounds") or []
    if rounds:
        print(f"  Rounds ({len(rounds)}): " +
              ", ".join(f"{r.get('roundName','?')}({r.get('roundId')})" for r in rounds[:6]))
    print("  Saved leaderboards:")
    for code, np_, nt_ in result.get("saved", []):
        print(f"    {code:4s}  playersGameHighs={np_}  teamsGameHighs={nt_}")
    print("=" * 64)


def main() -> None:
    mode = sys.argv[1] if len(sys.argv) > 1 else "game"
    ref = sys.argv[2] if len(sys.argv) > 2 else "127081"
    if mode == "competition":
        result = scrape_competition(ref)
        print_competition_summary(result)
        print(f"\nRaw JSON archived under: {ARCHIVE}/competition_{result['competition_id']}/")
    else:
        result = scrape_game(ref)
        print_game_summary(result)
        print(f"\nRaw JSON archived under: {ARCHIVE}/{result['game_id']}/")


if __name__ == "__main__":
    main()
