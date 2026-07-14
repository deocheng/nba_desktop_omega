"""NBACore v8 — Player Growth Report Service.

Builds a comprehensive career growth report for a player including:
- Bio + career totals
- Per-season trajectory (scoring, rebounds, assists, efficiency, etc.)
- Position evolution (games/minutes/points by position)
- Advanced metrics trajectory (PER, USG%, WS, BPM, VORP)
- Shooting profile evolution
- Scoring share of team total

Uses Layer 1 data loaders exclusively (no direct SQL).
"""
from __future__ import annotations

import logging

from backend.data_layer.growth_loader import (
    get_player_career_stats,
    get_player_career_summary,
    get_player_per_game_career,
    get_player_position_breakdown,
    get_player_shooting_career,
    get_team_season_points,
)

logger = logging.getLogger("nbacore.growth_report")

POSITION_MAP = {
    "PG": "控球后卫",
    "SG": "得分后卫",
    "SF": "小前锋",
    "PF": "大前锋",
    "C": "中锋",
}


def build_growth_report(player_id: str) -> dict:
    """Build a complete player growth report.

    Args:
        player_id: BBR player ID (e.g. 'jamesle01').

    Returns:
        dict with the following sections:
            - bio: player bio + career totals
            - seasons: per-season trajectory data
            - positions: position breakdown across career
            - milestones: key career milestones
    """
    # 1. Bio + career summary
    bio = get_player_career_summary(player_id)
    if not bio:
        return {}

    # 2. Per-season stats (totals + per_game combined)
    season_totals = get_player_career_stats(player_id)
    season_per_game = get_player_per_game_career(player_id)

    # Merge per-game into totals
    per_game_map = {}
    for pg in season_per_game:
        per_game_map[pg["season"]] = pg

    seasons = []
    for st in season_totals:
        season = st["season"]
        pg = per_game_map.get(season, {})
        combined = {**st}
        if pg:
            for k, v in pg.items():
                if k not in combined or combined[k] is None:
                    combined[k] = v

        # Compute per-game from totals if not available
        g = combined.get("g") or 0
        if g > 0:
            for total_key, pg_key in [
                ("pts", "pts_per_game"),
                ("trb", "trb_per_game"),
                ("ast", "ast_per_game"),
                ("stl", "stl_per_game"),
                ("blk", "blk_per_game"),
                ("tov", "tov_per_game"),
                ("orb", "orb_per_game"),
                ("drb", "drb_per_game"),
                ("mp", "mp_per_game"),
            ]:
                if combined.get(pg_key) is None and combined.get(total_key) is not None:
                    combined[pg_key] = round(combined[total_key] / g, 2)

        # Compute advanced ratios
        pf = combined.get("pf") or 0
        tov = combined.get("tov") or 0
        if pf > 0:
            combined["steal_block_per_foul"] = round(
                (combined.get("stl", 0) + combined.get("blk", 0)) / pf, 2
            )
        if tov > 0:
            combined["ast_per_tov"] = round(combined.get("ast", 0) / tov, 2)

        # Compute team scoring share (what % of team's points this player scored)
        team = combined.get("team")
        if team and season and combined.get("pts"):
            team_pts = get_team_season_points(team, season)
            if team_pts and team_pts > 0:
                combined["team_pts"] = team_pts
                combined["scoring_share"] = round(
                    combined["pts"] / team_pts * 100, 2
                )
            else:
                combined["scoring_share"] = None

        # Add position display name
        pos = combined.get("pos")
        if pos:
            combined["pos_cn"] = POSITION_MAP.get(pos, pos)

        seasons.append(combined)

    # 3. Position breakdown
    positions = get_player_position_breakdown(player_id)
    for p in positions:
        pos = p.get("pos", "")
        p["pos_cn"] = POSITION_MAP.get(pos, pos)

    # 4. Shooting profile data
    shooting = get_player_shooting_career(player_id)

    # 5. Compute milestones
    milestones = _compute_milestones(seasons, bio)

    return {
        "player_id": player_id,
        "bio": bio,
        "seasons": seasons,
        "positions": positions,
        "shooting": shooting,
        "milestones": milestones,
    }


def _compute_milestones(seasons: list[dict], bio: dict) -> list[dict]:
    """Compute key career milestones from season data.

    Args:
        seasons: List of per-season data (ordered by season ascending).
        bio: Player bio data.

    Returns:
        list[dict]: Milestones with season, type, label, value.
    """
    if not seasons:
        return []

    milestones = []
    first = seasons[0]
    last = seasons[-1]

    # Debut season
    milestones.append({
        "season": first.get("season"),
        "type": "debut",
        "label": "NBA 首秀",
        "value": f"{first.get('team', '')} · {first.get('pos', '')}",
        "detail": f"场均 {first.get('pts_per_game', 'N/A')} 分",
    })

    # Peak scoring season
    peak_score = max(seasons, key=lambda s: s.get("pts_per_game") or 0)
    milestones.append({
        "season": peak_score.get("season"),
        "type": "peak_scoring",
        "label": "得分巅峰",
        "value": f"{peak_score.get('pts_per_game')} PPG",
        "detail": f"USG% {peak_score.get('usg_percent')}",
    })

    # Peak PER season
    peak_per = max(seasons, key=lambda s: s.get("per") or 0)
    milestones.append({
        "season": peak_per.get("season"),
        "type": "peak_per",
        "label": "效率巅峰",
        "value": f"PER {peak_per.get('per')}",
        "detail": f"TS% {peak_per.get('ts_percent')}",
    })

    # Peak WS season
    peak_ws = max(seasons, key=lambda s: s.get("ws") or 0)
    milestones.append({
        "season": peak_ws.get("season"),
        "type": "peak_ws",
        "label": "胜利贡献巅峰",
        "value": f"WS {peak_ws.get('ws')}",
        "detail": f"VORP {peak_ws.get('vorp')}",
    })

    # First All-NBA calibre season (PER > 25)
    for s in seasons:
        if (s.get("per") or 0) >= 25:
            milestones.append({
                "season": s.get("season"),
                "type": "breakout",
                "label": "明星赛季",
                "value": f"PER {s.get('per')}",
                "detail": f"场均 {s.get('pts_per_game')} 分",
            })
            break

    # Position change milestones
    last_pos = None
    for s in seasons:
        pos = s.get("pos")
        if pos and pos != last_pos:
            if last_pos is not None:
                milestones.append({
                    "season": s.get("season"),
                    "type": "position_change",
                    "label": "位置转型",
                    "value": f"{last_pos} → {pos}",
                    "detail": f"场均 {s.get('pts_per_game')} 分",
                })
            last_pos = pos

    # Most recent season
    milestones.append({
        "season": last.get("season"),
        "type": "current",
        "label": "最新赛季",
        "value": f"{last.get('team', '')}",
        "detail": f"场均 {last.get('pts_per_game')} 分 · {last.get('pos', '')}",
    })

    # Sort by season
    milestones.sort(key=lambda m: m.get("season", 0))

    return milestones
